from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AppError


def validated_social_frontend_origin(settings: Settings) -> str:
    """Return the configured OAuth result origin after strict validation."""
    base = settings.social_frontend_base_url.strip().rstrip("/")
    parsed = urlparse(base)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise AppError("Social frontend redirect is not allowed", 503) from exc
    hostname = (parsed.hostname or "").casefold()
    loopback = hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and not loopback)
        or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
    ):
        raise AppError("Social frontend redirect is not allowed", 503)
    return f"{parsed.scheme}://{parsed.netloc}"


class TokenCipher:
    def __init__(self, settings: Settings) -> None:
        secret = settings.social_token_encryption_key
        if secret is None:
            raise AppError("Social token encryption is not configured", 503)
        try:
            self.fernet = Fernet(secret.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise AppError(
                "Social token encryption configuration is invalid", 503
            ) from exc
        self.key_id = settings.social_token_encryption_key_id

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self.fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise AppError("Stored social credential is unavailable", 409) from exc


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def digest_oauth_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
