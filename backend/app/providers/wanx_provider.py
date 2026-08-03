from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, settings
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderModelError,
)
from app.providers.live_configuration import (
    WANX_REGION_HOSTS,
    audit_live_provider_configuration,
    controlled_wanx_endpoint,
    metadata_for_http_failure,
    metadata_for_transport_failure,
    provider_error_from_metadata,
)
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskStatus,
    VisualTaskSubmission,
)

WANX_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
    "UNKNOWN",
}
WANX_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4"}
WANX_RESOLUTIONS = {"720P", "1080P"}


class WanxProvider(VisualGenerationProvider):
    """Wan2.7 text-to-video adapter using Model Studio's async HTTP API."""

    def __init__(
        self,
        app_settings: Settings = settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if (
            app_settings.wanx_api_key is None
            or not app_settings.wanx_api_key.get_secret_value().strip()
        ):
            raise ProviderAuthenticationError(
                "Wanx API credentials are not configured"
            )

        configuration = audit_live_provider_configuration(app_settings)
        if (
            app_settings.require_live_provider_coherence
            and not configuration.wanx.ready
        ):
            raise ProviderConfigurationError(
                "Wanx live provider configuration is inconsistent"
            )
        if app_settings.wanx_endpoint and (
            not controlled_wanx_endpoint(app_settings.wanx_endpoint)
            or (
                not configuration.wanx.endpoint_valid
                and transport is None
            )
        ):
            raise ProviderConfigurationError("Wanx endpoint is invalid")

        self.api_key = app_settings.wanx_api_key.get_secret_value().strip()
        self.model = app_settings.wanx_model
        self.endpoint = (
            configuration.wanx_endpoint
            if app_settings.require_live_provider_coherence
            else (
                controlled_wanx_endpoint(app_settings.wanx_endpoint)
                if transport is not None and app_settings.wanx_endpoint
                else self._resolve_endpoint(app_settings)
            )
        )
        self.timeout = app_settings.wanx_timeout
        self.transport = transport

    async def submit(
        self, request: VisualGenerationRequest
    ) -> VisualTaskSubmission:
        self._validate_request(request)
        payload = await self._request(
            "POST",
            "/services/aigc/video-generation/video-synthesis",
            enable_async=True,
            json={
                "model": self.model,
                "input": {"prompt": request.prompt.strip()},
                "parameters": {
                    "duration": request.duration_seconds,
                    "ratio": request.aspect_ratio,
                    "resolution": request.resolution,
                },
            },
        )
        output = self._require_output(payload)
        task_id = self._require_text(output, "task_id")
        return VisualTaskSubmission(
            provider_task_id=task_id,
            provider_request_id=self._optional_text(payload, "request_id"),
            status=self._parse_status(output),
        )

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        task_id = provider_task_id.strip()
        if not task_id:
            raise ProviderModelError("Wanx task ID cannot be empty")
        payload = await self._request(
            "GET", f"/tasks/{quote(task_id, safe='')}"
        )
        output = self._require_output(payload)
        returned_task_id = self._require_text(output, "task_id")
        status = self._parse_status(output)
        usage = payload.get("usage")
        metadata: dict[str, object] = {
            key: value
            for key in ("submit_time", "scheduled_time", "end_time")
            if (value := output.get(key)) is not None
        }
        if isinstance(usage, dict):
            metadata["usage"] = usage
        return VisualTaskSnapshot(
            provider_task_id=returned_task_id,
            provider_request_id=self._optional_text(payload, "request_id"),
            status=status,
            error_code=self._optional_text(output, "code"),
            error_message=self._optional_text(output, "message"),
            provider_output_url=self._optional_text(output, "video_url"),
            metadata=metadata,
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
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.endpoint}/{path.lstrip('/')}",
                    headers=headers,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            metadata = metadata_for_transport_failure(
                provider="wanx", phase=self._phase(method, path), error=exc
            )
            error = provider_error_from_metadata(metadata)
            error.args = ("Wanx request timed out",)
            raise error from exc
        except httpx.RequestError as exc:
            metadata = metadata_for_transport_failure(
                provider="wanx", phase=self._phase(method, path), error=exc
            )
            error = provider_error_from_metadata(metadata)
            error.args = ("Wanx service is unavailable",)
            raise error from exc

        if response.is_error:
            code, request_id = self._safe_response_identifiers(response)
            metadata = metadata_for_http_failure(
                provider="wanx",
                phase=self._phase(method, path),
                http_status=response.status_code,
                provider_code=code,
                request_id=request_id,
            )
            error = provider_error_from_metadata(metadata)
            messages = {
                "authentication_failed": "Wanx authentication failed",
                "permission_denied": "Wanx permission denied",
                "rate_or_quota_limited": "Wanx request was rate limited",
                "endpoint_or_model_not_found": (
                    "Wanx endpoint or model was not found"
                ),
                "invalid_request": "Wanx request parameters are invalid",
                "provider_service_error": "Wanx service is unavailable",
            }
            error.args = (
                messages.get(
                    metadata.safe_error_code or "", "Wanx request failed"
                ),
            )
            raise error
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderModelError("Wanx returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderModelError("Wanx returned an invalid response")
        return payload

    @staticmethod
    def _resolve_endpoint(app_settings: Settings) -> str:
        if app_settings.wanx_endpoint:
            audit = audit_live_provider_configuration(app_settings)
            if not audit.wanx.endpoint_valid:
                raise ProviderConfigurationError("Wanx endpoint is invalid")
            return audit.wanx_endpoint
        workspace_id = (app_settings.wanx_workspace_id or "").strip()
        host_template = WANX_REGION_HOSTS.get(app_settings.wanx_region)
        if not workspace_id or host_template is None:
            raise ProviderConfigurationError(
                "Wanx endpoint configuration is incomplete"
            )
        host = host_template.format(workspace_id=workspace_id)
        return f"https://{host}/api/v1"

    @staticmethod
    def _phase(method: str, path: str) -> str:
        if method == "POST":
            return "submit"
        return "refresh" if "/tasks/" in path else "request"

    @staticmethod
    def _safe_response_identifiers(
        response: httpx.Response,
    ) -> tuple[object, object]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        code = payload.get("code") if isinstance(payload, dict) else None
        request_id = None
        if isinstance(payload, dict):
            request_id = payload.get("request_id") or payload.get("requestId")
        if request_id is None:
            request_id = response.headers.get("x-request-id")
        return code, request_id

    @staticmethod
    def _validate_request(request: VisualGenerationRequest) -> None:
        if not request.prompt.strip():
            raise ProviderModelError("Wanx prompt cannot be empty")
        if request.duration_seconds < 2 or request.duration_seconds > 15:
            raise ProviderModelError("Wanx duration must be between 2 and 15 seconds")
        if request.aspect_ratio not in WANX_RATIOS:
            raise ProviderModelError("Wanx aspect ratio is not supported")
        if request.resolution not in WANX_RESOLUTIONS:
            raise ProviderModelError("Wanx resolution is not supported")

    @staticmethod
    def _require_output(payload: dict[str, Any]) -> dict[str, Any]:
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ProviderModelError("Wanx response does not contain task output")
        return output

    @staticmethod
    def _require_text(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProviderModelError(f"Wanx response is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_text(data: dict[str, Any], key: str) -> str | None:
        value = data.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @classmethod
    def _parse_status(cls, output: dict[str, Any]) -> VisualTaskStatus:
        status = cls._require_text(output, "task_status").upper()
        if status not in WANX_STATUSES:
            raise ProviderModelError("Wanx returned an unknown task status")
        return status  # type: ignore[return-value]
