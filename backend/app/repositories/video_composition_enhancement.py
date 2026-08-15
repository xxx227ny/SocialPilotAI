from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
)


class VideoCompositionEnhancementRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, enhancement_id: int) -> VideoCompositionEnhancement | None:
        return self.session.scalar(
            select(VideoCompositionEnhancement)
            .options(
                selectinload(VideoCompositionEnhancement.composition),
                selectinload(VideoCompositionEnhancement.source_artifact),
                selectinload(VideoCompositionEnhancement.voiceover_artifact),
                selectinload(VideoCompositionEnhancement.music_artifact),
                selectinload(VideoCompositionEnhancement.subtitle_artifact),
                selectinload(VideoCompositionEnhancement.artifact),
            )
            .where(VideoCompositionEnhancement.id == enhancement_id)
        )

    def get_by_key(self, key: str) -> VideoCompositionEnhancement | None:
        enhancement_id = self.session.scalar(
            select(VideoCompositionEnhancement.id).where(
                VideoCompositionEnhancement.idempotency_key == key
            )
        )
        return self.get(enhancement_id) if enhancement_id is not None else None

    def get_audio(self, artifact_id: int) -> VideoCompositionAudioArtifact | None:
        return self.session.get(VideoCompositionAudioArtifact, artifact_id)

    def list_audio(
        self, product_id: int, composition_id: int
    ) -> list[VideoCompositionAudioArtifact]:
        return list(
            self.session.scalars(
                select(VideoCompositionAudioArtifact)
                .where(
                    VideoCompositionAudioArtifact.product_id == product_id,
                    VideoCompositionAudioArtifact.composition_id == composition_id,
                )
                .order_by(VideoCompositionAudioArtifact.id)
            )
        )

    def get_artifact(
        self, artifact_id: int
    ) -> VideoCompositionEnhancementArtifact | None:
        return self.session.scalar(
            select(VideoCompositionEnhancementArtifact)
            .options(selectinload(VideoCompositionEnhancementArtifact.enhancement))
            .where(VideoCompositionEnhancementArtifact.id == artifact_id)
        )

    def get_subtitle(
        self, artifact_id: int
    ) -> VideoCompositionSubtitleArtifact | None:
        return self.session.scalar(
            select(VideoCompositionSubtitleArtifact)
            .options(selectinload(VideoCompositionSubtitleArtifact.enhancement))
            .where(VideoCompositionSubtitleArtifact.id == artifact_id)
        )
