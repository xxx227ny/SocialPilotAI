from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AppError


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
