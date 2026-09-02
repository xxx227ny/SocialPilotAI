from pathlib import Path
from typing import Annotated

from fastapi import Depends
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.api.auth_dependency import require_authenticated_user
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.providers import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    QwenProvider,
    WanxProvider,
)
from app.providers.base import TextGenerationProvider
from app.providers.instagram_provider import InstagramProvider, InstagramProviderError
from app.providers.live_configuration import (
    get_provider_failure_metadata,
    provider_public_http_status,
    public_provider_failure,
    qwen_provider_configured,
    safe_error_message,
    wanx_provider_configured,
)
from app.providers.pinterest_provider import PinterestProvider, PinterestProviderError
from app.providers.tiktok_provider import TikTokProvider, TikTokProviderError
from app.providers.visual_base import VisualGenerationProvider
from app.providers.youtube_provider import YouTubeProvider, YouTubeProviderError
from app.services.demo_auth_service import AuthenticatedUser
from app.services.instagram_media_probe import (
    FFprobeInstagramMediaProbe,
    InstagramMediaProbe,
)
from app.services.provider_credential_service import ProviderCredentialService
from app.services.tiktok_media_probe import FFprobeTikTokMediaProbe, TikTokMediaProbe
from app.services.user_auth_service import AuthenticatedPrincipal
from app.services.video_artifact_storage import (
    HttpProviderOutputFetcher,
    LocalVideoArtifactStorage,
    ProviderOutputFetcher,
    VideoArtifactError,
    VideoArtifactStorage,
)


def get_workspace_provider_settings(
    app_settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AuthenticatedPrincipal | AuthenticatedUser | None,
        Depends(require_authenticated_user),
    ],
) -> Settings:
    if not app_settings.enable_user_auth:
        return app_settings
    workspace_id = (
        principal.workspace_id
        if isinstance(principal, AuthenticatedPrincipal)
        else None
    )
    runtime = (
        ProviderCredentialService(db, app_settings).read_dashscope_runtime(
            workspace_id,
            require_verified=True,
        )
        if workspace_id is not None
        else None
    )
    secret = SecretStr(runtime.api_key) if runtime else None
    return app_settings.model_copy(
        update={
            "enable_user_auth": False,
            "qwen_api_key": secret,
            "dashscope_api_key": None,
            "wanx_api_key": secret,
            "token_plan_api_key_file": "",
            "qwen_endpoint": runtime.qwen_endpoint if runtime else None,
            "wanx_endpoint": runtime.native_endpoint if runtime else None,
            "wanx_image_endpoint": runtime.wanx_image_endpoint if runtime else "",
            "qwen_tts_endpoint": runtime.qwen_tts_endpoint if runtime else "",
            "happyhorse_endpoint": runtime.happyhorse_endpoint if runtime else "",
        }
    )


WorkspaceProviderSettingsDep = Annotated[
    Settings, Depends(get_workspace_provider_settings)
]


def get_text_generation_provider(
    app_settings: WorkspaceProviderSettingsDep,
) -> TextGenerationProvider:
    try:
        return SafeObservableTextProvider(QwenProvider(app_settings))
    except (ProviderAuthenticationError, ProviderConfigurationError) as exc:
        raise AppError(
            "Workspace API Key is missing or unverified", status_code=503
        ) from exc


class SafeObservableTextProvider(TextGenerationProvider):
    """Translate classified Qwen failures into safe public categories."""

    def __init__(self, provider: TextGenerationProvider) -> None:
        self.provider = provider

    def generate(self, prompt: str) -> str:
        try:
            return self.provider.generate(prompt)
        except ProviderError as exc:
            metadata = get_provider_failure_metadata(exc)
            if metadata is None:
                raise
            raise AppError(
                safe_error_message(metadata),
                provider_public_http_status(metadata),
                provider_failure=public_provider_failure(metadata),
            ) from exc


TextProviderDep = Annotated[
    TextGenerationProvider, Depends(get_text_generation_provider)
]


def require_strategy_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_strategy_execution:
        raise AppError(
            "Strategy execution is disabled by the server",
            status_code=503,
        )


StrategyExecutionGateDep = Annotated[None, Depends(require_strategy_execution_enabled)]


def require_copy_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_copy_execution:
        raise AppError(
            "Copy execution is disabled by the server",
            status_code=503,
        )


CopyExecutionGateDep = Annotated[None, Depends(require_copy_execution_enabled)]


def require_video_project_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_video_project_execution:
        raise AppError(
            "VideoProject execution is disabled by the server",
            status_code=503,
        )
    _require_live_qwen_configuration(app_settings)


VideoProjectExecutionGateDep = Annotated[
    None, Depends(require_video_project_execution_enabled)
]


def get_video_project_text_provider(
    gate: VideoProjectExecutionGateDep,
    provider: TextProviderDep,
) -> TextGenerationProvider:
    del gate
    return provider


VideoProjectTextProviderDep = Annotated[
    TextGenerationProvider, Depends(get_video_project_text_provider)
]


def require_v2_copy_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_copy_execution:
        raise AppError(
            "Copy execution is disabled by the server",
            status_code=503,
        )
    if not app_settings.enable_v2_copy_execution:
        raise AppError(
            "V2 Copy execution is disabled by the server",
            status_code=503,
        )
    _require_live_qwen_configuration(app_settings)


V2CopyExecutionGateDep = Annotated[None, Depends(require_v2_copy_execution_enabled)]


def require_v2_video_project_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_v2_video_project_execution:
        raise AppError(
            "V2 VideoProject execution is disabled by the server",
            status_code=503,
        )
    _require_live_qwen_configuration(app_settings)


V2VideoProjectExecutionGateDep = Annotated[
    None, Depends(require_v2_video_project_execution_enabled)
]


def require_growth_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_growth_execution:
        raise AppError(
            "Growth analysis execution is disabled by the server",
            status_code=503,
        )
    _require_live_qwen_configuration(app_settings)


GrowthExecutionGateDep = Annotated[None, Depends(require_growth_execution_enabled)]


def require_video_render_execution_enabled(
    app_settings: WorkspaceProviderSettingsDep,
) -> None:
    if not app_settings.enable_video_render_execution:
        raise AppError(
            "Video render execution is disabled by the server",
            status_code=503,
        )
    if app_settings.require_live_provider_coherence and not wanx_provider_configured(
        app_settings
    ):
        raise AppError(
            "Wanx live provider configuration is inconsistent",
            status_code=503,
        )


VideoRenderExecutionGateDep = Annotated[
    None, Depends(require_video_render_execution_enabled)
]


def require_video_composition_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_video_composition:
        raise AppError("Video composition execution is disabled by the server", 503)


VideoCompositionGateDep = Annotated[None, Depends(require_video_composition_enabled)]


def require_video_composition_enhancement_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_video_composition_enhancement:
        raise AppError("Video composition enhancement is disabled by the server", 503)


VideoCompositionEnhancementGateDep = Annotated[
    None, Depends(require_video_composition_enhancement_enabled)
]


def _require_live_qwen_configuration(app_settings: Settings) -> None:
    if app_settings.require_live_provider_coherence and not qwen_provider_configured(
        app_settings
    ):
        raise AppError(
            "Qwen live provider configuration is inconsistent",
            status_code=503,
        )


def get_visual_generation_provider(
    app_settings: WorkspaceProviderSettingsDep,
) -> VisualGenerationProvider:
    try:
        return WanxProvider(app_settings)
    except (ProviderAuthenticationError, ProviderConfigurationError) as exc:
        raise AppError(
            "Workspace API Key is missing or unverified", status_code=503
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


def get_optional_video_artifact_storage(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> VideoArtifactStorage | None:
    configured = (app_settings.video_artifact_storage_root or "").strip()
    if not configured:
        return None
    try:
        return LocalVideoArtifactStorage(
            Path(configured),
            app_settings.video_artifact_max_bytes,
        )
    except VideoArtifactError:
        return None


OptionalVideoArtifactStorageDep = Annotated[
    VideoArtifactStorage | None,
    Depends(get_optional_video_artifact_storage),
]


def require_social_account_binding_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_social_account_binding:
        raise AppError("Social account binding is disabled by the server", 503)


SocialAccountBindingGateDep = Annotated[
    None, Depends(require_social_account_binding_enabled)
]


def require_youtube_publishing_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_youtube_publishing:
        raise AppError("YouTube publishing is disabled by the server", 503)


YouTubePublishingGateDep = Annotated[None, Depends(require_youtube_publishing_enabled)]


def get_youtube_provider(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> YouTubeProvider:
    try:
        return YouTubeProvider(app_settings)
    except YouTubeProviderError as exc:
        raise AppError("YouTube provider is not configured", 503) from exc


def get_binding_youtube_provider(
    gate: SocialAccountBindingGateDep,
    provider: Annotated[YouTubeProvider, Depends(get_youtube_provider)],
) -> YouTubeProvider:
    del gate
    return provider


def get_publishing_youtube_provider(
    gate: YouTubePublishingGateDep,
    provider: Annotated[YouTubeProvider, Depends(get_youtube_provider)],
) -> YouTubeProvider:
    del gate
    return provider


BindingYouTubeProviderDep = Annotated[
    YouTubeProvider, Depends(get_binding_youtube_provider)
]
PublishingYouTubeProviderDep = Annotated[
    YouTubeProvider, Depends(get_publishing_youtube_provider)
]


def require_instagram_account_binding_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_instagram_account_binding:
        raise AppError("Instagram account binding is disabled by the server", 503)


InstagramAccountBindingGateDep = Annotated[
    None, Depends(require_instagram_account_binding_enabled)
]


def get_instagram_provider(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> InstagramProvider:
    try:
        return InstagramProvider(app_settings)
    except InstagramProviderError as exc:
        raise AppError("Instagram provider is not configured", 503) from exc


def get_binding_instagram_provider(
    gate: InstagramAccountBindingGateDep,
    provider: Annotated[InstagramProvider, Depends(get_instagram_provider)],
) -> InstagramProvider:
    del gate
    return provider


BindingInstagramProviderDep = Annotated[
    InstagramProvider, Depends(get_binding_instagram_provider)
]


def require_instagram_publishing_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_instagram_publishing:
        raise AppError("Instagram publishing is disabled by the server", 503)


InstagramPublishingGateDep = Annotated[
    None, Depends(require_instagram_publishing_enabled)
]


def get_instagram_media_probe(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> InstagramMediaProbe:
    return FFprobeInstagramMediaProbe(app_settings)


InstagramMediaProbeDep = Annotated[
    InstagramMediaProbe, Depends(get_instagram_media_probe)
]


def require_tiktok_account_binding_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_tiktok_account_binding:
        raise AppError("TikTok account binding is disabled by the server", 503)


TikTokAccountBindingGateDep = Annotated[
    None, Depends(require_tiktok_account_binding_enabled)
]


def get_tiktok_provider(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> TikTokProvider:
    try:
        return TikTokProvider(app_settings)
    except TikTokProviderError:
        raise AppError("TikTok provider is not configured", 503) from None


def get_binding_tiktok_provider(
    gate: TikTokAccountBindingGateDep,
    provider: Annotated[TikTokProvider, Depends(get_tiktok_provider)],
) -> TikTokProvider:
    del gate
    return provider


BindingTikTokProviderDep = Annotated[
    TikTokProvider, Depends(get_binding_tiktok_provider)
]


def require_pinterest_account_binding_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_pinterest_account_binding:
        raise AppError("Pinterest account binding is disabled by the server", 503)


PinterestAccountBindingGateDep = Annotated[
    None, Depends(require_pinterest_account_binding_enabled)
]


def get_pinterest_provider(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> PinterestProvider:
    try:
        return PinterestProvider(app_settings)
    except PinterestProviderError:
        raise AppError("Pinterest provider is not configured", 503) from None


def get_binding_pinterest_provider(
    gate: PinterestAccountBindingGateDep,
    provider: Annotated[PinterestProvider, Depends(get_pinterest_provider)],
) -> PinterestProvider:
    del gate
    return provider


BindingPinterestProviderDep = Annotated[
    PinterestProvider, Depends(get_binding_pinterest_provider)
]


def require_tiktok_publishing_enabled(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not app_settings.enable_tiktok_publishing:
        raise AppError("TikTok publishing is disabled by the server", 503)


TikTokPublishingGateDep = Annotated[None, Depends(require_tiktok_publishing_enabled)]


def get_tiktok_media_probe(
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> TikTokMediaProbe:
    return FFprobeTikTokMediaProbe(app_settings)


TikTokMediaProbeDep = Annotated[TikTokMediaProbe, Depends(get_tiktok_media_probe)]
