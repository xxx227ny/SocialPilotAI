import asyncio
import errno
import hashlib
import socket
import ssl
from pathlib import Path
from unittest.mock import Mock

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    SafeObservableTextProvider,
    get_text_generation_provider,
    require_growth_execution_enabled,
    require_v2_copy_execution_enabled,
    require_v2_video_project_execution_enabled,
    require_video_render_execution_enabled,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.main import app
from app.models import VideoRenderArtifact, VideoRenderTask
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderError,
)
from app.providers.live_configuration import (
    QWEN_REGION_ENDPOINT_TEMPLATES,
    WANX_REGION_ENDPOINT_TEMPLATES,
    audit_live_provider_configuration,
    effective_qwen_api_key,
    get_provider_failure_metadata,
    metadata_for_transport_failure,
    qwen_provider_configured,
    wanx_provider_configured,
)
from app.providers.qwen_provider import QwenProvider
from app.providers.visual_base import VisualGenerationRequest
from app.providers.wanx_provider import WanxProvider
from tests.test_growth_recommendation_constraints import (
    create_ready_context,
    model_counts,
)
from tests.test_video_render_service import create_video_project

QWEN_KEY = "safe-qwen-test-key"
WANX_KEY = "safe-wanx-test-key"
QWEN_WORKSPACE = "safe-qwen-workspace"
WANX_WORKSPACE = "safe-wanx-workspace"


def strict_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "qwen_api_key": QWEN_KEY,
        "dashscope_api_key": None,
        "qwen_workspace_id": QWEN_WORKSPACE,
        "qwen_region": "cn-beijing",
        "qwen_endpoint": None,
        "wanx_api_key": WANX_KEY,
        "wanx_workspace_id": WANX_WORKSPACE,
        "wanx_region": "cn-beijing",
        "wanx_endpoint": None,
        "qwen_model": "qwen-plus",
        "wanx_model": "wan2.7-t2v",
        "require_live_provider_coherence": True,
        "enable_growth_execution": True,
        "enable_copy_execution": True,
        "enable_v2_copy_execution": True,
        "enable_v2_video_project_execution": True,
        "enable_video_render_execution": True,
    }
    values.update(overrides)
    return Settings(**values)


def qwen_status_error(
    status: int,
    *,
    include_request_id: bool = True,
    proxy_response: bool = False,
) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://safe.invalid")
    headers: dict[str, str] = {}
    if include_request_id:
        headers["x-request-id"] = "raw-request-id"
    if proxy_response:
        headers["proxy-authenticate"] = "Fake proxy challenge"
    response = httpx.Response(
        status,
        request=request,
        headers=headers,
        json={
            "code": "ProviderCodeThatMustNotEscape",
            "message": f"secret message {QWEN_KEY}",
        },
    )
    error_type: type[openai.APIStatusError]
    if status == 401:
        error_type = openai.AuthenticationError
    elif status == 403:
        error_type = openai.PermissionDeniedError
    elif status == 429:
        error_type = openai.RateLimitError
    else:
        error_type = openai.APIStatusError
    return error_type(
        "unsafe provider message", response=response, body=response.json()
    )


def qwen_transport_error(error: httpx.RequestError) -> openai.APITimeoutError:
    request = httpx.Request("POST", "https://safe.invalid")
    try:
        raise error
    except httpx.RequestError as cause:
        try:
            raise openai.APITimeoutError(request=request) from cause
        except openai.APITimeoutError as wrapped:
            return wrapped


def wanx_request() -> VisualGenerationRequest:
    return VisualGenerationRequest(
        prompt="Fake request only",
        duration_seconds=5,
        aspect_ratio="16:9",
        resolution="720P",
    )


def test_qwen_and_wanx_are_independently_ready_with_different_values() -> None:
    settings = strict_settings()

    audit = audit_live_provider_configuration(settings)

    assert audit.qwen.ready is True
    assert audit.wanx.ready is True
    assert audit.qwen.missing_requirements == ()
    assert audit.wanx.missing_requirements == ()
    assert audit.qwen_endpoint == QWEN_REGION_ENDPOINT_TEMPLATES[
        "cn-beijing"
    ].format(workspace_id=QWEN_WORKSPACE)
    assert audit.wanx_endpoint == WANX_REGION_ENDPOINT_TEMPLATES[
        "cn-beijing"
    ].format(workspace_id=WANX_WORKSPACE)


def test_provider_constructors_read_only_their_own_credentials() -> None:
    settings = strict_settings()

    qwen = QwenProvider(settings)
    wanx = WanxProvider(settings)

    assert qwen.client.api_key == QWEN_KEY
    assert wanx.api_key == WANX_KEY
    assert qwen.client.api_key != wanx.api_key


def test_qwen_never_falls_back_to_wanx_key() -> None:
    settings = strict_settings(qwen_api_key=None, wanx_api_key=WANX_KEY)

    assert effective_qwen_api_key(settings) == ""
    assert qwen_provider_configured(settings) is False
    assert wanx_provider_configured(settings) is True
    with pytest.raises(ProviderAuthenticationError):
        QwenProvider(settings)


def test_wanx_never_falls_back_to_qwen_or_dashscope_key() -> None:
    settings = strict_settings(wanx_api_key=None)

    assert qwen_provider_configured(settings) is True
    assert wanx_provider_configured(settings) is False
    with pytest.raises(ProviderAuthenticationError):
        WanxProvider(settings)


def test_dashscope_is_a_one_way_deprecated_qwen_alias() -> None:
    settings = strict_settings(
        qwen_api_key=None,
        dashscope_api_key="safe-legacy-qwen-key",
        wanx_api_key=None,
    )

    assert effective_qwen_api_key(settings) == "safe-legacy-qwen-key"
    assert qwen_provider_configured(settings) is True
    assert wanx_provider_configured(settings) is False


@pytest.mark.parametrize(
    ("overrides", "qwen_ready", "wanx_ready", "requirement"),
    [
        (
            {"qwen_workspace_id": None},
            False,
            True,
            "qwen_workspace_configuration",
        ),
        (
            {"wanx_workspace_id": None},
            True,
            False,
            "wanx_workspace_configuration",
        ),
        (
            {"qwen_region": "unsupported"},
            False,
            True,
            "qwen_region_configuration",
        ),
        (
            {"wanx_region": "unsupported"},
            True,
            False,
            "wanx_region_configuration",
        ),
        (
            {"qwen_model": "unsupported"},
            False,
            True,
            "qwen_model_configuration",
        ),
        (
            {"wanx_model": "unsupported"},
            True,
            False,
            "wanx_model_configuration",
        ),
    ],
)
def test_invalid_provider_configuration_only_blocks_that_provider(
    overrides: dict[str, object],
    qwen_ready: bool,
    wanx_ready: bool,
    requirement: str,
) -> None:
    audit = audit_live_provider_configuration(strict_settings(**overrides))

    assert audit.qwen.ready is qwen_ready
    assert audit.wanx.ready is wanx_ready
    assert requirement in audit.missing_requirements


@pytest.mark.parametrize(
    ("field", "value", "provider"),
    [
        (
            "qwen_endpoint",
            "http://safe-qwen-workspace.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1",
            "qwen",
        ),
        ("qwen_endpoint", "https://localhost/compatible-mode/v1", "qwen"),
        (
            "qwen_endpoint",
            "https://example.invalid/compatible-mode/v1",
            "qwen",
        ),
        (
            "qwen_endpoint",
            "https://safe-qwen-workspace.cn-beijing.maas.aliyuncs.com/"
            "compatible-mode/v1/compatible-mode/v1",
            "qwen",
        ),
        (
            "wanx_endpoint",
            "https://safe-wanx-workspace.cn-beijing.maas.aliyuncs.com/"
            "api/v1/api/v1",
            "wanx",
        ),
        ("wanx_endpoint", "file:///tmp/provider", "wanx"),
    ],
)
def test_explicit_endpoints_fail_closed_when_not_exactly_controlled(
    field: str, value: str, provider: str
) -> None:
    audit = audit_live_provider_configuration(
        strict_settings(**{field: value})
    )

    readiness = audit.qwen if provider == "qwen" else audit.wanx
    assert readiness.endpoint_valid is False
    assert readiness.ready is False


def test_exact_endpoints_normalize_one_trailing_slash() -> None:
    settings = strict_settings(
        qwen_endpoint=QWEN_REGION_ENDPOINT_TEMPLATES["cn-beijing"].format(
            workspace_id=QWEN_WORKSPACE
        )
        + "/",
        wanx_endpoint=WANX_REGION_ENDPOINT_TEMPLATES["cn-beijing"].format(
            workspace_id=WANX_WORKSPACE
        )
        + "/",
    )

    audit = audit_live_provider_configuration(settings)

    assert audit.qwen.ready is True
    assert audit.wanx.ready is True


@pytest.mark.parametrize(
    ("status", "code", "uncertain", "billable"),
    [
        (400, "invalid_request", False, True),
        (401, "authentication_failed", False, False),
        (403, "permission_denied", False, False),
        (404, "endpoint_or_model_not_found", False, False),
        (408, "response_uncertain", True, True),
        (429, "rate_or_quota_limited", False, False),
        (500, "provider_service_error", True, True),
    ],
)
def test_qwen_http_failures_have_safe_classified_metadata(
    status: int, code: str, uncertain: bool, billable: bool
) -> None:
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_status_error(status)

    with pytest.raises(ProviderError) as captured:
        provider.generate("Fake JSON request")

    metadata = get_provider_failure_metadata(captured.value)
    assert metadata is not None
    assert metadata.provider == "qwen"
    assert metadata.http_status == status
    assert metadata.safe_error_code == code
    assert metadata.uncertain is uncertain
    assert metadata.potentially_billable is billable
    assert metadata.request_id_digest == hashlib.sha256(
        b"raw-request-id"
    ).hexdigest()[:16]
    exposed = f"{captured.value!s} {metadata!r}"
    assert "raw-request-id" not in exposed
    assert QWEN_KEY not in exposed
    assert "unsafe provider message" not in exposed
    provider.client.chat.completions.create.assert_called_once()


@pytest.mark.parametrize(
    ("transport_error", "code", "phase", "uncertain", "billable"),
    [
        (httpx.ConnectTimeout("connect"), "connect_timeout", "connect", False, False),
        (httpx.PoolTimeout("pool"), "connect_timeout", "connect", False, False),
        (httpx.ProxyError("proxy"), "proxy_unavailable", "connect", False, False),
        (httpx.ReadTimeout("read"), "response_uncertain", "response", True, True),
        (httpx.WriteTimeout("write"), "response_uncertain", "response", True, True),
    ],
)
def test_qwen_transport_failures_are_phase_aware(
    transport_error: httpx.RequestError,
    code: str,
    phase: str,
    uncertain: bool,
    billable: bool,
) -> None:
    request = httpx.Request("POST", "https://safe.invalid")
    transport_error.request = request
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_transport_error(
        transport_error
    )

    with pytest.raises(ProviderError) as captured:
        provider.generate("Fake JSON request")

    metadata = get_provider_failure_metadata(captured.value)
    assert metadata is not None
    assert metadata.http_status is None
    assert metadata.safe_error_code == code
    assert metadata.phase == phase
    assert metadata.uncertain is uncertain
    assert metadata.potentially_billable is billable
    provider.client.chat.completions.create.assert_called_once()


def test_local_proxy_503_is_not_misreported_as_provider_503() -> None:
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_status_error(
        503, proxy_response=True
    )

    with pytest.raises(ProviderError) as captured:
        provider.generate("Fake JSON request")

    metadata = get_provider_failure_metadata(captured.value)
    assert metadata is not None
    assert metadata.phase == "connect"
    assert metadata.http_status is None
    assert metadata.safe_error_code == "proxy_unavailable"
    assert metadata.uncertain is False
    assert metadata.potentially_billable is False


def chained_connect_error(inner: BaseException) -> httpx.ConnectError:
    try:
        raise inner
    except BaseException as cause:
        try:
            raise httpx.ConnectError("safe connect failure") from cause
        except httpx.ConnectError as error:
            return error


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        (
            socket.gaierror(socket.EAI_NONAME, "private DNS detail"),
            "dns_resolution_failed",
        ),
        (
            ConnectionRefusedError(errno.ECONNREFUSED, "private endpoint"),
            "tcp_connection_refused",
        ),
        (
            OSError(errno.ENETUNREACH, "private network"),
            "network_unreachable",
        ),
        (
            ssl.SSLCertVerificationError(1, "private certificate"),
            "tls_certificate_failed",
        ),
        (ssl.SSLError(1, "private handshake"), "tls_handshake_failed"),
        (
            ConnectionResetError(errno.ECONNRESET, "private endpoint"),
            "connection_reset_before_request",
        ),
        (OSError(9999, "private unknown"), "connection_failed_unknown"),
    ],
)
def test_connect_failures_have_specific_safe_categories(
    inner: BaseException, expected: str
) -> None:
    metadata = metadata_for_transport_failure(
        provider="qwen",
        phase="generation",
        error=chained_connect_error(inner),
    )
    assert metadata.safe_error_code == expected
    assert metadata.phase == "connect"
    assert metadata.http_status is None
    assert metadata.request_id_digest is None
    assert metadata.uncertain is False
    assert metadata.potentially_billable is False
    exposed = repr(metadata)
    assert "private" not in exposed


def test_qwen_openai_client_builds_one_exact_path_without_retry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            401,
            request=request,
            json={"code": "FakeAuthenticationFailure"},
        )

    settings = strict_settings()
    endpoint = audit_live_provider_configuration(settings).qwen_endpoint
    provider = QwenProvider(settings)
    provider.client = openai.OpenAI(
        api_key=QWEN_KEY,
        base_url=endpoint,
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            trust_env=True,
        ),
        max_retries=0,
    )

    with pytest.raises(ProviderError):
        provider.generate("Fake JSON request")

    assert len(requests) == 1
    assert requests[0].url.path == "/compatible-mode/v1/chat/completions"


def test_qwen_http_client_uses_explicit_proxy_and_timeout_contract() -> None:
    settings = strict_settings()
    provider = QwenProvider(settings)
    http_client = provider.client._client
    try:
        assert http_client._trust_env is True
        assert provider.client.max_retries == 0
        assert http_client.timeout.connect == settings.qwen_connect_timeout
        assert http_client.timeout.read == settings.qwen_read_timeout
        assert http_client.timeout.write == settings.qwen_write_timeout
        assert http_client.timeout.pool == settings.qwen_pool_timeout
    finally:
        provider.client.close()


@pytest.mark.parametrize(
    (
        "provider_status",
        "public_status",
        "code",
        "uncertain",
        "billable",
    ),
    [
        (400, 400, "invalid_request", False, True),
        (401, 401, "authentication_failed", False, False),
        (403, 403, "permission_denied", False, False),
        (404, 404, "endpoint_or_model_not_found", False, False),
        (408, 408, "response_uncertain", True, True),
        (429, 429, "rate_or_quota_limited", False, False),
        (500, 503, "provider_service_error", True, True),
        (503, 503, "provider_service_error", True, True),
    ],
)
def test_growth_route_preserves_provider_failure_contract(
    provider_status: int,
    public_status: int,
    code: str,
    uncertain: bool,
    billable: bool,
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_status_error(
        provider_status
    )
    before = model_counts(db_session)
    app.dependency_overrides[get_settings] = lambda: strict_settings()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == public_status, response.json()
    error = response.json()["error"]
    assert set(error) == {
        "provider",
        "phase",
        "provider_http_status",
        "safe_error_code",
        "request_id_digest",
        "uncertain",
        "potentially_billable",
        "occurred_at",
    }
    assert error["provider"] == "qwen"
    assert error["phase"] == "response"
    assert error["provider_http_status"] == provider_status
    assert error["safe_error_code"] == code
    assert error["request_id_digest"] == hashlib.sha256(
        b"raw-request-id"
    ).hexdigest()[:16]
    assert error["uncertain"] is uncertain
    assert error["potentially_billable"] is billable
    assert "raw-request-id" not in response.text
    assert "unsafe provider message" not in response.text
    assert QWEN_KEY not in response.text
    assert model_counts(db_session) == before


def test_growth_route_without_request_id_returns_null_digest(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_status_error(
        503, include_request_id=False
    )
    app.dependency_overrides[get_settings] = lambda: strict_settings()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 503
    assert response.json()["error"]["request_id_digest"] is None


def test_production_provider_wrapper_keeps_safe_metadata_through_route(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = qwen_status_error(503)
    wrapped = SafeObservableTextProvider(provider)
    app.dependency_overrides[get_settings] = lambda: strict_settings()
    app.dependency_overrides[get_text_generation_provider] = lambda: wrapped
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    error = response.json()["error"]
    assert response.status_code == 503
    assert error["provider_http_status"] == 503
    assert error["safe_error_code"] == "provider_service_error"
    assert error["uncertain"] is True
    assert error["potentially_billable"] is True


@pytest.mark.parametrize(
    ("failure", "public_status", "code", "phase", "uncertain", "billable"),
    [
        (
            qwen_transport_error(httpx.ConnectTimeout("connect")),
            503,
            "connect_timeout",
            "connect",
            False,
            False,
        ),
        (
            qwen_transport_error(httpx.ReadTimeout("read")),
            504,
            "response_uncertain",
            "response",
            True,
            True,
        ),
        (
            qwen_status_error(503, proxy_response=True),
            503,
            "proxy_unavailable",
            "connect",
            False,
            False,
        ),
    ],
)
def test_growth_route_preserves_transport_origin(
    failure: Exception,
    public_status: int,
    code: str,
    phase: str,
    uncertain: bool,
    billable: bool,
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider = QwenProvider(strict_settings())
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = failure
    app.dependency_overrides[get_settings] = lambda: strict_settings()
    app.dependency_overrides[get_text_generation_provider] = lambda: provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    error = response.json()["error"]
    assert response.status_code == public_status
    assert error["provider_http_status"] is None
    assert error["safe_error_code"] == code
    assert error["phase"] == phase
    assert error["uncertain"] is uncertain
    assert error["potentially_billable"] is billable


def test_backend_503_has_no_provider_failure_fields(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
) -> None:
    identity = create_ready_context(client, db_session, product_payload)
    provider_resolutions = 0

    def forbidden_provider() -> QwenProvider:
        nonlocal provider_resolutions
        provider_resolutions += 1
        raise AssertionError("provider must not resolve behind the gate")

    app.dependency_overrides[get_settings] = lambda: strict_settings(
        enable_growth_execution=False
    )
    app.dependency_overrides[get_text_generation_provider] = forbidden_provider
    try:
        response = client.post(
            f"/api/v1/products/{identity['product_id']}/growth-analysis",
            json={"expected_context_digest": identity["digest"]},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_text_generation_provider, None)

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "message": "Growth analysis execution is disabled by the server"
        }
    }
    assert provider_resolutions == 0


@pytest.mark.parametrize(
    ("status", "code", "uncertain"),
    [
        (400, "invalid_request", False),
        (401, "authentication_failed", False),
        (403, "permission_denied", False),
        (404, "endpoint_or_model_not_found", False),
        (408, "response_uncertain", True),
        (429, "rate_or_quota_limited", False),
        (503, "provider_service_error", True),
    ],
)
def test_wanx_http_failures_use_the_same_safe_contract(
    status: int, code: str, uncertain: bool
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "code": "ProviderCodeThatMustNotEscape",
                "request_id": "raw-wanx-request-id",
                "message": f"private {WANX_KEY}",
            },
        )

    provider = WanxProvider(
        strict_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(ProviderError) as captured:
        asyncio.run(provider.submit(wanx_request()))

    metadata = get_provider_failure_metadata(captured.value)
    assert metadata is not None
    assert metadata.provider == "wanx"
    assert metadata.http_status == status
    assert metadata.safe_error_code == code
    assert metadata.uncertain is uncertain
    exposed = f"{captured.value!s} {metadata!r}"
    assert "raw-wanx-request-id" not in exposed
    assert WANX_KEY not in exposed
    assert "private" not in exposed


def test_qwen_preflight_blocks_missing_qwen_without_provider_resolution(
    client: TestClient,
    db_session: Session,
    product_payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = create_ready_context(client, db_session, product_payload)
    provider_constructor = Mock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr("app.api.dependencies.QwenProvider", provider_constructor)
    app.dependency_overrides[get_settings] = lambda: strict_settings(
        qwen_api_key=None,
        dashscope_api_key=None,
    )

    response = client.get(
        f"/api/v1/products/{source['product_id']}/growth-analysis/preflight"
    )

    assert response.status_code == 200
    assert response.json()["provider_configured"] is False
    assert response.json()["ready_for_execution"] is False
    assert "qwen_credentials_configuration" in response.json()[
        "missing_requirements"
    ]
    provider_constructor.assert_not_called()


def test_render_preflight_blocks_missing_wanx_without_writes_or_resolution(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = create_video_project(db_session)
    provider_constructor = Mock(side_effect=AssertionError("must not resolve"))
    monkeypatch.setattr("app.api.dependencies.WanxProvider", provider_constructor)
    app.dependency_overrides[get_settings] = lambda: strict_settings(
        wanx_api_key=None,
        video_artifact_storage_root=str(tmp_path),
    )
    before = (
        int(db_session.scalar(select(func.count()).select_from(VideoRenderTask)) or 0),
        int(
            db_session.scalar(
                select(func.count()).select_from(VideoRenderArtifact)
            )
            or 0
        ),
    )

    response = client.get(
        f"/api/v1/video-projects/{project.id}/render-preflight"
    )

    assert response.status_code == 200
    assert response.json()["provider_configured"] is False
    assert response.json()["ready_for_execution"] is False
    assert "wanx_credentials_configuration" in response.json()[
        "missing_requirements"
    ]
    provider_constructor.assert_not_called()
    after = (
        int(db_session.scalar(select(func.count()).select_from(VideoRenderTask)) or 0),
        int(
            db_session.scalar(
                select(func.count()).select_from(VideoRenderArtifact)
            )
            or 0
        ),
    )
    assert after == before


@pytest.mark.parametrize(
    "gate",
    [
        require_growth_execution_enabled,
        require_v2_copy_execution_enabled,
        require_v2_video_project_execution_enabled,
    ],
)
def test_qwen_execution_gates_ignore_wanx_readiness(gate: object) -> None:
    gate(strict_settings(wanx_api_key=None))  # type: ignore[operator]


def test_render_execution_gate_ignores_qwen_readiness() -> None:
    require_video_render_execution_enabled(
        strict_settings(qwen_api_key=None, dashscope_api_key=None)
    )


def test_each_gate_fails_closed_for_its_own_provider() -> None:
    with pytest.raises(AppError):
        require_growth_execution_enabled(
            strict_settings(qwen_api_key=None, dashscope_api_key=None)
        )
    with pytest.raises(AppError):
        require_video_render_execution_enabled(strict_settings(wanx_api_key=None))


@pytest.mark.parametrize(
    ("field", "value", "requirement"),
    [
        ("duration_seconds", 1, "wanx_scene_duration"),
        ("duration_seconds", 16, "wanx_scene_duration"),
        ("aspect_ratio", "2:1", "wanx_aspect_ratio"),
    ],
)
def test_render_preflight_still_blocks_unsupported_wanx_constraints(
    client: TestClient,
    db_session: Session,
    field: str,
    value: object,
    requirement: str,
) -> None:
    project = create_video_project(db_session)
    if field == "duration_seconds":
        scenes = list(project.scenes)
        scenes[0] = {**scenes[0], "duration_seconds": value}
        project.scenes = scenes
        project.duration_seconds = int(value) + int(
            scenes[1]["duration_seconds"]
        )
    else:
        setattr(project, field, value)
    db_session.commit()

    response = client.get(
        f"/api/v1/video-projects/{project.id}/render-preflight"
    )

    assert response.status_code == 200
    assert response.json()["input_ready"] is False
    assert response.json()["ready_for_execution"] is False
    assert requirement in response.json()["missing_requirements"]
