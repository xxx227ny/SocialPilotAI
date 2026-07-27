from collections.abc import Callable

from sqlalchemy.orm import Session

from app.providers.visual_base import VisualGenerationProvider
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.video_render import VideoRenderTaskCreate
from app.services.video_render_execution_service import (
    VideoRenderExecutionResult,
    VideoRenderExecutionService,
)
from app.services.video_render_service import VideoRenderService

LIVE_SCENE_SEQUENCE = 1
LIVE_RESOLUTION = "720P"
LIVE_IDEMPOTENCY_VERSION = "v1"

VisualProviderFactory = Callable[[], VisualGenerationProvider]


class LiveVideoRenderService:
    """Safe facade for a single fixed-parameter presentation render."""

    def __init__(
        self, session: Session, provider_factory: VisualProviderFactory
    ) -> None:
        self.session = session
        self.provider_factory = provider_factory
        self.render_service = VideoRenderService(session)
        self.artifact_repository = VideoRenderArtifactRepository(session)

    async def execute(
        self, video_project_id: int
    ) -> VideoRenderExecutionResult:
        artifacts = (
            self.render_service.list_succeeded_artifacts_by_video_project(
                video_project_id
            )
        )
        if artifacts:
            artifact = artifacts[0]
            return VideoRenderExecutionResult(
                task=artifact.video_render_task,
                artifact=artifact,
                external_call=False,
            )

        task = self.render_service.create_render_task(
            video_project_id,
            VideoRenderTaskCreate(
                scene_sequence=LIVE_SCENE_SEQUENCE,
                resolution=LIVE_RESOLUTION,
                idempotency_key=self._idempotency_key(video_project_id),
            ),
        )
        if task.status != "CREATED":
            return VideoRenderExecutionResult(
                task=task,
                artifact=self.artifact_repository.get_by_task_id(task.id),
                external_call=False,
            )

        provider = self.provider_factory()
        return await VideoRenderExecutionService(
            self.session, provider, allow_live_demo=True
        ).submit(task.id)

    @staticmethod
    def _idempotency_key(video_project_id: int) -> str:
        return (
            f"live-presentation:{video_project_id}:"
            f"scene-{LIVE_SCENE_SEQUENCE}:{LIVE_RESOLUTION.casefold()}:"
            f"{LIVE_IDEMPOTENCY_VERSION}"
        )
