from pydantic import BaseModel, ConfigDict, Field

from app.execution.contracts import ExecutionContext, HandlerResult
from app.models import BrandKitVersion, Product
from app.repositories.batch_video import BatchVideoRepository
from app.services.batch_video_preflight import stable_digest, variant_source_payload

BATCH_VIDEO_VARIANT_PREPARE_V1 = "video.batch.variant.prepare.v1"


class BatchVideoVariantPrepareV1Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: int = Field(gt=0)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class BatchVideoVariantPrepareV1Handler:
    job_type = BATCH_VIDEO_VARIANT_PREPARE_V1
    input_schema = BatchVideoVariantPrepareV1Input

    def __init__(self, *, session_factory) -> None:
        self.session_factory = session_factory

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = BatchVideoVariantPrepareV1Input.model_validate(payload)
        context.checkpoint()
        with self.session_factory() as session:
            variant = BatchVideoRepository(session).get_variant(data.variant_id)
            if variant is None or variant.source_digest != data.source_digest:
                return HandlerResult.failed("BATCH_VARIANT_IDENTITY_MISMATCH")
            product = session.get(Product, variant.product_id)
            if product is None:
                return HandlerResult.failed("BATCH_VARIANT_PRODUCT_MISSING")
            if variant.brand_kit_version_id is not None:
                brand = session.get(BrandKitVersion, variant.brand_kit_version_id)
                if brand is None or brand.digest != variant.brand_kit_version_digest:
                    return HandlerResult.failed("BATCH_VARIANT_BRAND_MISMATCH")
            actual = stable_digest(
                variant_source_payload(
                    product_id=variant.product_id,
                    platform=variant.platform,
                    variant_index=variant.variant_index,
                    duration_seconds=variant.duration_seconds,
                    aspect_ratio=variant.aspect_ratio,
                    language=variant.language,
                    creative_angle=variant.creative_angle,
                    brand_kit_version_id=variant.brand_kit_version_id,
                    brand_kit_version_digest=variant.brand_kit_version_digest,
                )
            )
            if actual != variant.source_digest:
                return HandlerResult.failed("BATCH_VARIANT_SOURCE_MISMATCH")
            variant.status = "READY_FOR_SCRIPT"
            variant.result_entity_type = "batch_video_variant"
            variant.result_entity_id = variant.id
            variant.completed_at = variant.updated_at
            session.commit()
            return HandlerResult.succeeded(
                provider_name="local_batch_orchestrator",
                result_entity_type="batch_video_variant",
                result_entity_id=variant.id,
            )
