from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VideoRenderArtifact
from app.schemas.video_render_artifact import VideoRenderArtifactCreate


class VideoRenderArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, video_render_task_id: int, data: VideoRenderArtifactCreate
    ) -> VideoRenderArtifact:
        artifact = VideoRenderArtifact(
            video_render_task_id=video_render_task_id,
            provider_output_url=data.provider_output_url,
            storage_path=data.storage_path,
            artifact_metadata=data.metadata,
            expires_at=data.expires_at,
        )
        self.session.add(artifact)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def get_by_task_id(self, task_id: int) -> VideoRenderArtifact | None:
        return self.session.scalar(
            select(VideoRenderArtifact).where(
                VideoRenderArtifact.video_render_task_id == task_id
            )
        )

    def update(
        self,
        artifact: VideoRenderArtifact,
        data: VideoRenderArtifactCreate,
    ) -> VideoRenderArtifact:
        artifact.provider_output_url = data.provider_output_url
        artifact.storage_path = data.storage_path
        artifact.artifact_metadata = data.metadata
        artifact.expires_at = data.expires_at
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def list(self) -> list[VideoRenderArtifact]:
        statement = select(VideoRenderArtifact).order_by(
            VideoRenderArtifact.created_at.desc(),
            VideoRenderArtifact.id.desc(),
        )
        return list(self.session.scalars(statement).all())
