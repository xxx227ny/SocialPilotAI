from typing import Annotated

from fastapi import Depends

from app.core.exceptions import AppError
from app.providers import ProviderAuthenticationError, QwenProvider
from app.providers.base import TextGenerationProvider


def get_text_generation_provider() -> TextGenerationProvider:
    try:
        return QwenProvider()
    except ProviderAuthenticationError as exc:
        raise AppError(
            "Qwen API credentials are not configured", status_code=503
        ) from exc


TextProviderDep = Annotated[
    TextGenerationProvider, Depends(get_text_generation_provider)
]
