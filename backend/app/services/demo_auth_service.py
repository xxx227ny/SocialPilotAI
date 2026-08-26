import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from app.core.config import Settings

SESSION_COOKIE_NAME = "socialpilot_session"
PASSWORD_HASH_ITERATIONS = 600_000


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        (
            "pbkdf2_sha256",
            str(PASSWORD_HASH_ITERATIONS),
            _encode(actual_salt),
            _encode(digest),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, expected_text = encoded.split("$", 3)
        iterations = int(iterations_text)
        salt = _decode(salt_text)
        expected = _decode(expected_text)
    except (TypeError, ValueError):
        return False
    if algorithm != "pbkdf2_sha256" or iterations < 100_000:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def credentials_are_valid(settings: Settings, username: str, password: str) -> bool:
    if not settings.enable_demo_auth:
        return False
    configured_username = (settings.demo_auth_username or "").strip()
    configured_hash = (
        settings.demo_auth_password_hash.get_secret_value()
        if settings.demo_auth_password_hash is not None
        else ""
    )
    username_matches = hmac.compare_digest(
        username.strip().casefold(), configured_username.casefold()
    )
    password_matches = verify_password(password, configured_hash)
    return username_matches and password_matches


def create_session_token(
    settings: Settings, username: str, *, now: int | None = None
) -> str:
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {
            "exp": issued_at + settings.demo_auth_session_ttl_seconds,
            "iat": issued_at,
            "sub": username,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_text = _encode(payload)
    signature = hmac.new(
        _session_secret(settings), payload_text.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{payload_text}.{_encode(signature)}"


def read_session_token(
    settings: Settings, token: str | None, *, now: int | None = None
) -> AuthenticatedUser | None:
    if not settings.enable_demo_auth or not token:
        return None
    try:
        payload_text, signature_text = token.split(".", 1)
        expected_signature = hmac.new(
            _session_secret(settings), payload_text.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(signature_text), expected_signature):
            return None
        payload = json.loads(_decode(payload_text).decode("utf-8"))
        expires_at = int(payload["exp"])
        username = str(payload["sub"])
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    current_time = int(time.time()) if now is None else now
    configured_username = (settings.demo_auth_username or "").strip()
    if expires_at <= current_time or not hmac.compare_digest(
        username.casefold(), configured_username.casefold()
    ):
        return None
    return AuthenticatedUser(username=configured_username)


def _session_secret(settings: Settings) -> bytes:
    if settings.demo_auth_session_secret is None:
        return b""
    return settings.demo_auth_session_secret.get_secret_value().encode("utf-8")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
