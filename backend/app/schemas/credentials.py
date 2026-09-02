from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


class DashScopeCredentialWrite(BaseModel):
    api_key: SecretStr
    region: Literal["cn-beijing"] = "cn-beijing"
    provider_workspace_id: str | None = Field(default=None, max_length=63)

    @field_validator("provider_workspace_id")
    @classmethod
    def normalize_workspace_id(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None


class ProviderCredentialRead(BaseModel):
    provider: str = "DASHSCOPE"
    configured: bool
    key_hint: str | None = None
    region: Literal["cn-beijing"] = "cn-beijing"
    provider_workspace_id: str | None = None
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
    region: Literal["cn-beijing"]
    provider_workspace_id: str | None
    verified_at: datetime | None = None
    message: str
