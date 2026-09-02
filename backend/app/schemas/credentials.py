from datetime import datetime
from typing import Literal

from pydantic import BaseModel, SecretStr


class DashScopeCredentialWrite(BaseModel):
    api_key: SecretStr


class ProviderCredentialRead(BaseModel):
    provider: str = "DASHSCOPE"
    configured: bool
    key_hint: str | None = None
    verified: bool = False
    verified_at: datetime | None = None
    updated_at: datetime | None = None


class ProviderCredentialVerificationRead(BaseModel):
    provider: str = "DASHSCOPE"
    status: Literal[
        "VERIFIED",
        "INVALID",
        "FORBIDDEN",
        "RATE_LIMITED",
        "UNAVAILABLE",
    ]
    verified: bool
    key_hint: str
    verified_at: datetime | None = None
    message: str
