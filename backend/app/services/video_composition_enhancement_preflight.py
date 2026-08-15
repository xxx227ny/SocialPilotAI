from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.repositories.video_composition import VideoCompositionRepository
from app.repositories.video_composition_enhancement import (
    VideoCompositionEnhancementRepository,
)
from app.schemas.video_composition_enhancement import (
    FrozenAudioArtifactRead,
    FrozenEnhancementParametersRead,
    VideoCompositionEnhancementPreflightRead,
    VideoCompositionEnhancementPreflightRequest,
)
from app.services.video_composition_asset_storage import VideoCompositionAssetStorage
from app.services.video_composition_service import VideoCompositionArtifactAccessService


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parameters(data: VideoCompositionEnhancementPreflightRequest):
    return FrozenEnhancementParametersRead(
        voiceover_gain_millidb=round(data.mix.voiceover_gain_db * 1000),
        music_gain_millidb=round(data.mix.music_gain_db * 1000),
        ducking_reduction_millidb=round(data.mix.ducking_reduction_db * 1000),
        target_lufs_milli=round(data.mix.target_lufs * 1000),
        true_peak_millidb=round(data.mix.true_peak_db * 1000),
    )


class VideoCompositionEnhancementPreflightService:
    def __init__(self, session: Session, settings) -> None:
        self.session = session
        self.settings = settings
        self.compositions = VideoCompositionRepository(session)
        self.repository = VideoCompositionEnhancementRepository(session)
        self.assets = VideoCompositionAssetStorage(
            Path(settings.video_artifact_storage_root or ""),
            settings.video_artifact_max_bytes,
        )
        self.video_access = VideoCompositionArtifactAccessService(session, settings)

    def run(
        self,
        product_id: int,
        data: VideoCompositionEnhancementPreflightRequest,
        *,
        expires_at: datetime | None = None,
    ) -> VideoCompositionEnhancementPreflightRead:
        composition = self.compositions.get(data.composition_id)
        if (
            composition is None
            or composition.product_id != product_id
            or composition.status != "SUCCEEDED"
            or composition.artifact is None
            or composition.artifact.id != data.source_artifact_id
        ):
            raise AppError("Composition enhancement source identity is invalid", 409)
        source_artifact, _ = self.video_access.resolve(data.source_artifact_id)
        voiceover = self._audio(
            data.voiceover_artifact_id,
            "voiceover",
            product_id,
            composition.video_project_id,
            composition.id,
        )
        music = (
            self._audio(
                data.music_artifact_id,
                "music",
                product_id,
                composition.video_project_id,
                composition.id,
            )
            if data.music_artifact_id is not None
            else None
        )
        if max(cue.end_ms for cue in data.cues) > voiceover.duration_ms + 34:
            raise AppError("Subtitle timeline exceeds frozen voiceover", 409)
        parameters = _parameters(data)
        cues = sorted(data.cues, key=lambda cue: cue.sequence)
        style = data.style
        source_payload = {
            "contract": "video-composition-enhance-v1",
            "product_id": product_id,
            "video_project_id": composition.video_project_id,
            "composition_id": composition.id,
            "composition_input_digest": composition.input_digest,
            "composition_source_chain_digest": composition.source_chain_digest,
            "source_artifact": {
                "id": source_artifact.id,
                "sha256": source_artifact.sha256,
                "size_bytes": source_artifact.size_bytes,
            },
            "voiceover": voiceover.model_dump(mode="json"),
            "music": music.model_dump(mode="json") if music else None,
        }
        source_chain_digest = _digest(source_payload)
        input_payload = {
            **source_payload,
            "cues": [cue.model_dump(mode="json") for cue in cues],
            "style": style.model_dump(mode="json"),
            "parameters": parameters.model_dump(mode="json"),
        }
        input_digest = _digest(input_payload)
        expiry = (
            expires_at or datetime.now(UTC) + timedelta(minutes=10)
        ).astimezone(UTC)
        preflight_digest = _digest(
            {"input_digest": input_digest, "expires_at": expiry.isoformat()}
        )
        return VideoCompositionEnhancementPreflightRead(
            product_id=product_id,
            video_project_id=composition.video_project_id,
            composition_id=composition.id,
            source_artifact_id=source_artifact.id,
            voiceover_artifact_id=voiceover.id,
            music_artifact_id=music.id if music else None,
            source_artifact_sha256=source_artifact.sha256,
            voiceover=voiceover,
            music=music,
            cues=cues,
            style=style,
            mix=data.mix,
            parameters=parameters,
            input_digest=input_digest,
            source_chain_digest=source_chain_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            ready=True,
            missing_requirements=[],
            execution_notice=(
                "本地 FFmpeg 增强费用为零；将生成真实配音混音、"
                "可选音乐 ducking 与烧录字幕。"
            ),
        )

    def _audio(
        self,
        artifact_id: int,
        expected_kind: str,
        product_id: int,
        video_project_id: int,
        composition_id: int,
    ) -> FrozenAudioArtifactRead:
        artifact = self.repository.get_audio(artifact_id)
        if (
            artifact is None
            or artifact.kind != expected_kind
            or artifact.product_id != product_id
            or artifact.video_project_id != video_project_id
            or artifact.composition_id != composition_id
            or (expected_kind == "voiceover" and artifact.duration_ms > 15000)
        ):
            raise AppError("Composition audio source identity is invalid", 409)
        self.assets.resolve_audio(
            artifact.storage_path,
            artifact.content_type,
            artifact.size_bytes,
            artifact.sha256,
        )
        return FrozenAudioArtifactRead.model_validate(
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "product_id": artifact.product_id,
                "video_project_id": artifact.video_project_id,
                "composition_id": artifact.composition_id,
                "content_type": artifact.content_type,
                "size_bytes": artifact.size_bytes,
                "sha256": artifact.sha256,
                "duration_ms": artifact.duration_ms,
            }
        )
