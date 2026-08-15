from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
)
from app.repositories.video_composition_enhancement import (
    VideoCompositionEnhancementRepository,
)
from app.schemas.video_composition_enhancement import (
    EnhancementMixInput,
    SubtitleCueInput,
    SubtitleStyleInput,
    VideoCompositionEnhancementPreflightRequest,
    VideoCompositionEnhancementRead,
)
from app.services.video_composition_asset_storage import VideoCompositionAssetStorage
from app.services.video_composition_enhancement_ffmpeg import (
    EnhancementFFmpegInput,
    VideoCompositionEnhancementFFmpeg,
    VideoCompositionEnhancementFFmpegError,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from app.services.video_composition_enhancement_probe import (
    EnhancementMedia,
    VideoCompositionEnhancementProbe,
    VideoCompositionEnhancementProbeError,
)
from app.services.video_composition_service import VideoCompositionArtifactAccessService
from app.services.video_composition_subtitles import render_webvtt


class VideoCompositionEnhancementService:
    def __init__(self, session: Session, settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = VideoCompositionEnhancementRepository(session)
        self.assets = VideoCompositionAssetStorage(
            Path(settings.video_artifact_storage_root or ""),
            settings.video_artifact_max_bytes,
        )
        self.video_access = VideoCompositionArtifactAccessService(session, settings)

    def get(self, enhancement_id: int) -> VideoCompositionEnhancementRead:
        enhancement = self.repository.get(enhancement_id)
        if enhancement is None:
            raise AppError("Video composition enhancement not found", 404)
        return VideoCompositionEnhancementRead.model_validate(enhancement)

    def enhance(
        self,
        enhancement_id: int,
        *,
        before_persist=None,
    ) -> VideoCompositionEnhancementArtifact:
        enhancement = self.repository.get(enhancement_id)
        if enhancement is None:
            raise AppError("Video composition enhancement not found", 404)
        if enhancement.status == "SUCCEEDED" and enhancement.artifact is not None:
            return enhancement.artifact
        if enhancement.status not in {"QUEUED", "FAILED", "PERSIST_UNKNOWN"}:
            raise AppError("Video composition enhancement is not renderable", 409)
        cues = [
            SubtitleCueInput.model_validate(item)
            for item in enhancement.subtitle_cues_json
        ]
        style = SubtitleStyleInput.model_validate(enhancement.subtitle_style_json)
        try:
            current = VideoCompositionEnhancementPreflightService(
                self.session,
                self.settings,
            ).run(
                enhancement.product_id,
                VideoCompositionEnhancementPreflightRequest(
                    composition_id=enhancement.composition_id,
                    source_artifact_id=enhancement.source_artifact_id,
                    voiceover_artifact_id=enhancement.voiceover_artifact_id,
                    music_artifact_id=enhancement.music_artifact_id,
                    cues=cues,
                    style=style,
                    mix=EnhancementMixInput(
                        voiceover_gain_db=enhancement.voiceover_gain_millidb / 1000,
                        music_gain_db=enhancement.music_gain_millidb / 1000,
                        ducking_reduction_db=(
                            enhancement.ducking_reduction_millidb / 1000
                        ),
                        target_lufs=enhancement.target_lufs_milli / 1000,
                        true_peak_db=enhancement.true_peak_millidb / 1000,
                    ),
                ),
            )
            if (
                current.input_digest != enhancement.input_digest
                or current.source_chain_digest != enhancement.source_chain_digest
            ):
                raise AppError("Enhancement frozen identity changed", 409)
            source_artifact, source_path = self.video_access.resolve(
                enhancement.source_artifact_id
            )
            voice = enhancement.voiceover_artifact
            music = enhancement.music_artifact
            if (
                source_artifact.composition_id != enhancement.composition_id
                or source_artifact.sha256 != enhancement.source_artifact.sha256
                or voice.product_id != enhancement.product_id
                or voice.video_project_id != enhancement.video_project_id
                or voice.composition_id != enhancement.composition_id
                or voice.kind != "voiceover"
            ):
                raise AppError("Enhancement frozen identity changed", 409)
            voice_path = self.assets.resolve_audio(
                voice.storage_path, voice.content_type, voice.size_bytes, voice.sha256
            )
            music_path = None
            if music is not None:
                if (
                    music.id != enhancement.music_artifact_id
                    or music.product_id != enhancement.product_id
                    or music.video_project_id != enhancement.video_project_id
                    or music.composition_id != enhancement.composition_id
                    or music.kind != "music"
                ):
                    raise AppError("Enhancement frozen identity changed", 409)
                music_path = self.assets.resolve_audio(
                    music.storage_path,
                    music.content_type,
                    music.size_bytes,
                    music.sha256,
                )
        except AppError:
            self._fail(enhancement, "ENHANCEMENT_FROZEN_IDENTITY_MISMATCH")
            raise
        enhancement.status = "ENHANCING"
        enhancement.safe_error_code = None
        self.session.commit()
        temp_root = Path(self.settings.video_composition_temp_root or "")
        if not temp_root.is_absolute():
            self._fail(enhancement, "ENHANCEMENT_TEMP_STORAGE_UNAVAILABLE")
            raise AppError("Composition temporary storage is unavailable", 503)
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"enhancement-{enhancement.id}-", dir=temp_root
        ) as workspace_name:
            workspace = Path(workspace_name)
            subtitle_content = render_webvtt(cues, style)
            subtitle_path = workspace / "subtitles.vtt"
            subtitle_path.write_bytes(subtitle_content)
            output = workspace / "enhanced.mp4"
            try:
                VideoCompositionEnhancementFFmpeg(
                    self.settings.video_composition_ffmpeg_path,
                    self.settings.video_composition_process_timeout,
                ).render(
                    EnhancementFFmpegInput(
                        video=source_path,
                        voiceover=voice_path,
                        music=music_path,
                        subtitle=subtitle_path,
                        voiceover_gain_millidb=enhancement.voiceover_gain_millidb,
                        music_gain_millidb=enhancement.music_gain_millidb,
                        ducking_reduction_millidb=enhancement.ducking_reduction_millidb,
                        target_lufs_milli=enhancement.target_lufs_milli,
                        true_peak_millidb=enhancement.true_peak_millidb,
                        font_size=style.font_size,
                        bottom_margin=style.bottom_margin,
                        outline_width=style.outline_width,
                    ),
                    output,
                )
                enhancement.status = "VERIFYING"
                self.session.commit()
                probe = VideoCompositionEnhancementProbe(
                    self.settings.video_composition_ffprobe_path,
                    self.settings.video_composition_ffmpeg_path,
                    self.settings.video_composition_process_timeout,
                )
                media = probe.inspect(output)
                probe.validate(
                    media,
                    enhancement.target_lufs_milli,
                    enhancement.true_peak_millidb,
                )
            except (
                VideoCompositionEnhancementFFmpegError,
                VideoCompositionEnhancementProbeError,
            ) as exc:
                self._fail(enhancement, str(exc))
                raise AppError("Video composition enhancement failed", 500) from None
            if before_persist is not None:
                before_persist()
            stored_subtitle = self.assets.store_immutable(
                identity=f"enhancement-{enhancement.id}-subtitles",
                content=subtitle_content,
                extension=".vtt",
            )
            stored_video = self.assets.store_immutable(
                identity=f"enhancement-{enhancement.id}",
                content=output.read_bytes(),
                extension=".mp4",
            )
            return self._persist(
                enhancement.id,
                media,
                stored_subtitle,
                stored_video,
                len(cues),
            )

    def _persist(self, enhancement_id, media, subtitle, video, cue_count):
        enhancement = self.repository.get(enhancement_id)
        if enhancement is None:
            raise AppError("Video composition enhancement disappeared", 409)
        subtitle_record = (
            enhancement.subtitle_artifact
            or VideoCompositionSubtitleArtifact(enhancement_id=enhancement.id)
        )
        subtitle_record.storage_path = subtitle.relative_path
        subtitle_record.content_type = "text/vtt; charset=utf-8"
        subtitle_record.size_bytes = subtitle.size_bytes
        subtitle_record.sha256 = subtitle.sha256
        subtitle_record.format = "webvtt"
        subtitle_record.cue_count = cue_count
        self.session.add(subtitle_record)
        self.session.flush()
        artifact = enhancement.artifact or VideoCompositionEnhancementArtifact(
            enhancement_id=enhancement.id
        )
        self._apply_media(artifact, media)
        artifact.subtitle_artifact_id = subtitle_record.id
        artifact.storage_path = video.relative_path
        artifact.content_type = "video/mp4"
        artifact.size_bytes = video.size_bytes
        artifact.sha256 = video.sha256
        artifact.subtitle_format = "webvtt"
        artifact.subtitle_cue_count = cue_count
        artifact.subtitle_sha256 = subtitle.sha256
        artifact.source_chain_digest = enhancement.source_chain_digest
        self.session.add(artifact)
        enhancement.status = "SUCCEEDED"
        enhancement.completed_at = datetime.now(UTC)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            winner = self.repository.get(enhancement_id)
            if winner is not None and winner.artifact is not None:
                return winner.artifact
            if winner is not None:
                winner.status = "PERSIST_UNKNOWN"
                winner.safe_error_code = "ENHANCEMENT_RESULT_PERSIST_UNKNOWN"
                self.session.commit()
            raise AppError("Enhancement result persistence is uncertain", 500) from None
        self.session.refresh(artifact)
        return artifact

    @staticmethod
    def _apply_media(artifact, media: EnhancementMedia) -> None:
        artifact.duration_ms = media.duration_ms
        artifact.width = media.width
        artifact.height = media.height
        artifact.fps_numerator = media.fps_numerator
        artifact.fps_denominator = media.fps_denominator
        artifact.video_codec = media.video_codec
        artifact.video_profile = media.video_profile
        artifact.pixel_format = media.pixel_format
        artifact.audio_codec = media.audio_codec
        artifact.audio_profile = media.audio_profile
        artifact.audio_sample_rate = media.audio_sample_rate
        artifact.audio_channels = media.audio_channels
        artifact.container = media.container
        artifact.measured_lufs_milli = media.measured_lufs_milli
        artifact.measured_true_peak_millidb = media.measured_true_peak_millidb
        artifact.audio_video_sync_offset_ms = media.audio_video_sync_offset_ms
        artifact.longest_black_segment_ms = media.longest_black_segment_ms

    def _fail(self, enhancement: VideoCompositionEnhancement, code: str) -> None:
        enhancement.status = "FAILED"
        enhancement.safe_error_code = code[:100]
        enhancement.completed_at = datetime.now(UTC)
        self.session.commit()


class VideoCompositionEnhancementArtifactAccessService:
    def __init__(self, session: Session, settings) -> None:
        self.repository = VideoCompositionEnhancementRepository(session)
        self.assets = VideoCompositionAssetStorage(
            Path(settings.video_artifact_storage_root or ""),
            settings.video_artifact_max_bytes,
        )

    def resolve_video(self, artifact_id: int):
        artifact = self.repository.get_artifact(artifact_id)
        if artifact is None or artifact.enhancement.status != "SUCCEEDED":
            raise AppError("Enhanced composition artifact not found", 404)
        return artifact, self.assets.resolve_exact(
            artifact.storage_path, artifact.size_bytes, artifact.sha256, ".mp4"
        )

    def resolve_subtitle(self, artifact_id: int):
        artifact = self.repository.get_subtitle(artifact_id)
        if artifact is None or artifact.enhancement.status != "SUCCEEDED":
            raise AppError("Composition subtitle artifact not found", 404)
        return artifact, self.assets.resolve_exact(
            artifact.storage_path, artifact.size_bytes, artifact.sha256, ".vtt"
        )
