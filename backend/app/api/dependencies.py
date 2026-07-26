from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
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


def require_strategy_execution_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_strategy_execution:
        raise AppError(
            "Strategy execution is disabled by the server",
            status_code=503,
        )


StrategyExecutionGateDep = Annotated[
    None, Depends(require_strategy_execution_enabled)
]


def require_copy_execution_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_copy_execution:
        raise AppError(
            "Copy execution is disabled by the server",
            status_code=503,
        )


CopyExecutionGateDep = Annotated[
    None, Depends(require_copy_execution_enabled)
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
