from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.provider_runtime import (
    DEFAULT_PROVIDER_REGION,
    WorkspaceProviderRuntime,
    resolve_workspace_provider_runtime,
)
from app.models import ProviderCredential
from app.models.product import utc_now

DASHSCOPE_PROVIDER = "DASHSCOPE"


class CredentialCipher:
    def __init__(self, settings: Settings) -> None:
        secret = settings.user_credential_encryption_key
        if secret is None:
            raise AppError("用户凭证加密服务尚未配置。", 503)
        try:
            self.fernet = Fernet(secret.get_secret_value().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise AppError("用户凭证加密服务配置无效。", 503) from exc
        self.key_id = settings.user_credential_encryption_key_id

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self.fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise AppError("已保存的用户 API Key 无法解密，请重新绑定。", 409) from exc


class ProviderCredentialService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.cipher = CredentialCipher(settings)

    def get(
        self, workspace_id: int, provider: str = DASHSCOPE_PROVIDER
    ) -> ProviderCredential | None:
        return self.db.scalar(
            select(ProviderCredential).where(
                ProviderCredential.workspace_id == workspace_id,
                ProviderCredential.provider == provider,
                ProviderCredential.status == "ACTIVE",
            )
        )

    def set_dashscope_key(
        self,
        workspace_id: int,
        api_key: str,
        *,
        region: str = DEFAULT_PROVIDER_REGION,
        provider_workspace_id: str | None = None,
    ) -> ProviderCredential:
        normalized = api_key.strip()
        if len(normalized) < 8 or len(normalized) > 512:
            raise ValueError("API Key length is invalid")
        runtime = resolve_workspace_provider_runtime(
            api_key=normalized,
            region=region,
            provider_workspace_id=provider_workspace_id,
        )
        credential = self.get(workspace_id)
        now = utc_now()
        if credential is None:
            credential = ProviderCredential(
                workspace_id=workspace_id,
                provider=DASHSCOPE_PROVIDER,
                secret_ciphertext=self.cipher.encrypt(normalized),
                encryption_key_id=self.cipher.key_id,
                secret_hint=_secret_hint(normalized),
                provider_region=runtime.region,
                provider_workspace_ref=runtime.provider_workspace_id,
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
            self.db.add(credential)
        else:
            credential.secret_ciphertext = self.cipher.encrypt(normalized)
            credential.encryption_key_id = self.cipher.key_id
            credential.secret_hint = _secret_hint(normalized)
            credential.provider_region = runtime.region
            credential.provider_workspace_ref = runtime.provider_workspace_id
            credential.verified_at = None
            credential.updated_at = now
        self.db.flush()
        return credential

    def read_dashscope_key(self, workspace_id: int) -> str | None:
        credential = self.get(workspace_id)
        if credential is None:
            return None
        return self.cipher.decrypt(credential.secret_ciphertext)

    def read_verified_dashscope_key(self, workspace_id: int) -> str | None:
        credential = self.get(workspace_id)
        if credential is None or credential.verified_at is None:
            return None
        return self.cipher.decrypt(credential.secret_ciphertext)

    def read_dashscope_runtime(
        self, workspace_id: int, *, require_verified: bool = False
    ) -> WorkspaceProviderRuntime | None:
        credential = self.get(workspace_id)
        if credential is None or (require_verified and credential.verified_at is None):
            return None
        return resolve_workspace_provider_runtime(
            api_key=self.cipher.decrypt(credential.secret_ciphertext),
            region=credential.provider_region,
            provider_workspace_id=credential.provider_workspace_ref,
        )

    def set_dashscope_verified(
        self, workspace_id: int, *, verified: bool
    ) -> ProviderCredential | None:
        credential = self.get(workspace_id)
        if credential is None:
            return None
        credential.verified_at = utc_now() if verified else None
        credential.updated_at = utc_now()
        self.db.flush()
        return credential

    def delete_dashscope_key(self, workspace_id: int) -> bool:
        credential = self.get(workspace_id)
        if credential is None:
            return False
        self.db.delete(credential)
        self.db.flush()
        return True


def _secret_hint(value: str) -> str:
    suffix = value[-4:] if len(value) >= 4 else value
    return f"••••{suffix}"
