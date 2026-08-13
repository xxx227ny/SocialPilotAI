from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.repositories.video_composition import VideoCompositionRepository
from app.services.video_composition_service import VideoCompositionService

VIDEO_COMPOSITION_RENDER_V1 = "video.composition.render.v1"


class VideoCompositionRenderV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    video_project_id: int = Field(gt=0)
    frozen_input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_source_chain_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class VideoCompositionRenderV1Handler:
    job_type = VIDEO_COMPOSITION_RENDER_V1
    input_schema = VideoCompositionRenderV1Input

    def __init__(self, *, session_factory, settings: Settings) -> None:
        self.session_factory = session_factory
        self.settings = settings

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = VideoCompositionRenderV1Input.model_validate(payload)
        context.checkpoint()
        with self.session_factory() as session:
            composition = VideoCompositionRepository(session).get(data.composition_id)
            if (
                composition is None
                or composition.product_id != data.product_id
                or composition.video_project_id != data.video_project_id
                or composition.input_digest != data.frozen_input_digest
                or composition.source_chain_digest != data.frozen_source_chain_digest
            ):
                return HandlerResult.failed("COMPOSITION_FROZEN_IDENTITY_MISMATCH")
            try:
                artifact = VideoCompositionService(session, self.settings).render(
                    composition.id
                )
            except AppError:
                refreshed = VideoCompositionRepository(session).get(composition.id)
                if refreshed is not None and refreshed.status == "PERSIST_UNKNOWN":
                    return HandlerResult.submit_unknown(
                        "COMPOSITION_RESULT_PERSIST_UNKNOWN",
                        provider_name="local_ffmpeg",
                    )
                return HandlerResult.failed("COMPOSITION_RENDER_FAILED")
            except Exception:
                return HandlerResult.failed("COMPOSITION_RENDER_FAILED")
            return HandlerResult.succeeded(
                provider_name="local_ffmpeg",
                result_entity_type="video_composition_artifact",
                result_entity_id=artifact.id,
            )
