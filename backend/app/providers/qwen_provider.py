from typing import Any

import httpx
import openai
from openai import DefaultHttpxClient, OpenAI

from app.core.config import Settings, settings
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderModelError,
    TextGenerationProvider,
)
from app.providers.live_configuration import (
    audit_live_provider_configuration,
    controlled_qwen_endpoint,
    effective_qwen_api_key,
    effective_qwen_endpoint,
    metadata_for_http_failure,
    metadata_for_transport_failure,
    provider_error_from_metadata,
    provider_failure_metadata,
)

QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenProvider(TextGenerationProvider):
    """Alibaba Model Studio adapter using the OpenAI-compatible API."""

    def __init__(self, app_settings: Settings = settings) -> None:
        api_key = effective_qwen_api_key(app_settings)
        if not api_key:
            raise ProviderAuthenticationError(
                "Qwen API credentials are not configured"
            )

        configuration = audit_live_provider_configuration(app_settings)
        if (
            app_settings.require_live_provider_coherence
            and not configuration.qwen.ready
        ):
            raise ProviderConfigurationError(
                "Qwen live provider configuration is inconsistent"
            )
        if app_settings.qwen_endpoint:
            explicit_endpoint = controlled_qwen_endpoint(
                app_settings.qwen_endpoint
            )
            if not explicit_endpoint or not configuration.qwen.endpoint_valid:
                raise ProviderConfigurationError("Qwen endpoint is invalid")

        self.model = app_settings.qwen_model
        timeout = httpx.Timeout(
            timeout=app_settings.qwen_timeout,
            connect=app_settings.qwen_connect_timeout,
            read=app_settings.qwen_read_timeout,
            write=app_settings.qwen_write_timeout,
            pool=app_settings.qwen_pool_timeout,
        )
        self.client = OpenAI(
            api_key=api_key,
            base_url=effective_qwen_endpoint(app_settings) or QWEN_BASE_URL,
            timeout=timeout,
            http_client=DefaultHttpxClient(timeout=timeout, trust_env=True),
            max_retries=0,
        )

    def generate(self, prompt: str) -> str:
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a cross-border ecommerce marketing analyst. "
                            "Return only one valid JSON object matching the user's "
                            "requested structure."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
        except openai.APIStatusError as exc:
            code, request_id = self._safe_response_identifiers(exc)
            metadata = metadata_for_http_failure(
                provider="qwen",
                phase="generation",
                http_status=exc.status_code,
                provider_code=code,
                request_id=request_id,
                response_from_provider=not self._is_proxy_response(exc),
            )
            raise provider_error_from_metadata(metadata) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            metadata = metadata_for_transport_failure(
                provider="qwen", phase="generation", error=exc
            )
            raise provider_error_from_metadata(metadata) from exc
        except openai.OpenAIError as exc:
            metadata = provider_failure_metadata(
                provider="qwen",
                phase="connect",
                provider_code="connection_failed_unknown",
                uncertain=False,
                potentially_billable=False,
            )
            raise provider_error_from_metadata(metadata) from exc

        if not completion.choices:
            raise self._invalid_output_error()
        content = completion.choices[0].message.content
        if not content or not content.strip():
            raise self._invalid_output_error()
        return content.strip()

    @staticmethod
    def _invalid_output_error() -> ProviderModelError:
        metadata = provider_failure_metadata(
            provider="qwen",
            phase="schema",
            provider_code="invalid_provider_output",
            uncertain=False,
            potentially_billable=True,
        )
        error = ProviderModelError("Qwen returned invalid output")
        error.safe_metadata = metadata  # type: ignore[attr-defined]
        return error

    @staticmethod
    def _is_proxy_response(error: openai.APIStatusError) -> bool:
        headers = error.response.headers
        server = headers.get("server", "").strip().lower()
        return bool(
            headers.get("proxy-authenticate")
            or headers.get("x-squid-error")
            or server.startswith("squid")
        )

    @staticmethod
    def _safe_response_identifiers(
        error: openai.APIStatusError,
    ) -> tuple[object, object]:
        body: Any = getattr(error, "body", None)
        code = body.get("code") if isinstance(body, dict) else None
        request_id = None
        if isinstance(body, dict):
            request_id = body.get("request_id") or body.get("requestId")
        if request_id is None:
            request_id = error.response.headers.get("x-request-id")
        return code, request_id
