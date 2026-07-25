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
