from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.repositories.video_composition_enhancement import (
    VideoCompositionEnhancementRepository,
)
from app.services.video_composition_enhancement_service import (
    VideoCompositionEnhancementService,
)

VIDEO_COMPOSITION_ENHANCE_V1 = "video.composition.enhance.v1"


class VideoCompositionEnhanceV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enhancement_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    composition_id: int = Field(gt=0)
    source_artifact_id: int = Field(gt=0)
    voiceover_artifact_id: int = Field(gt=0)
    music_artifact_id: int | None = Field(default=None, gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_source_chain_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class VideoCompositionEnhanceV1Handler:
    job_type = VIDEO_COMPOSITION_ENHANCE_V1
    input_schema = VideoCompositionEnhanceV1Input

    def __init__(self, *, session_factory, settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = VideoCompositionEnhanceV1Input.model_validate(payload)
        context.checkpoint()
        with self.session_factory() as session:
            enhancement = VideoCompositionEnhancementRepository(session).get(
                data.enhancement_id
            )
            if (
                enhancement is None
                or enhancement.product_id != data.product_id
                or enhancement.video_project_id != data.video_project_id
                or enhancement.composition_id != data.composition_id
                or enhancement.source_artifact_id != data.source_artifact_id
                or enhancement.voiceover_artifact_id != data.voiceover_artifact_id
                or enhancement.music_artifact_id != data.music_artifact_id
                or enhancement.input_digest != data.frozen_input_digest
                or enhancement.source_chain_digest != data.frozen_source_chain_digest
            ):
                return HandlerResult.failed("ENHANCEMENT_FROZEN_IDENTITY_MISMATCH")
            try:
                artifact = VideoCompositionEnhancementService(
                    session, self.settings
                ).enhance(
                    enhancement.id,
                    before_persist=context.before_irreversible_local_persist,
                )
            except AppError:
                refreshed = VideoCompositionEnhancementRepository(session).get(
                    enhancement.id
                )
                if refreshed is not None and refreshed.status == "PERSIST_UNKNOWN":
                    return HandlerResult.submit_unknown(
                        "ENHANCEMENT_RESULT_PERSIST_UNKNOWN",
                        provider_name="local_ffmpeg",
                    )
                return HandlerResult.failed("ENHANCEMENT_RENDER_FAILED")
            except Exception:
                return HandlerResult.failed("ENHANCEMENT_RENDER_FAILED")
            return HandlerResult.succeeded(
                provider_name="local_ffmpeg",
                result_entity_type="video_composition_enhancement_artifact",
                result_entity_id=artifact.id,
            )
