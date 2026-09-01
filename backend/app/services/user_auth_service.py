from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuthSession, Membership, User, Workspace
from app.models.product import utc_now
from app.services.demo_auth_service import hash_password, verify_password

SESSION_COOKIE_NAME = "socialpilot_session"
_DUMMY_PASSWORD_HASH = hash_password(
    "invalid-user-password", salt=b"socialpilot-auth-dummy"
)


class DuplicateEmailError(ValueError):
    """Raised when a registration email already exists."""


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: int
    workspace_id: int
    email: str
    role: str


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    local, separator, domain = normalized.partition("@")
    if not separator or not local or "." not in domain or domain.startswith("."):
        raise ValueError("Email address is invalid")
    return normalized


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    workspace_name: str | None,
    session_ttl_seconds: int,
) -> tuple[AuthenticatedPrincipal, str]:
    normalized_email = normalize_email(email)
    existing = db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise DuplicateEmailError("Email is already registered")
    user = User(email=normalized_email, password_hash=hash_password(password))
    default_name = f"{normalized_email.split('@', 1)[0][:80]} 的工作区"
    normalized_workspace_name = (
        workspace_name.strip() if workspace_name is not None else default_name
    )
    if len(normalized_workspace_name) < 2:
        raise ValueError("Workspace name is invalid")
    workspace = Workspace(name=normalized_workspace_name)
    membership = Membership(user=user, workspace=workspace, role="OWNER")
    db.add_all((user, workspace, membership))
    db.flush()
    token = create_session(
        db,
        user_id=user.id,
        workspace_id=workspace.id,
        session_ttl_seconds=session_ttl_seconds,
    )
    return (
        AuthenticatedPrincipal(
            user_id=user.id,
            workspace_id=workspace.id,
            email=user.email,
            role=membership.role,
        ),
        token,
    )


def login_user(
    db: Session,
    *,
    email: str,
    password: str,
    session_ttl_seconds: int,
) -> tuple[AuthenticatedPrincipal, str] | None:
    try:
        normalized_email = normalize_email(email)
    except ValueError:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    user = db.scalar(select(User).where(User.email == normalized_email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    if not verify_password(password, password_hash):
        return None
    if user is None or user.status != "ACTIVE":
        return None
    membership = db.scalar(
        select(Membership)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(
            Membership.user_id == user.id,
            Membership.status == "ACTIVE",
            Workspace.status == "ACTIVE",
        )
        .order_by(Membership.id)
    )
    if membership is None:
        return None
    token = create_session(
        db,
        user_id=user.id,
        workspace_id=membership.workspace_id,
        session_ttl_seconds=session_ttl_seconds,
    )
    return (
        AuthenticatedPrincipal(
            user_id=user.id,
            workspace_id=membership.workspace_id,
            email=user.email,
            role=membership.role,
        ),
        token,
    )


def create_session(
    db: Session,
    *,
    user_id: int,
    workspace_id: int,
    session_ttl_seconds: int,
) -> str:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    db.add(
        AuthSession(
            user_id=user_id,
            workspace_id=workspace_id,
            token_hash=_token_hash(token),
            family_id=secrets.token_hex(16),
            expires_at=now + timedelta(seconds=session_ttl_seconds),
            created_at=now,
            last_used_at=now,
        )
    )
    db.flush()
    return token


def read_session(db: Session, token: str | None) -> AuthenticatedPrincipal | None:
    if not token:
        return None
    now = utc_now()
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    if auth_session is None:
        return None
    user = db.get(User, auth_session.user_id)
    workspace = db.get(Workspace, auth_session.workspace_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == auth_session.user_id,
            Membership.workspace_id == auth_session.workspace_id,
            Membership.status == "ACTIVE",
        )
    )
    if (
        user is None
        or workspace is None
        or membership is None
        or user.status != "ACTIVE"
        or workspace.status != "ACTIVE"
    ):
        return None
    return AuthenticatedPrincipal(
        user_id=user.id,
        workspace_id=workspace.id,
        email=user.email,
        role=membership.role,
    )


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    auth_session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if auth_session is not None:
        auth_session.revoked_at = utc_now()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
