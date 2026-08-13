from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import VideoComposition, VideoCompositionArtifact
from app.repositories.video_composition import VideoCompositionRepository
from app.schemas.video_composition import VideoCompositionRead
from app.services.video_artifact_storage import (
    LocalVideoArtifactStorage,
    VideoArtifactError,
)
from app.services.video_composition_ffmpeg import FFmpegShot, VideoCompositionFFmpeg
from app.services.video_composition_probe import (
    VideoCompositionMedia,
    VideoCompositionProbe,
)
from app.services.video_render_operation_service import VideoArtifactAccessService


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class VideoCompositionService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = VideoCompositionRepository(session)
        root = Path(settings.video_artifact_storage_root or "")
        if not root.is_absolute():
            raise AppError("Artifact storage is not configured", 503)
        self.storage = LocalVideoArtifactStorage(
            root, settings.video_artifact_max_bytes
        )
        self.access = VideoArtifactAccessService(session, self.storage)

    def get(self, composition_id: int) -> VideoCompositionRead:
        composition = self.repository.get(composition_id)
        if composition is None:
            raise AppError("Video composition not found", 404)
        return VideoCompositionRead.model_validate(composition)

    def render(self, composition_id: int) -> VideoCompositionArtifact:
        composition = self.repository.get(composition_id)
        if composition is None:
            raise AppError("Video composition not found", 404)
        if composition.status == "SUCCEEDED" and composition.artifact is not None:
            return composition.artifact
        if composition.status not in {"QUEUED", "FAILED", "PERSIST_UNKNOWN"}:
            raise AppError("Video composition is not renderable", 409)
        resolved: list[FFmpegShot] = []
        for shot in composition.shots:
            verified = self.access.resolve_verified(shot.source_artifact_id)
            task = verified.artifact.video_render_task
            if (
                shot.product_id != composition.product_id
                or shot.video_project_id != composition.video_project_id
                or task.id != shot.source_render_task_id
                or task.video_project_id != composition.video_project_id
                or verified.sha256 != shot.source_artifact_sha256
                or _sha256_file(verified.path) != shot.source_artifact_sha256
            ):
                self._fail(composition, "COMPOSITION_FROZEN_SOURCE_CHANGED")
                raise AppError("Composition frozen source changed", 409)
            resolved.append(
                FFmpegShot(
                    path=verified.path,
                    trim_start_ms=shot.trim_start_ms,
                    duration_ms=shot.end_ms - shot.start_ms,
                )
            )
        composition.status = "COMPOSING"
        composition.safe_error_code = None
        self.session.commit()
        temp_root = Path(self.settings.video_composition_temp_root or "")
        if not temp_root.is_absolute():
            self._fail(composition, "COMPOSITION_TEMP_STORAGE_UNAVAILABLE")
            raise AppError("Composition temporary storage is unavailable", 503)
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"composition-{composition.id}-", dir=temp_root
        ) as workspace:
            output = Path(workspace) / "output.mp4"
            VideoCompositionFFmpeg(
                self.settings.video_composition_ffmpeg_path,
                self.settings.video_composition_process_timeout,
            ).render(resolved, output)
            composition.status = "VERIFYING"
            self.session.commit()
            probe = VideoCompositionProbe(
                self.settings.video_composition_ffprobe_path,
                self.settings.video_composition_process_timeout,
            )
            media = probe.inspect(output)
            probe.validate(media)
            content = output.read_bytes()
            stored, created = self.storage.store_immutable(
                task_id=composition.id,
                content=content,
                content_type="video/mp4",
            )
            return self._persist_result(
                composition.id,
                media,
                stored.relative_path,
                stored.size_bytes,
                stored.sha256,
                created,
            )

    def _persist_result(
        self,
        composition_id: int,
        media: VideoCompositionMedia,
        storage_path: str,
        size_bytes: int,
        sha256: str,
        created: bool,
    ) -> VideoCompositionArtifact:
        composition = self.repository.get(composition_id)
        if composition is None:
            if created:
                self.storage.delete(storage_path)
            raise AppError("Video composition disappeared", 409)
        artifact = composition.artifact or VideoCompositionArtifact(
            composition_id=composition.id
        )
        artifact.storage_path = storage_path
        artifact.content_type = "video/mp4"
        artifact.size_bytes = size_bytes
        artifact.sha256 = sha256
        artifact.duration_ms = media.duration_ms
        artifact.width = media.width
        artifact.height = media.height
        artifact.fps_numerator = media.fps_numerator
        artifact.fps_denominator = media.fps_denominator
        artifact.video_codec = media.video_codec
        artifact.pixel_format = media.pixel_format
        artifact.audio_codec = media.audio_codec
        artifact.audio_sample_rate = media.audio_sample_rate
        artifact.container = media.container
        artifact.source_chain_digest = composition.source_chain_digest
        self.session.add(artifact)
        composition.status = "SUCCEEDED"
        composition.completed_at = datetime.now(UTC)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            winner = self.repository.get(composition_id)
            if (
                winner is not None
                and winner.artifact is not None
                and winner.artifact.sha256 == sha256
            ):
                return winner.artifact
            if created:
                self.storage.delete(storage_path)
            if winner is not None:
                winner.status = "PERSIST_UNKNOWN"
                winner.safe_error_code = "COMPOSITION_RESULT_PERSIST_UNKNOWN"
                self.session.commit()
            raise AppError("Composition result persistence is uncertain", 500) from None
        self.session.refresh(artifact)
        return artifact

    def _fail(self, composition: VideoComposition, code: str) -> None:
        composition.status = "FAILED"
        composition.safe_error_code = code
        composition.completed_at = datetime.now(UTC)
        self.session.commit()


class VideoCompositionArtifactAccessService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.repository = VideoCompositionRepository(session)
        self.storage = LocalVideoArtifactStorage(
            Path(settings.video_artifact_storage_root or ""),
            settings.video_artifact_max_bytes,
        )

    def resolve(self, artifact_id: int) -> tuple[VideoCompositionArtifact, Path]:
        artifact = self.repository.get_artifact(artifact_id)
        if artifact is None or artifact.composition.status != "SUCCEEDED":
            raise AppError("Composition artifact not found", 404)
        try:
            path, content_type = self.storage.resolve(artifact.storage_path)
        except VideoArtifactError as exc:
            raise AppError(exc.safe_message, 404) from exc
        if (
            content_type != "video/mp4"
            or artifact.content_type != "video/mp4"
            or path.stat().st_size != artifact.size_bytes
            or _sha256_file(path) != artifact.sha256
        ):
            raise AppError("Composition artifact integrity check failed", 409)
        return artifact, path
