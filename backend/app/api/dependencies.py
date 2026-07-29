from pathlib import Path
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
from app.services.video_artifact_storage import (
    HttpProviderOutputFetcher,
    LocalVideoArtifactStorage,
    ProviderOutputFetcher,
    VideoArtifactError,
    VideoArtifactStorage,
)


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


def require_growth_execution_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_growth_execution:
        raise AppError(
            "Growth analysis execution is disabled by the server",
            status_code=503,
        )


GrowthExecutionGateDep = Annotated[
    None, Depends(require_growth_execution_enabled)
]


def require_video_render_execution_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_video_render_execution:
        raise AppError(
            "Video render execution is disabled by the server",
            status_code=503,
        )


VideoRenderExecutionGateDep = Annotated[
    None, Depends(require_video_render_execution_enabled)
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


def get_provider_output_fetcher(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderOutputFetcher:
    return HttpProviderOutputFetcher(
        app_settings.video_artifact_max_bytes,
        app_settings.wanx_timeout,
    )


ProviderOutputFetcherDep = Annotated[
    ProviderOutputFetcher, Depends(get_provider_output_fetcher)
]


def get_video_artifact_storage(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> VideoArtifactStorage:
    configured = (app_settings.video_artifact_storage_root or "").strip()
    if not configured:
        raise AppError("Artifact storage is not configured", status_code=503)
    try:
        return LocalVideoArtifactStorage(
            Path(configured),
            app_settings.video_artifact_max_bytes,
        )
    except VideoArtifactError as exc:
        raise AppError(exc.safe_message, status_code=503) from exc


VideoArtifactStorageDep = Annotated[
    VideoArtifactStorage, Depends(get_video_artifact_storage)
]
