from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, settings
from app.execution.credential_context import current_execution_provider_runtime
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
    ProviderTimeoutError,
)
from app.providers.live_configuration import (
    effective_happyhorse_endpoint,
    effective_qwen_api_key,
)
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskStatus,
    VisualTaskSubmission,
)

TOKEN_PLAN_VIDEO_ENDPOINT = "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1"
HAPPYHORSE_MODEL = "happyhorse-1.1-r2v"
HAPPYHORSE_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
    "UNKNOWN",
}


class HappyHorseProvider(VisualGenerationProvider):
    """HappyHorse reference-to-video adapter for the competition Token Plan."""

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = effective_qwen_api_key(app_settings)
        if not self.api_key:
            raise ProviderAuthenticationError(
                "HappyHorse API credentials are not configured"
            )
        endpoint = effective_happyhorse_endpoint(app_settings).rstrip("/")
        if (
            endpoint != TOKEN_PLAN_VIDEO_ENDPOINT
            and current_execution_provider_runtime() is None
            and transport is None
        ):
            raise ProviderConfigurationError("HappyHorse endpoint is invalid")
        if app_settings.happyhorse_model != HAPPYHORSE_MODEL:
            raise ProviderConfigurationError("HappyHorse model is invalid")
        self.endpoint = endpoint
        self.model = app_settings.happyhorse_model
        self.timeout = app_settings.happyhorse_timeout
        self.transport = transport

    async def submit(self, request: VisualGenerationRequest) -> VisualTaskSubmission:
        self._validate_request(request)
        media = [
            {
                "type": "reference_image",
                "url": (
                    f"data:{image.content_type};base64,"
                    f"{base64.b64encode(image.content).decode('ascii')}"
                ),
            }
            for image in request.reference_images
        ]
        payload = await self._request(
            "POST",
            "/services/aigc/video-generation/video-synthesis",
            enable_async=True,
            json={
                "model": self.model,
                "input": {"prompt": request.prompt.strip(), "media": media},
                "parameters": {
                    "duration": request.duration_seconds,
                    "ratio": request.aspect_ratio,
                    "resolution": request.resolution,
                },
            },
        )
        output = self._require_output(payload)
        return VisualTaskSubmission(
            provider_task_id=self._require_text(output, "task_id"),
            provider_request_id=self._optional_text(payload, "request_id"),
            status=self._parse_status(output),
        )

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        task_id = provider_task_id.strip()
        if not task_id:
            raise ProviderModelError("HappyHorse task ID cannot be empty")
        payload = await self._request("GET", f"/tasks/{quote(task_id, safe='')}")
        output = self._require_output(payload)
        return VisualTaskSnapshot(
            provider_task_id=self._require_text(output, "task_id"),
            provider_request_id=self._optional_text(payload, "request_id"),
            status=self._parse_status(output),
            error_code=self._optional_text(output, "code"),
            error_message=self._optional_text(output, "message"),
            provider_output_url=self._optional_text(output, "video_url"),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        enable_async: bool = False,
        json: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if enable_async:
            headers["X-DashScope-Async"] = "enable"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport
            ) as client:
                response = await client.request(
                    method,
                    f"{self.endpoint}/{path.lstrip('/')}",
                    headers=headers,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("HappyHorse request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError("HappyHorse service is unavailable") from exc
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("HappyHorse authentication failed")
        if response.status_code == 429:
            raise ProviderQuotaError("HappyHorse quota or rate limit was reached")
        if response.is_error:
            raise ProviderModelError("HappyHorse request was rejected")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderModelError("HappyHorse returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderModelError("HappyHorse returned an invalid response")
        return payload

    @staticmethod
    def _validate_request(request: VisualGenerationRequest) -> None:
        if not request.prompt.strip():
            raise ProviderModelError("HappyHorse prompt cannot be empty")
        if request.duration_seconds != 15:
            raise ProviderModelError("HappyHorse product video must be 15 seconds")
        if request.aspect_ratio != "9:16":
            raise ProviderModelError("HappyHorse product video must use 9:16")
        if request.resolution not in {"720P", "1080P"}:
            raise ProviderModelError("HappyHorse resolution is not supported")
        if not 1 <= len(request.reference_images) <= 9:
            raise ProviderModelError(
                "HappyHorse requires between one and nine reference images"
            )
        if any(not image.content for image in request.reference_images):
            raise ProviderModelError("HappyHorse reference image is empty")

    @staticmethod
    def _require_output(payload: dict[str, Any]) -> dict[str, Any]:
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ProviderModelError("HappyHorse response does not contain task output")
        return output

    @staticmethod
    def _require_text(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProviderModelError(f"HappyHorse response is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_text(data: dict[str, Any], key: str) -> str | None:
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @classmethod
    def _parse_status(cls, output: dict[str, Any]) -> VisualTaskStatus:
        status = cls._require_text(output, "task_status").upper()
        if status not in HAPPYHORSE_STATUSES:
            raise ProviderModelError("HappyHorse returned an unknown task status")
        return status  # type: ignore[return-value]
