from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.services.product_image_render_service import (
    PRODUCT_IMAGE_RENDER_V1,
    ProductImageRenderService,
)


class ProductImageRenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    asset_id: int = Field(gt=0)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    motion: str = Field(pattern=r"^(zoom_in|zoom_out|pan_left|pan_right)$")


class ProductImageRenderV1Handler:
    job_type = PRODUCT_IMAGE_RENDER_V1
    input_schema = ProductImageRenderInput

    def __init__(self, *, session_factory, settings: Settings) -> None:
        self.session_factory, self.settings = session_factory, settings

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = ProductImageRenderInput.model_validate(payload)
        context.checkpoint()
        try:
            with self.session_factory() as session:
                artifact = ProductImageRenderService(session, self.settings).render(
                    data.task_id, data.asset_id, data.asset_sha256, data.motion
                )
        except AppError:
            return HandlerResult.failed("PRODUCT_IMAGE_RENDER_FAILED")
        return HandlerResult.succeeded(
            provider_name="local_ffmpeg",
            result_entity_type="video_render_artifact",
            result_entity_id=artifact.id,
            provider_submission_state="NOT_SUBMITTED",
        )
