from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountActionToken, AuthSession, User
from app.models.product import utc_now
from app.services.demo_auth_service import hash_password, verify_password
from app.services.user_auth_service import normalize_email

EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
PASSWORD_RESET = "PASSWORD_RESET"


def find_active_user_by_email(db: Session, email: str) -> User | None:
    try:
        normalized = normalize_email(email)
    except ValueError:
        return None
    return db.scalar(
        select(User).where(User.email == normalized, User.status == "ACTIVE")
    )


def issue_account_action_token(
    db: Session,
    *,
    user_id: int,
    purpose: str,
    ttl_seconds: int,
    cooldown_seconds: int,
) -> str | None:
    now = utc_now()
    recent = db.scalar(
        select(AccountActionToken)
        .where(
            AccountActionToken.user_id == user_id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.consumed_at.is_(None),
            AccountActionToken.expires_at > now,
            AccountActionToken.created_at
            > now - timedelta(seconds=cooldown_seconds),
        )
        .order_by(AccountActionToken.created_at.desc())
    )
    if recent is not None:
        return None

    for previous in db.scalars(
        select(AccountActionToken).where(
            AccountActionToken.user_id == user_id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.consumed_at.is_(None),
        )
    ).all():
        previous.consumed_at = now

    token = secrets.token_urlsafe(48)
    db.add(
        AccountActionToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=_token_hash(token),
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_at=now,
        )
    )
    db.flush()
    return token


def verify_email_with_token(db: Session, token: str) -> bool:
    action_token = _active_token(db, token=token, purpose=EMAIL_VERIFICATION)
    if action_token is None:
        return False
    user = db.get(User, action_token.user_id)
    if user is None or user.status != "ACTIVE":
        return False
    now = utc_now()
    user.email_verified_at = user.email_verified_at or now
    user.updated_at = now
    _consume_user_tokens(db, user_id=user.id, purpose=EMAIL_VERIFICATION, now=now)
    db.flush()
    return True


def reset_password_with_token(
    db: Session,
    *,
    token: str,
    new_password: str,
) -> str:
    action_token = _active_token(db, token=token, purpose=PASSWORD_RESET)
    if action_token is None:
        return "INVALID"
    user = db.get(User, action_token.user_id)
    if user is None or user.status != "ACTIVE":
        return "INVALID"
    if verify_password(new_password, user.password_hash):
        return "UNCHANGED"

    now = utc_now()
    user.password_hash = hash_password(new_password)
    user.updated_at = now
    for auth_session in db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all():
        auth_session.revoked_at = now
    _consume_user_tokens(db, user_id=user.id, purpose=PASSWORD_RESET, now=now)
    db.flush()
    return "RESET"


def _active_token(
    db: Session,
    *,
    token: str,
    purpose: str,
) -> AccountActionToken | None:
    now = utc_now()
    return db.scalar(
        select(AccountActionToken).where(
            AccountActionToken.token_hash == _token_hash(token),
            AccountActionToken.purpose == purpose,
            AccountActionToken.consumed_at.is_(None),
            AccountActionToken.expires_at > now,
        )
    )


def _consume_user_tokens(
    db: Session,
    *,
    user_id: int,
    purpose: str,
    now,
) -> None:
    for action_token in db.scalars(
        select(AccountActionToken).where(
            AccountActionToken.user_id == user_id,
            AccountActionToken.purpose == purpose,
            AccountActionToken.consumed_at.is_(None),
        )
    ).all():
        action_token.consumed_at = now


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
