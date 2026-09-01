from __future__ import annotations

import errno
import hashlib
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.core.exceptions import SafeProviderFailure
from app.execution.credential_context import (
    current_execution_api_key,
    execution_api_key_is_bound,
)
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelError,
    ProviderQuotaError,
    ProviderTimeoutError,
)

SUPPORTED_REGIONS = {"cn-beijing"}
QWEN_REGION_ENDPOINT_TEMPLATES = {
    "cn-beijing": (
        "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    ),
}
WANX_REGION_ENDPOINT_TEMPLATES = {
    "cn-beijing": ("https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1"),
}
WANX_REGION_HOSTS = {
    region: template.removeprefix("https://").removesuffix("/api/v1")
    for region, template in WANX_REGION_ENDPOINT_TEMPLATES.items()
}
QWEN_MODELS = {"qwen-plus", "qwen3.7-plus"}
WANX_MODELS = {"wan2.7-t2v"}
TOKEN_PLAN_QWEN_ENDPOINT = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)
TOKEN_PLAN_MULTIMODAL_ENDPOINT = (
    "https://token-plan.cn-beijing.maas.aliyuncs.com/api/v1"
)

ProviderName = Literal["qwen", "wanx"]
CONNECTION_FAILURE_CODES = frozenset(
    {
        "dns_resolution_failed",
        "tcp_connection_refused",
        "connect_timeout",
        "network_unreachable",
        "tls_handshake_failed",
        "tls_certificate_failed",
        "proxy_unavailable",
        "connection_reset_before_request",
        "connection_failed_unknown",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    credentials_configured: bool
    workspace_configured: bool
    region_supported: bool
    endpoint_valid: bool
    model_configured: bool
    ready: bool
    missing_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiveProviderConfiguration:
    qwen_endpoint: str
    wanx_endpoint: str
    qwen: ProviderReadiness
    wanx: ProviderReadiness

    @property
    def qwen_ready(self) -> bool:
        return self.qwen.ready

    @property
    def wanx_ready(self) -> bool:
        return self.wanx.ready

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (*self.qwen.missing_requirements, *self.wanx.missing_requirements)
            )
        )


@dataclass(frozen=True, slots=True)
class ProviderFailureMetadata:
    provider: ProviderName
    phase: str
    http_status: int | None
    safe_error_code: str | None
    request_id_digest: str | None
    uncertain: bool
    potentially_billable: bool
    occurred_at: str


def audit_live_provider_configuration(
    settings: Settings,
) -> LiveProviderConfiguration:
    qwen_endpoint, qwen_endpoint_valid = _resolve_endpoint(
        explicit=settings.qwen_endpoint,
        workspace_id=settings.qwen_workspace_id,
        region=settings.qwen_region,
        templates=QWEN_REGION_ENDPOINT_TEMPLATES,
    )
    wanx_endpoint, wanx_endpoint_valid = _resolve_endpoint(
        explicit=settings.wanx_endpoint,
        workspace_id=settings.wanx_workspace_id,
        region=settings.wanx_region,
        templates=WANX_REGION_ENDPOINT_TEMPLATES,
    )
    qwen_token_plan = qwen_endpoint == TOKEN_PLAN_QWEN_ENDPOINT
    wanx_token_plan = wanx_endpoint == TOKEN_PLAN_MULTIMODAL_ENDPOINT
    qwen_endpoint_valid = qwen_endpoint_valid or qwen_token_plan
    wanx_endpoint_valid = wanx_endpoint_valid or wanx_token_plan
    qwen = _provider_readiness(
        provider="qwen",
        credentials_configured=bool(effective_qwen_api_key(settings)),
        workspace_configured=bool(_text(settings.qwen_workspace_id)) or qwen_token_plan,
        region_supported=_text(settings.qwen_region) in SUPPORTED_REGIONS,
        endpoint_valid=qwen_endpoint_valid,
        model_configured=_text(settings.qwen_model) in QWEN_MODELS,
    )
    wanx = _provider_readiness(
        provider="wanx",
        credentials_configured=bool(effective_wanx_api_key(settings)),
        workspace_configured=bool(_text(settings.wanx_workspace_id)) or wanx_token_plan,
        region_supported=_text(settings.wanx_region) in SUPPORTED_REGIONS,
        endpoint_valid=wanx_endpoint_valid,
        model_configured=_text(settings.wanx_model) in WANX_MODELS,
    )
    return LiveProviderConfiguration(
        qwen_endpoint=qwen_endpoint,
        wanx_endpoint=wanx_endpoint,
        qwen=qwen,
        wanx=wanx,
    )


def qwen_provider_configured(settings: Settings) -> bool:
    if not settings.require_live_provider_coherence:
        return bool(effective_qwen_api_key(settings))
    return audit_live_provider_configuration(settings).qwen.ready


def qwen_missing_requirements(settings: Settings) -> tuple[str, ...]:
    if settings.require_live_provider_coherence:
        return audit_live_provider_configuration(settings).qwen.missing_requirements
    return (
        () if effective_qwen_api_key(settings) else ("qwen_credentials_configuration",)
    )


def wanx_provider_configured(settings: Settings) -> bool:
    if not settings.require_live_provider_coherence:
        return bool(effective_wanx_api_key(settings)) and bool(
            (settings.wanx_endpoint or "").strip()
            or (
                _text(settings.wanx_workspace_id)
                and _text(settings.wanx_region) in WANX_REGION_ENDPOINT_TEMPLATES
            )
        )
    return audit_live_provider_configuration(settings).wanx.ready


def wanx_missing_requirements(settings: Settings) -> tuple[str, ...]:
    if settings.require_live_provider_coherence:
        return audit_live_provider_configuration(settings).wanx.missing_requirements
    missing: list[str] = []
    if not effective_wanx_api_key(settings):
        missing.append("wanx_credentials_configuration")
    if not (
        (settings.wanx_endpoint or "").strip()
        or (
            _text(settings.wanx_workspace_id)
            and _text(settings.wanx_region) in WANX_REGION_ENDPOINT_TEMPLATES
        )
    ):
        missing.append("wanx_endpoint_configuration")
    return tuple(missing)


def effective_qwen_api_key(settings: Settings) -> str:
    """Return credentials paired with the configured provider endpoint."""
    if execution_api_key_is_bound():
        return current_execution_api_key() or ""
    if settings.enable_user_auth:
        return ""
    if _token_plan_credentials_selected(settings):
        return (
            _secret_file(settings.token_plan_api_key_file)
            or _secret(settings.qwen_api_key)
            or _secret(settings.dashscope_api_key)
        )
    return (
        _secret(settings.qwen_api_key)
        or _secret(settings.dashscope_api_key)
        or _secret_file(settings.token_plan_api_key_file)
    )


def effective_wanx_api_key(settings: Settings) -> str:
    """Use credentials paired with the active Qwen/Wanx provider profile."""
    if execution_api_key_is_bound():
        return current_execution_api_key() or ""
    if settings.enable_user_auth:
        return ""
    if _token_plan_credentials_selected(settings):
        return _secret_file(settings.token_plan_api_key_file) or _secret(
            settings.wanx_api_key
        )
    return _secret(settings.wanx_api_key) or _secret_file(
        settings.token_plan_api_key_file
    )


def _token_plan_credentials_selected(settings: Settings) -> bool:
    return _normalize_endpoint(settings.qwen_endpoint) == TOKEN_PLAN_QWEN_ENDPOINT


def controlled_qwen_endpoint(value: str | None) -> str:
    normalized = _normalize_endpoint(value)
    return normalized if normalized.endswith("/compatible-mode/v1") else ""


def controlled_wanx_endpoint(value: str | None) -> str:
    normalized = _normalize_endpoint(value)
    return normalized if normalized.endswith("/api/v1") else ""


def provider_failure_metadata(
    *,
    provider: ProviderName,
    phase: str,
    http_status: int | None = None,
    provider_code: object = None,
    request_id: object = None,
    uncertain: bool,
    potentially_billable: bool,
) -> ProviderFailureMetadata:
    return ProviderFailureMetadata(
        provider=provider,
        phase=phase,
        http_status=http_status,
        safe_error_code=_safe_error_code(http_status, provider_code),
        request_id_digest=_request_id_digest(request_id),
        uncertain=uncertain,
        potentially_billable=potentially_billable,
        occurred_at=datetime.now(UTC).isoformat(),
    )


def metadata_for_http_failure(
    *,
    provider: ProviderName,
    phase: str,
    http_status: int,
    provider_code: object = None,
    request_id: object = None,
    response_from_provider: bool = True,
) -> ProviderFailureMetadata:
    del phase
    if not response_from_provider:
        return provider_failure_metadata(
            provider=provider,
            phase="connect",
            provider_code="proxy_unavailable",
            uncertain=False,
            potentially_billable=False,
        )
    uncertain = http_status == 408 or http_status >= 500
    return provider_failure_metadata(
        provider=provider,
        phase="response",
        http_status=http_status,
        provider_code=provider_code,
        request_id=request_id,
        uncertain=uncertain,
        potentially_billable=uncertain or http_status == 400,
    )


def metadata_for_transport_failure(
    *, provider: ProviderName, phase: str, error: BaseException
) -> ProviderFailureMetadata:
    del phase
    proxy_failure = _contains_error(error, (httpx.ProxyError,))
    connect_failure = _contains_error(
        error,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.PoolTimeout,
        ),
    )
    uncertain = not (proxy_failure or connect_failure)
    code = (
        "proxy_unavailable"
        if proxy_failure
        else _classify_connect_failure(error)
        if connect_failure
        else "response_uncertain"
    )
    return provider_failure_metadata(
        provider=provider,
        phase="response" if uncertain else "connect",
        provider_code=code,
        uncertain=uncertain,
        potentially_billable=uncertain,
    )


def provider_error_from_metadata(
    metadata: ProviderFailureMetadata,
) -> ProviderError:
    code = metadata.safe_error_code
    if code == "authentication_failed":
        error: ProviderError = ProviderAuthenticationError(
            "Provider authentication failed"
        )
    elif code == "rate_or_quota_limited":
        error = ProviderQuotaError("Provider quota or rate limit reached")
    elif metadata.uncertain:
        error = ProviderTimeoutError("Provider result is uncertain")
    elif code in CONNECTION_FAILURE_CODES:
        error = ProviderModelError("Provider connection failed before submission")
    elif code == "provider_service_error":
        error = ProviderConnectionError("Provider service is unavailable")
    else:
        error = ProviderModelError("Provider request failed")
    error.safe_metadata = metadata  # type: ignore[attr-defined]
    return error


def get_provider_failure_metadata(
    error: BaseException,
) -> ProviderFailureMetadata | None:
    value = getattr(error, "safe_metadata", None)
    return value if isinstance(value, ProviderFailureMetadata) else None


def safe_error_message(metadata: ProviderFailureMetadata) -> str:
    if metadata.uncertain:
        return "Qwen request result is uncertain"
    messages = {
        "authentication_failed": "Qwen provider authentication failed",
        "permission_denied": "Qwen provider permission denied",
        "endpoint_or_model_not_found": "Qwen endpoint or model was not found",
        "rate_or_quota_limited": "Qwen quota or rate limit prevents execution",
        "provider_service_error": "Qwen provider is temporarily unavailable",
        "invalid_request": "Qwen request or model parameters are invalid",
        "dns_resolution_failed": "Qwen DNS resolution failed",
        "tcp_connection_refused": "Qwen TCP connection was refused",
        "connect_timeout": "Qwen connection timed out",
        "network_unreachable": "Qwen network is unreachable",
        "tls_handshake_failed": "Qwen TLS handshake failed",
        "tls_certificate_failed": "Qwen TLS certificate verification failed",
        "connection_reset_before_request": ("Qwen connection reset before request"),
        "connection_failed_unknown": "Qwen provider connection failed",
        "proxy_unavailable": "Qwen proxy connection failed",
        "invalid_provider_output": "Qwen returned invalid provider output",
    }
    return messages.get(metadata.safe_error_code or "", "Qwen generation failed")


def provider_public_http_status(metadata: ProviderFailureMetadata) -> int:
    """Map a classified failure to an HTTP status without hiding provider status."""
    if metadata.http_status in {400, 401, 403, 404, 408, 429}:
        return metadata.http_status
    if metadata.safe_error_code in CONNECTION_FAILURE_CODES:
        return 503
    if metadata.safe_error_code == "invalid_provider_output":
        return 502
    if metadata.uncertain:
        return 504 if metadata.http_status is None else 503
    return 502


def public_provider_failure(
    metadata: ProviderFailureMetadata,
) -> SafeProviderFailure:
    phase = metadata.phase
    if phase not in {"connect", "request", "response", "schema", "delivery"}:
        phase = (
            "schema"
            if "validation" in phase
            else "connect"
            if metadata.safe_error_code in CONNECTION_FAILURE_CODES
            else "response"
        )
    return SafeProviderFailure(
        provider=metadata.provider,
        phase=phase,  # type: ignore[arg-type]
        provider_http_status=metadata.http_status,
        safe_error_code=metadata.safe_error_code or "provider_error",
        request_id_digest=metadata.request_id_digest,
        uncertain=metadata.uncertain,
        potentially_billable=metadata.potentially_billable,
        occurred_at=metadata.occurred_at,
    )


def _provider_readiness(
    *,
    provider: ProviderName,
    credentials_configured: bool,
    workspace_configured: bool,
    region_supported: bool,
    endpoint_valid: bool,
    model_configured: bool,
) -> ProviderReadiness:
    checks = {
        "credentials": credentials_configured,
        "workspace": workspace_configured,
        "region": region_supported,
        "endpoint": endpoint_valid,
        "model": model_configured,
    }
    missing = tuple(
        f"{provider}_{name}_configuration"
        for name, ready in checks.items()
        if not ready
    )
    return ProviderReadiness(
        credentials_configured=credentials_configured,
        workspace_configured=workspace_configured,
        region_supported=region_supported,
        endpoint_valid=endpoint_valid,
        model_configured=model_configured,
        ready=not missing,
        missing_requirements=missing,
    )


def _resolve_endpoint(
    *,
    explicit: str | None,
    workspace_id: str | None,
    region: str,
    templates: dict[str, str],
) -> tuple[str, bool]:
    normalized_workspace = _text(workspace_id)
    normalized_region = _text(region)
    template = templates.get(normalized_region)
    expected = (
        template.format(workspace_id=normalized_workspace)
        if template and normalized_workspace and _safe_workspace(normalized_workspace)
        else ""
    )
    candidate = _normalize_endpoint(explicit) if explicit else expected
    return candidate, bool(expected and candidate == expected)


def _normalize_endpoint(value: str | None) -> str:
    text = _text(value).rstrip("/")
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        return ""
    host = (parsed.hostname or "").lower()
    if not host.endswith(".maas.aliyuncs.com"):
        return ""
    path = "/" + "/".join(part for part in parsed.path.split("/") if part)
    return urlunsplit(("https", host, path, "", ""))


def _safe_workspace(value: str) -> bool:
    return bool(value) and all(
        character.isascii() and (character.isalnum() or character == "-")
        for character in value
    )


def _safe_error_code(http_status: int | None, provider_code: object) -> str | None:
    by_status = {
        400: "invalid_request",
        401: "authentication_failed",
        403: "permission_denied",
        404: "endpoint_or_model_not_found",
        408: "response_uncertain",
        429: "rate_or_quota_limited",
    }
    if http_status in by_status:
        return by_status[http_status]
    if http_status is not None and http_status >= 500:
        return "provider_service_error"
    if isinstance(provider_code, str) and provider_code in {
        "dns_resolution_failed",
        "tcp_connection_refused",
        "connect_timeout",
        "network_unreachable",
        "tls_handshake_failed",
        "tls_certificate_failed",
        "proxy_unavailable",
        "connection_reset_before_request",
        "connection_failed_unknown",
        "response_uncertain",
        "delivery_uncertain",
        "invalid_provider_output",
    }:
        return provider_code
    return None


def _request_id_digest(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()[:16]


def _contains_error(
    error: BaseException, expected: tuple[type[BaseException], ...]
) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, expected):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _classify_connect_failure(error: BaseException) -> str:
    if _contains_error(error, (httpx.ConnectTimeout, httpx.PoolTimeout)):
        return "connect_timeout"
    if _contains_error(error, (ssl.SSLCertVerificationError,)):
        return "tls_certificate_failed"
    if _contains_error(error, (ssl.SSLError,)):
        return "tls_handshake_failed"
    if _contains_error(error, (socket.gaierror,)):
        return "dns_resolution_failed"

    numbers = _safe_error_numbers(error)
    if numbers.intersection({errno.ECONNREFUSED, 10061}):
        return "tcp_connection_refused"
    if numbers.intersection({errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}):
        return "network_unreachable"
    if numbers.intersection({errno.ECONNRESET, 10054}):
        return "connection_reset_before_request"
    if numbers.intersection({errno.ETIMEDOUT, 10060}):
        return "connect_timeout"
    return "connection_failed_unknown"


def _safe_error_numbers(error: BaseException) -> set[int]:
    numbers: set[int] = set()
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        for name in ("errno", "winerror"):
            value = getattr(current, name, None)
            if isinstance(value, int):
                numbers.add(value)
        current = current.__cause__ or current.__context__
    return numbers


def _secret(value: object) -> str:
    if value is None or not hasattr(value, "get_secret_value"):
        return ""
    secret = value.get_secret_value()  # type: ignore[union-attr]
    return secret.strip() if isinstance(secret, str) else ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _secret_file(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    path = Path(value.strip())
    if not path.is_absolute():
        return ""
    try:
        if not path.is_file() or path.stat().st_size > 16_384:
            return ""
        return path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""
