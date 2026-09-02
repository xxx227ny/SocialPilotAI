import httpx

from app.services.provider_credential_verifier import (
    DASHSCOPE_MODEL_LIST_URL,
    DashScopeCredentialVerifier,
)

API_KEY = "sk-verifier-test-key-123456"


def verifier_for(status_code: int) -> DashScopeCredentialVerifier:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(DASHSCOPE_MODEL_LIST_URL)
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert request.url.params["capabilities"] == "TG"
        assert request.url.params["page_size"] == "1"
        return httpx.Response(status_code, json={"safe": True})

    return DashScopeCredentialVerifier(transport=httpx.MockTransport(handle))


def test_non_billable_model_list_verification_accepts_valid_key() -> None:
    result = verifier_for(200).verify(API_KEY)

    assert result.status == "VERIFIED"
    assert result.verified is True
    assert API_KEY not in result.message


def test_verification_classifies_safe_provider_statuses_without_echoing_key() -> None:
    expected = {
        401: "INVALID",
        403: "FORBIDDEN",
        429: "RATE_LIMITED",
        503: "UNAVAILABLE",
    }

    for status_code, status in expected.items():
        result = verifier_for(status_code).verify(API_KEY)
        assert result.status == status
        assert result.verified is False
        assert API_KEY not in result.message


def test_verification_connection_failure_is_safe_and_not_retried() -> None:
    calls = 0

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    result = DashScopeCredentialVerifier(transport=httpx.MockTransport(fail)).verify(
        API_KEY
    )

    assert calls == 1
    assert result.status == "UNAVAILABLE"
    assert result.verified is False
    assert API_KEY not in result.message
