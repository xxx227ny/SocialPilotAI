from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LoginThrottle
from app.models.product import utc_now


@dataclass(frozen=True, slots=True)
class LoginThrottleDecision:
    allowed: bool
    retry_after_seconds: int = 0


class LoginThrottleService:
    """Persist bounded login failures without storing email or address values."""

    def __init__(
        self,
        session: Session,
        *,
        max_failures: int,
        window_seconds: int,
        lock_seconds: int,
    ) -> None:
        self.session = session
        self.max_failures = max_failures
        self.window = timedelta(seconds=window_seconds)
        self.lock = timedelta(seconds=lock_seconds)

    def check(self, email: str, remote_address: str | None) -> LoginThrottleDecision:
        record = self._get(email, remote_address)
        if record is None:
            return LoginThrottleDecision(True)
        now = utc_now()
        locked_until = _utc(record.locked_until)
        if locked_until is not None and locked_until > now:
            return LoginThrottleDecision(
                False,
                max(1, math.ceil((locked_until - now).total_seconds())),
            )
        if _utc(record.window_started_at) + self.window <= now:
            self.session.delete(record)
            self.session.flush()
        return LoginThrottleDecision(True)

    def record_failure(
        self, email: str, remote_address: str | None
    ) -> LoginThrottleDecision:
        now = utc_now()
        record = self._get(email, remote_address)
        if record is None:
            record = LoginThrottle(
                scope_hash=_scope_hash(email, remote_address),
                failure_count=0,
                window_started_at=now,
                updated_at=now,
            )
            self.session.add(record)
        elif _utc(record.window_started_at) + self.window <= now:
            record.failure_count = 0
            record.window_started_at = now
            record.locked_until = None
        record.failure_count += 1
        record.updated_at = now
        if record.failure_count >= self.max_failures:
            record.locked_until = now + self.lock
            self.session.flush()
            return LoginThrottleDecision(False, math.ceil(self.lock.total_seconds()))
        self.session.flush()
        return LoginThrottleDecision(True)

    def clear(self, email: str, remote_address: str | None) -> None:
        record = self._get(email, remote_address)
        if record is not None:
            self.session.delete(record)
            self.session.flush()

    def _get(self, email: str, remote_address: str | None) -> LoginThrottle | None:
        return self.session.scalar(
            select(LoginThrottle).where(
                LoginThrottle.scope_hash == _scope_hash(email, remote_address)
            )
        )


def _scope_hash(email: str, remote_address: str | None) -> str:
    normalized_email = email.strip().casefold()
    normalized_address = (remote_address or "unknown").strip().casefold()
    material = f"login-throttle-v1\x00{normalized_email}\x00{normalized_address}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
