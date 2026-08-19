from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.execution.contracts import ExecutionContext, HandlerResult
from app.providers.wanx_image_provider import (
    WanxImageExplicitFailure,
    WanxImageSubmissionUnknown,
)
from app.services.wanx_product_image_service import (
    WANX_PRODUCT_IMAGE_GENERATE_V1,
    WanxProductImageService,
)


class WanxProductImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    product_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    script_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scene_id: int = Field(gt=0)
    scene_sequence: int = Field(ge=1, le=12)
    prompt: str = Field(min_length=1, max_length=5000)
    model: str
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WanxProductImageGenerateV1Handler:
    job_type = WANX_PRODUCT_IMAGE_GENERATE_V1
    input_schema = WanxProductImageInput

    def __init__(
        self, *, session_factory, settings: Settings, provider_factory
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.provider_factory = provider_factory

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = WanxProductImageInput.model_validate(payload)
        context.before_provider_call(may_submit_external=True)
        try:
            generated = self.provider_factory(self.settings).generate(data.prompt)
        except WanxImageSubmissionUnknown:
            return HandlerResult.submit_unknown(
                "WANX_IMAGE_RESULT_UNKNOWN", provider_name="wanx"
            )
        except WanxImageExplicitFailure:
            return HandlerResult.failed(
                "WANX_IMAGE_FAILED", provider_submission_state="EXPLICIT_FAILURE"
            )
        try:
            with self.session_factory() as session:
                artifact = WanxProductImageService(session, self.settings).persist(
                    data.product_id, generated.content
                )
        except Exception:
            return HandlerResult.failed(
                "WANX_IMAGE_PERSIST_FAILED",
                provider_submission_state="RESPONSE_RECEIVED",
            )
        return HandlerResult.succeeded(
            provider_name="wanx",
            provider_operation_id=generated.request_id_digest,
            result_entity_type="product_asset",
            result_entity_id=artifact.id,
            provider_submission_state="RESPONSE_RECEIVED",
        )
