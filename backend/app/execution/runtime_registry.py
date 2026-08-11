from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.execution.handlers.qwen_copy_matrix import QwenCopyMatrixGenerateV1Handler
from app.execution.handlers.qwen_strategy import QwenStrategyGenerateV1Handler
from app.execution.handlers.qwen_video_project import (
    QwenVideoProjectGenerateV1Handler,
)
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
from app.providers.visual_base import (
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.providers.youtube_provider import YouTubeProvider
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
    return registry
