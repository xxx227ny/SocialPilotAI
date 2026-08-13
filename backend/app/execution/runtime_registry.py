from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.execution.handlers.instagram_publish import (
    InstagramPublishFinalizeV1Handler,
    InstagramPublishRefreshV1Handler,
    InstagramPublishSubmitV1Handler,
)
from app.execution.handlers.qwen_copy_matrix import QwenCopyMatrixGenerateV1Handler
from app.execution.handlers.qwen_strategy import QwenStrategyGenerateV1Handler
from app.execution.handlers.qwen_video_project import (
    QwenVideoProjectGenerateV1Handler,
)
from app.execution.handlers.tiktok_publish import (
    TikTokCreatorInfoV1Handler,
    TikTokRefreshV1Handler,
    TikTokSubmitV1Handler,
)
from app.execution.handlers.video_composition import VideoCompositionRenderV1Handler
from app.execution.handlers.wanx_video_render import (
    WanxVideoRenderRefreshV1Handler,
    WanxVideoRenderSubmitV1Handler,
)
from app.execution.handlers.youtube_publish import (
    YouTubePublishRefreshV1Handler,
    YouTubePublishSubmitV1Handler,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.providers import (
    QwenProvider,
    TextGenerationProvider,
    VisualGenerationProvider,
    WanxProvider,
)
from app.providers.instagram_provider import InstagramProvider
from app.providers.tiktok_provider import TikTokProvider
from app.providers.visual_base import (
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.providers.youtube_provider import YouTubeProvider
from app.services.instagram_media_probe import (
    FFprobeInstagramMediaProbe,
    InstagramMediaProbe,
)
from app.services.tiktok_media_probe import FFprobeTikTokMediaProbe, TikTokMediaProbe
from app.services.video_artifact_storage import (
    HttpProviderOutputFetcher,
    LocalVideoArtifactStorage,
    ProviderOutputFetcher,
    VideoArtifactStorage,
)


class LazyQwenProvider(TextGenerationProvider):
    """Construct the network adapter only after a confirmed Job is claimed."""

    def __init__(
        self,
        settings: Settings,
        provider_factory: Callable[[Settings], TextGenerationProvider] = QwenProvider,
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory

    def generate(self, prompt: str) -> str:
        return self.provider_factory(self.settings).generate(prompt)


class LazyWanxProvider(VisualGenerationProvider):
    """Construct the Wanx adapter only inside a claimed Worker Job."""

    def __init__(
        self,
        settings: Settings,
        provider_factory: Callable[[Settings], VisualGenerationProvider],
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory

    async def submit(self, request: VisualGenerationRequest) -> VisualTaskSubmission:
        return await self.provider_factory(self.settings).submit(request)

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        return await self.provider_factory(self.settings).fetch(provider_task_id)


class LazyYouTubeProvider:
    """Construct the YouTube adapter only inside a claimed Worker Job."""

    def __init__(
        self,
        settings: Settings,
        provider_factory: Callable[[Settings], YouTubeProvider],
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory

    def _provider(self) -> YouTubeProvider:
        return self.provider_factory(self.settings)

    async def refresh_access_token(self, refresh_token: str):
        return await self._provider().refresh_access_token(refresh_token)

    async def initiate_upload_session(self, **kwargs: object):
        return await self._provider().initiate_upload_session(**kwargs)

    async def upload_media(self, **kwargs: object):
        return await self._provider().upload_media(**kwargs)

    async def get_video_status(self, **kwargs: object):
        return await self._provider().get_video_status(**kwargs)


class LazyInstagramProvider:
    def __init__(
        self,
        settings: Settings,
        provider_factory: Callable[[Settings], InstagramProvider],
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory

    def _provider(self) -> InstagramProvider:
        return self.provider_factory(self.settings)

    async def create_resumable_reel_container(self, **kwargs: object):
        return await self._provider().create_resumable_reel_container(**kwargs)

    async def upload_reel_bytes(self, **kwargs: object):
        return await self._provider().upload_reel_bytes(**kwargs)

    async def get_container_status(self, **kwargs: object):
        return await self._provider().get_container_status(**kwargs)

    async def publish_reel(self, **kwargs: object):
        return await self._provider().publish_reel(**kwargs)


class LazyTikTokProvider:
    def __init__(
        self, settings: Settings, provider_factory: Callable[[Settings], TikTokProvider]
    ) -> None:
        self.settings, self.provider_factory = settings, provider_factory

    def _provider(self) -> TikTokProvider:
        return self.provider_factory(self.settings)

    async def refresh_access_token(self, refresh_token: str):
        return await self._provider().refresh_access_token(refresh_token)

    async def query_creator_info(self, **kwargs: object):
        return await self._provider().query_creator_info(**kwargs)

    async def initialize_direct_post(self, **kwargs: object):
        return await self._provider().initialize_direct_post(**kwargs)

    async def upload_video_chunk(self, **kwargs: object):
        return await self._provider().upload_video_chunk(**kwargs)

    async def fetch_publish_status(self, **kwargs: object):
        return await self._provider().fetch_publish_status(**kwargs)


class LazyVideoArtifactStorage(VideoArtifactStorage):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _storage(self) -> LocalVideoArtifactStorage:
        return LocalVideoArtifactStorage(
            Path(self.settings.video_artifact_storage_root),
            self.settings.video_artifact_max_bytes,
        )

    def store(self, *, task_id: int, content: bytes, content_type: str):
        return self._storage().store(
            task_id=task_id, content=content, content_type=content_type
        )

    def resolve(self, relative_path: str):
        return self._storage().resolve(relative_path)

    def delete(self, relative_path: str) -> None:
        self._storage().delete(relative_path)


def build_execution_handler_registry(
    *,
    session_factory: Callable[[], Session],
    settings: Settings,
    qwen_provider_factory: Callable[[Settings], TextGenerationProvider] = QwenProvider,
    wanx_provider_factory: Callable[
        [Settings], VisualGenerationProvider
    ] = WanxProvider,
    youtube_provider_factory: Callable[[Settings], YouTubeProvider] = YouTubeProvider,
    instagram_provider_factory: Callable[
        [Settings], InstagramProvider
    ] = InstagramProvider,
    tiktok_provider_factory: Callable[[Settings], TikTokProvider] = TikTokProvider,
    instagram_media_probe: InstagramMediaProbe | None = None,
    tiktok_media_probe: TikTokMediaProbe | None = None,
    output_fetcher: ProviderOutputFetcher | None = None,
    artifact_storage: VideoArtifactStorage | None = None,
) -> ExecutionHandlerRegistry:
    registry = ExecutionHandlerRegistry()
    registry.register(
        QwenStrategyGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    registry.register(
        QwenCopyMatrixGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    registry.register(
        QwenVideoProjectGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    wanx_provider = LazyWanxProvider(settings, wanx_provider_factory)
    render_fetcher = output_fetcher or HttpProviderOutputFetcher(
        settings.video_artifact_max_bytes, settings.wanx_timeout
    )
    render_storage = artifact_storage or LazyVideoArtifactStorage(settings)
    registry.register(
        WanxVideoRenderSubmitV1Handler(
            session_factory=session_factory,
            provider=wanx_provider,
            settings=settings,
            output_fetcher=render_fetcher,
            artifact_storage=render_storage,
        )
    )
    registry.register(
        WanxVideoRenderRefreshV1Handler(
            session_factory=session_factory,
            provider=wanx_provider,
            settings=settings,
            output_fetcher=render_fetcher,
            artifact_storage=render_storage,
        )
    )
    registry.register(
        VideoCompositionRenderV1Handler(
            session_factory=session_factory,
            settings=settings,
        )
    )
    youtube_provider = LazyYouTubeProvider(settings, youtube_provider_factory)
    registry.register(
        YouTubePublishSubmitV1Handler(
            session_factory=session_factory,
            provider=youtube_provider,
            settings=settings,
            artifact_storage=render_storage,
        )
    )
    registry.register(
        YouTubePublishRefreshV1Handler(
            session_factory=session_factory,
            provider=youtube_provider,
            settings=settings,
            artifact_storage=render_storage,
        )
    )
    instagram_provider = LazyInstagramProvider(settings, instagram_provider_factory)
    media_probe = instagram_media_probe or FFprobeInstagramMediaProbe(settings)
    for handler in (
        InstagramPublishSubmitV1Handler,
        InstagramPublishRefreshV1Handler,
        InstagramPublishFinalizeV1Handler,
    ):
        registry.register(
            handler(
                session_factory=session_factory,
                provider=instagram_provider,
                settings=settings,
                artifact_storage=render_storage,
                media_probe=media_probe,
            )
        )
    tiktok_provider = LazyTikTokProvider(settings, tiktok_provider_factory)
    tiktok_probe = tiktok_media_probe or FFprobeTikTokMediaProbe(settings)
    for handler in (
        TikTokCreatorInfoV1Handler,
        TikTokSubmitV1Handler,
        TikTokRefreshV1Handler,
    ):
        registry.register(
            handler(
                session_factory=session_factory,
                provider=tiktok_provider,
                settings=settings,
                artifact_storage=render_storage,
                media_probe=tiktok_probe,
            )
        )
    return registry
