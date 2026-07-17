from typing import Annotated

from fastapi import Depends

from app.core.exceptions import AppError
from app.providers import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    QwenProvider,
    WanxProvider,
)
from app.providers.base import TextGenerationProvider
from app.providers.visual_base import VisualGenerationProvider


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


def get_visual_generation_provider() -> VisualGenerationProvider:
    try:
        return WanxProvider()
    except (ProviderAuthenticationError, ProviderConfigurationError) as exc:
        raise AppError(
            "Wanx provider is not configured", status_code=503
        ) from exc


VisualProviderDep = Annotated[
    VisualGenerationProvider, Depends(get_visual_generation_provider)
]
