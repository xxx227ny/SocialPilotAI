from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

DASHSCOPE_MODEL_LIST_URL = "https://dashscope.aliyuncs.com/api/v1/models"
VerificationStatus = Literal[
    "VERIFIED",
    "INVALID",
    "FORBIDDEN",
    "RATE_LIMITED",
    "UNAVAILABLE",
]


@dataclass(frozen=True, slots=True)
class CredentialVerificationResult:
    status: VerificationStatus
    verified: bool
    message: str


class DashScopeCredentialVerifier:
    """Authenticate a DashScope key without starting billable generation."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(timeout_seconds, 5),
        )
        self.transport = transport

    def verify(
        self, api_key: str, *, models_endpoint: str = DASHSCOPE_MODEL_LIST_URL
    ) -> CredentialVerificationResult:
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
                trust_env=True,
                follow_redirects=False,
            ) as client:
                response = client.get(
                    models_endpoint,
                    params={
                        "capabilities": "TG",
                        "page_no": 1,
                        "page_size": 1,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                )
        except httpx.RequestError:
            return CredentialVerificationResult(
                status="UNAVAILABLE",
                verified=False,
                message="暂时无法连接阿里云百炼，Key 尚未验证；不会自动重试。",
            )

        if response.status_code == 200:
            return CredentialVerificationResult(
                status="VERIFIED",
                verified=True,
                message="API Key 验证通过，已启用当前工作区的 AI 功能。",
            )
        if response.status_code == 401:
            return CredentialVerificationResult(
                status="INVALID",
                verified=False,
                message="API Key 无效，或 Key 与华北2（北京）地域不匹配。",
            )
        if response.status_code == 403:
            return CredentialVerificationResult(
                status="FORBIDDEN",
                verified=False,
                message="API Key 已被拒绝访问，请检查百炼服务与业务空间权限。",
            )
        if response.status_code == 429:
            return CredentialVerificationResult(
                status="RATE_LIMITED",
                verified=False,
                message="阿里云百炼暂时限制了验证请求，请稍后手动重试。",
            )
        return CredentialVerificationResult(
            status="UNAVAILABLE",
            verified=False,
            message="阿里云百炼暂时无法完成验证，Key 尚未启用；不会自动重试。",
        )
