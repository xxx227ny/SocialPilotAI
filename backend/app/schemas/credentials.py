from datetime import datetime

from pydantic import BaseModel, SecretStr


class DashScopeCredentialWrite(BaseModel):
    api_key: SecretStr


class ProviderCredentialRead(BaseModel):
    provider: str = "DASHSCOPE"
    configured: bool
    key_hint: str | None = None
    verified: bool = False
    updated_at: datetime | None = None
