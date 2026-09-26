from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import openai
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    ProviderQuotaError,
)
from app.providers.qwen_provider import QwenProvider


def make_provider() -> QwenProvider:
    provider = QwenProvider(
        Settings(
            dashscope_api_key=SecretStr("unit-test-placeholder"),
            qwen_model="qwen-plus",
            qwen_timeout=12,
        )
    )
    provider.client = Mock()
    return provider


def test_qwen_provider_uses_structured_chat_completion() -> None:
    provider = make_provider()
    provider.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
    )

    result = provider.generate("Return a JSON object")

    assert result == '{"ok": true}'
    provider.client.chat.completions.create.assert_called_once()
    call_arguments = provider.client.chat.completions.create.call_args.kwargs
    assert call_arguments["model"] == "qwen-plus"
    assert call_arguments["response_format"] == {"type": "json_object"}
    assert call_arguments["extra_body"] == {"enable_thinking": False}


def test_qwen_provider_maps_authentication_error() -> None:
    provider = make_provider()
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(401, request=request)
    provider.client.chat.completions.create.side_effect = openai.AuthenticationError(
        "authentication failed", response=response, body=None
    )

    with pytest.raises(ProviderAuthenticationError):
        provider.generate("Return JSON")


def test_qwen_provider_maps_connection_error() -> None:
    provider = make_provider()
    request = httpx.Request("POST", "https://example.invalid")
    provider.client.chat.completions.create.side_effect = openai.APIConnectionError(
        request=request
    )

    with pytest.raises(ProviderConnectionError):
        provider.generate("Return JSON")


def test_qwen_provider_maps_rate_limit_error() -> None:
    provider = make_provider()
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(429, request=request)
    provider.client.chat.completions.create.side_effect = openai.RateLimitError(
        "rate limited", response=response, body=None
    )

    with pytest.raises(ProviderQuotaError):
        provider.generate("Return JSON")


def test_qwen_provider_rejects_empty_model_text() -> None:
    provider = make_provider()
    provider.client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
    )

    with pytest.raises(ProviderModelError):
        provider.generate("Return JSON")


def test_qwen_provider_safely_falls_back_after_pre_submission_connect_timeout() -> None:
    endpoint = (
        "https://workspace-12.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    provider = QwenProvider(
        Settings(
            dashscope_api_key=SecretStr("unit-test-placeholder"),
            qwen_workspace_id="workspace-12",
            qwen_endpoint=endpoint,
            qwen_model="qwen-plus",
        )
    )
    provider.client = Mock()
    request = httpx.Request("POST", f"{endpoint}/chat/completions")
    connect_timeout = httpx.ConnectTimeout(
        "dedicated endpoint timed out", request=request
    )
    try:
        raise openai.APITimeoutError(request=request) from connect_timeout
    except openai.APITimeoutError as timeout_error:
        provider.client.chat.completions.create.side_effect = [
            timeout_error,
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"ok": true}')
                    )
                ]
            ),
        ]

    assert provider.generate("Return JSON") == '{"ok": true}'
    assert provider.client.chat.completions.create.call_count == 2
    assert str(provider.client.base_url).rstrip("/") == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_qwen_provider_fallback_changes_the_real_openai_request_host() -> None:
    endpoint = (
        "https://workspace-12.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "workspace-12.cn-beijing.maas.aliyuncs.com":
            raise httpx.ConnectTimeout("dedicated endpoint timed out", request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen-plus",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"ok": true}',
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = QwenProvider(
        Settings(
            dashscope_api_key=SecretStr("unit-test-placeholder"),
            qwen_workspace_id="workspace-12",
            qwen_endpoint=endpoint,
            qwen_model="qwen-plus",
        )
    )
    provider.client.close()
    provider.client = openai.OpenAI(
        api_key="unit-test-placeholder",
        base_url=endpoint,
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            trust_env=True,
        ),
        max_retries=0,
    )

    assert provider.generate("Return JSON") == '{"ok": true}'
    assert [request.url.host for request in requests] == [
        "workspace-12.cn-beijing.maas.aliyuncs.com",
        "dashscope.aliyuncs.com",
    ]


def test_qwen_provider_never_falls_back_after_response_timeout() -> None:
    endpoint = (
        "https://workspace-12.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    provider = QwenProvider(
        Settings(
            dashscope_api_key=SecretStr("unit-test-placeholder"),
            qwen_workspace_id="workspace-12",
            qwen_endpoint=endpoint,
            qwen_model="qwen-plus",
        )
    )
    provider.client = Mock()
    request = httpx.Request("POST", f"{endpoint}/chat/completions")
    read_timeout = httpx.ReadTimeout("response timed out", request=request)
    try:
        raise openai.APITimeoutError(request=request) from read_timeout
    except openai.APITimeoutError as timeout_error:
        provider.client.chat.completions.create.side_effect = timeout_error

    with pytest.raises(ProviderConnectionError):
        provider.generate("Return JSON")

    provider.client.chat.completions.create.assert_called_once()
