from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.video_composition import VideoComposition, VideoCompositionArtifact


class VideoCompositionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, composition_id: int) -> VideoComposition | None:
        return self.session.scalar(
            select(VideoComposition)
            .options(
                selectinload(VideoComposition.shots),
                selectinload(VideoComposition.artifact),
            )
            .where(VideoComposition.id == composition_id)
        )

    def get_by_key(self, key: str) -> VideoComposition | None:
        return self.session.scalar(
            select(VideoComposition)
            .options(
                selectinload(VideoComposition.shots),
                selectinload(VideoComposition.artifact),
            )
            .where(VideoComposition.idempotency_key == key)
        )

    def get_artifact(self, artifact_id: int) -> VideoCompositionArtifact | None:
        return self.session.scalar(
            select(VideoCompositionArtifact)
            .options(selectinload(VideoCompositionArtifact.composition))
            .where(VideoCompositionArtifact.id == artifact_id)
        )
