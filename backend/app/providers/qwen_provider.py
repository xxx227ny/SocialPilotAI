import openai
from openai import OpenAI

from app.core.config import Settings, settings
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderModelError,
    TextGenerationProvider,
)

QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class QwenProvider(TextGenerationProvider):
    """Alibaba Cloud Model Studio adapter using its OpenAI-compatible API."""

    def __init__(self, app_settings: Settings = settings) -> None:
        if app_settings.dashscope_api_key is None:
            raise ProviderAuthenticationError("Qwen API credentials are not configured")

        self.model = app_settings.qwen_model
        self.client = OpenAI(
            api_key=app_settings.dashscope_api_key.get_secret_value(),
            base_url=QWEN_BASE_URL,
            timeout=app_settings.qwen_timeout,
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
        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError(
                "Qwen authentication failed"
            ) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderConnectionError("Qwen service is unavailable") from exc
        except openai.APIStatusError as exc:
            raise ProviderModelError(
                f"Qwen request failed with status {exc.status_code}"
            ) from exc
        except openai.OpenAIError as exc:
            raise ProviderModelError("Qwen request failed") from exc

        if not completion.choices:
            raise ProviderModelError("Qwen returned no choices")
        content = completion.choices[0].message.content
        if not content or not content.strip():
            raise ProviderModelError("Qwen returned empty text")
        return content.strip()
