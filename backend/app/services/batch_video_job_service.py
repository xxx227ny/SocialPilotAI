from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.execution.handlers.batch_video_variant import (
    BATCH_VIDEO_VARIANT_PREPARE_V1,
    BatchVideoVariantPrepareV1Input,
)
from app.models import BatchVideoJob, BatchVideoVariant, ExecutionJob
from app.models.product import utc_now
from app.repositories.batch_video import BatchVideoRepository
from app.schemas.batch_video import (
    BatchVideoCreateRead,
    BatchVideoCreateRequest,
    BatchVideoJobRead,
    BatchVideoVariantRead,
)
from app.services.batch_video_preflight import BatchVideoPreflightService


def _variant_status(variant: BatchVideoVariant) -> str:
    job = variant.execution_job
    if job is None:
        return variant.status
    return {
        "QUEUED": "WAITING",
        "PAUSED": "PAUSED",
        "RUNNING": "RUNNING",
        "SUCCEEDED": "READY_FOR_SCRIPT",
        "FAILED": "FAILED",
        "SUBMIT_UNKNOWN": "FAILED",
        "CANCELLED": "CANCELLED",
    }[job.status]


def aggregate_batch_status(variants: list[BatchVideoVariant]) -> str:
    statuses = [_variant_status(item) for item in variants]
    if not statuses:
        return "WAITING"
    if all(value == "WAITING" for value in statuses):
        return "WAITING"
    if all(value == "READY_FOR_SCRIPT" for value in statuses):
        return "READY_FOR_SCRIPT"
    if all(value == "FAILED" for value in statuses):
        return "FAILED"
    if all(value == "CANCELLED" for value in statuses):
        return "CANCELLED"
    if any(value == "RUNNING" for value in statuses):
        return "RUNNING"
    if any(value == "FAILED" for value in statuses):
        return "PARTIAL_FAILED"
    if all(value in {"READY_FOR_SCRIPT", "FAILED", "CANCELLED"} for value in statuses):
        return "MIXED_TERMINAL"
    if any(value == "PAUSED" for value in statuses):
        return "PAUSED"
    return "RUNNING"


class BatchVideoJobService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BatchVideoRepository(session)

    def create(self, data: BatchVideoCreateRequest) -> BatchVideoCreateRead:
        existing = self.repository.get_by_idempotency(data.idempotency_key)
        if existing is not None:
            if existing.request_digest != data.request_digest:
                raise AppError("Idempotency key was used for different input", 409)
            return self._create_read(existing.id, reused=True)
        digest_match = self.repository.get_by_digest(data.request_digest)
        if digest_match is not None:
            return self._create_read(digest_match.id, reused=True)
        expiry = data.preflight_expires_at.astimezone(UTC)
        if expiry <= datetime.now(UTC):
            raise AppError("Batch video Preflight has expired", 409)
        checked = BatchVideoPreflightService(self.session).run(data, expires_at=expiry)
        if (
            checked.request_digest != data.request_digest
            or checked.preflight_digest != data.preflight_digest
        ):
            raise AppError("Batch video frozen Preflight mismatch", 409)
        batch = BatchVideoJob(
            request_digest=checked.request_digest,
            idempotency_key=data.idempotency_key,
            status="WAITING",
            priority=data.priority,
            variant_count=checked.variant_count,
            max_concurrency=data.max_concurrency,
            current_stage_cost=Decimal("0"),
            currency="USD",
            cost_scope="orchestration_only",
            downstream_provider_cost_status="NOT_ESTIMATED",
            cost_confirmed=data.cost_confirmed,
            frozen_constraints_json={
                "contract_version": checked.contract_version,
                "product_ids": sorted(data.product_ids),
                "platforms": sorted(data.platforms),
                "variants_per_platform": data.variants_per_platform,
                "duration_seconds": data.duration_seconds,
                "aspect_ratio": data.aspect_ratio,
                "language": data.language,
                "creative_angle": data.creative_angle,
            },
        )
        try:
            self.session.add(batch)
            self.session.flush()
            variants: list[BatchVideoVariant] = []
            for ordinal, plan in enumerate(checked.variants):
                variant = BatchVideoVariant(
                    batch_video_job_id=batch.id,
                    product_id=plan.product_id,
                    platform=plan.platform,
                    variant_index=plan.variant_index,
                    duration_seconds=data.duration_seconds,
                    aspect_ratio=data.aspect_ratio,
                    language=data.language,
                    creative_angle=data.creative_angle,
                    brand_kit_version_id=plan.brand_kit_version_id,
                    brand_kit_version_digest=plan.brand_kit_version_digest,
                    source_digest=plan.source_digest,
                    idempotency_key=(
                        f"batch-variant:{batch.request_digest}:{plan.source_digest}"
                    ),
                    status="WAITING",
                )
                self.session.add(variant)
                self.session.flush()
                payload = BatchVideoVariantPrepareV1Input(
                    variant_id=variant.id, source_digest=variant.source_digest
                )
                job = ExecutionJob(
                    job_type=BATCH_VIDEO_VARIANT_PREPARE_V1,
                    source_type="batch_video_variant",
                    source_id=variant.id,
                    input_digest=variant.source_digest,
                    idempotency_key=(
                        f"batch-prepare:{batch.request_digest}:{variant.source_digest}"
                    ),
                    input_payload=payload.model_dump(mode="json"),
                    priority=batch.priority,
                    concurrency_key=(
                        f"video-batch:{batch.id}:slot:{ordinal % batch.max_concurrency}"
                    ),
                    estimated_cost=Decimal("0"),
                    currency="USD",
                    cost_confirmed=True,
                    max_attempts=1,
                    status="QUEUED",
                )
                self.session.add(job)
                self.session.flush()
                variant.execution_job_id = job.id
                variants.append(variant)
            self.session.commit()
        except (IntegrityError, OperationalError):
            self.session.rollback()
            concurrent = self.repository.get_by_idempotency(data.idempotency_key)
            if concurrent is None:
                concurrent = self.repository.get_by_digest(data.request_digest)
            if concurrent is None:
                raise
            if concurrent.request_digest != data.request_digest:
                raise AppError(
                    "Idempotency key was used for different input", 409
                ) from None
            return self._create_read(concurrent.id, reused=True)
        except Exception:
            self.session.rollback()
            raise
        return self._create_read(batch.id, reused=False)

    def get_batch(self, batch_id: int) -> BatchVideoJobRead:
        batch = self._required_batch(batch_id)
        return BatchVideoJobRead.model_validate(batch).model_copy(
            update={"status": aggregate_batch_status(batch.variants)}
        )

    def list_variants(self, batch_id: int) -> list[BatchVideoVariantRead]:
        self._required_batch(batch_id)
        return [
            self._variant_read(item) for item in self.repository.list_variants(batch_id)
        ]

    def get_variant(self, variant_id: int) -> BatchVideoVariantRead:
        variant = self.repository.get_variant(variant_id)
        if variant is None:
            raise AppError("Batch video resource not found", 404)
        return self._variant_read(variant)

    def pause(self, batch_id: int) -> BatchVideoJobRead:
        return self._control(batch_id, "pause")

    def resume(self, batch_id: int) -> BatchVideoJobRead:
        return self._control(batch_id, "resume")

    def cancel(self, batch_id: int) -> BatchVideoJobRead:
        return self._control(batch_id, "cancel")

    def _control(self, batch_id: int, action: str) -> BatchVideoJobRead:
        batch = self._required_batch(batch_id)
        now = utc_now()
        for variant in batch.variants:
            job = variant.execution_job
            if job is None:
                raise AppError("Batch video queue record is incomplete", 409)
            if action == "pause" and job.status == "QUEUED":
                job.status = "PAUSED"
                variant.status = "PAUSED"
            elif action == "resume" and job.status == "PAUSED":
                job.status = "QUEUED"
                variant.status = "WAITING"
            elif action == "cancel" and job.status in {"QUEUED", "PAUSED"}:
                job.status = "CANCELLED"
                job.completed_at = now
                variant.status = "CANCELLED"
                variant.completed_at = now
        self.session.commit()
        return self.get_batch(batch_id)

    def _required_batch(self, batch_id: int) -> BatchVideoJob:
        batch = self.repository.get_batch(batch_id)
        if batch is None:
            raise AppError("Batch video resource not found", 404)
        return batch

    def _create_read(self, batch_id: int, *, reused: bool) -> BatchVideoCreateRead:
        return BatchVideoCreateRead(
            batch=self.get_batch(batch_id),
            variants=self.list_variants(batch_id),
            reused=reused,
        )

    @staticmethod
    def _variant_read(variant: BatchVideoVariant) -> BatchVideoVariantRead:
        return BatchVideoVariantRead.model_validate(variant).model_copy(
            update={"status": _variant_status(variant)}
        )
