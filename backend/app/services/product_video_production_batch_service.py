from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import (
    ExecutionJob,
    ProductAsset,
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoScriptVersion,
)
from app.models.product import utc_now
from app.schemas.product_marketing_video import (
    ProductVideoProductionBatchRead,
    ProductVideoProductionCreateRead,
    ProductVideoProductionCreateRequest,
    ProductVideoProductionItemRead,
    ThreePlatformVideoPreflightRequest,
    WanxProductImageSubmitRequest,
)
from app.services.three_platform_video_preflight import (
    ThreePlatformVideoPreflightService,
)
from app.services.wanx_product_image_service import WanxProductImageService


class ProductVideoProductionBatchService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create(
        self, product_id: int, data: ProductVideoProductionCreateRequest
    ) -> ProductVideoProductionCreateRead:
        existing = self._by_idempotency(data.idempotency_key)
        if existing is not None:
            if (
                existing.product_id != product_id
                or existing.input_digest != data.input_digest
            ):
                raise AppError("Idempotency key was used for different input", 409)
            return self._create_read(existing, reused=True)

        checked = ThreePlatformVideoPreflightService(self.session, self.settings).run(
            product_id,
            ThreePlatformVideoPreflightRequest(
                reference_product_asset_id=data.reference_product_asset_id,
                reference_product_asset_sha256=(data.reference_product_asset_sha256),
                selections=data.selections,
            ),
        )
        if checked.input_digest != data.input_digest:
            raise AppError("Three-platform frozen Preflight mismatch", 409)
        if not checked.ready:
            raise AppError("Three-platform production is not ready", 409)

        batch = ProductVideoProductionBatch(
            product_id=product_id,
            reference_product_asset_id=data.reference_product_asset_id,
            reference_product_asset_sha256=data.reference_product_asset_sha256,
            input_digest=checked.input_digest,
            idempotency_key=data.idempotency_key,
            status="WAITING",
            known_estimated_cost=checked.known_estimated_cost,
            currency=checked.currency,
            cost_estimate_complete=checked.cost_estimate_complete,
            cost_confirmed=data.cost_confirmed,
            provider_call_budget=checked.provider_call_count,
            frozen_preflight_json=checked.model_dump(mode="json"),
        )
        try:
            self.session.add(batch)
            self.session.flush()
            for platform in checked.platforms:
                self.session.add(
                    ProductVideoProductionItem(
                        production_batch_id=batch.id,
                        batch_video_variant_id=platform.variant_id,
                        script_version_id=platform.script_version_id,
                        platform=platform.platform,
                        status="WAITING",
                        stage="QUEUED",
                        stage_state_json={
                            "scene_count": platform.scene_count,
                            "wanx_image_generation_calls": (
                                platform.wanx_image_generation_calls
                            ),
                            "happyhorse_generation_calls": (
                                platform.happyhorse_generation_calls
                            ),
                            "qwen_tts_generation_calls": (
                                platform.qwen_tts_generation_calls
                            ),
                        },
                    )
                )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._by_idempotency(data.idempotency_key)
            if concurrent is None:
                raise
            if (
                concurrent.product_id != product_id
                or concurrent.input_digest != data.input_digest
            ):
                raise AppError(
                    "Idempotency key was used for different input", 409
                ) from None
            return self._create_read(concurrent, reused=True)
        return self._create_read(self._required(product_id, batch.id), reused=False)

    def get(self, product_id: int, batch_id: int) -> ProductVideoProductionCreateRead:
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def advance(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status == "PAUSED":
            raise AppError("Product video production batch is paused", 409)
        if batch.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return self._create_read(batch, reused=True)

        for item in batch.items:
            if item.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                continue
            if item.stage == "QUEUED":
                self._enqueue_wanx_images(batch, item)
            elif item.stage == "GENERATING_IMAGES":
                self._refresh_wanx_images(batch, item)
        self._sync_batch_status(batch)
        self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def pause(self, product_id: int, batch_id: int) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status in {"WAITING", "RUNNING"}:
            batch.status = "PAUSED"
            for job in self._execution_jobs(batch):
                if job.status == "QUEUED":
                    job.status = "PAUSED"
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def resume(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status == "PAUSED":
            for job in self._execution_jobs(batch):
                if job.status == "PAUSED":
                    job.status = "QUEUED"
            batch.status = "WAITING"
            self._sync_batch_status(batch)
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def cancel(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            now = utc_now()
            batch.status = "CANCELLED"
            batch.completed_at = now
            for job in self._execution_jobs(batch):
                if job.status in {"QUEUED", "PAUSED"}:
                    job.status = "CANCELLED"
                    job.completed_at = now
            for item in batch.items:
                if item.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    item.status = "CANCELLED"
                    item.completed_at = now
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def _enqueue_wanx_images(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        version = self.session.get(VideoScriptVersion, item.script_version_id)
        if (
            version is None
            or version.product_id != batch.product_id
            or version.batch_video_variant_id != item.batch_video_variant_id
            or version.platform != item.platform
            or not version.scenes
        ):
            self._fail_item(item, "PRODUCTION_SCRIPT_IDENTITY_INVALID")
            return
        service = WanxProductImageService(self.session, self.settings)
        job_ids: list[int] = []
        for scene in version.scenes:
            submitted = service.enqueue(
                batch.product_id,
                WanxProductImageSubmitRequest(
                    script_version_id=version.id,
                    scene_sequence=scene.sequence,
                    reference_product_asset_id=batch.reference_product_asset_id,
                    reference_product_asset_sha256=(
                        batch.reference_product_asset_sha256
                    ),
                    idempotency_key=(
                        f"production:{batch.id}:item:{item.id}:wanx:{scene.sequence}"
                    ),
                    cost_confirmed=True,
                ),
            )
            job_ids.append(submitted.job.id)
        item.stage_state_json = {
            **item.stage_state_json,
            "wanx_job_ids": job_ids,
            "wanx_product_asset_ids": [],
        }
        item.status = "RUNNING"
        item.stage = "GENERATING_IMAGES"

    def _refresh_wanx_images(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        job_ids = item.stage_state_json.get("wanx_job_ids")
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or not all(isinstance(job_id, int) and job_id > 0 for job_id in job_ids)
        ):
            self._fail_item(item, "PRODUCTION_WANX_JOB_IDENTITY_INVALID")
            return
        jobs = list(
            self.session.scalars(
                select(ExecutionJob)
                .where(ExecutionJob.id.in_(job_ids))
                .order_by(ExecutionJob.id)
            ).all()
        )
        if len(jobs) != len(job_ids):
            self._fail_item(item, "PRODUCTION_WANX_JOB_IDENTITY_INVALID")
            return
        if any(job.status == "SUBMIT_UNKNOWN" for job in jobs):
            self._fail_item(item, "PRODUCTION_WANX_SUBMIT_UNKNOWN")
            return
        if any(job.status in {"FAILED", "CANCELLED"} for job in jobs):
            self._fail_item(item, "PRODUCTION_WANX_IMAGE_FAILED")
            return
        if not all(job.status == "SUCCEEDED" for job in jobs):
            return

        asset_ids: list[int] = []
        for job in jobs:
            asset = (
                self.session.get(ProductAsset, job.result_entity_id)
                if job.result_entity_type == "product_asset"
                and job.result_entity_id is not None
                else None
            )
            if (
                asset is None
                or asset.product_id != batch.product_id
                or not asset.sha256
            ):
                self._fail_item(item, "PRODUCTION_WANX_RESULT_INVALID")
                return
            asset_ids.append(asset.id)
        item.stage_state_json = {
            **item.stage_state_json,
            "wanx_product_asset_ids": asset_ids,
        }
        item.stage = "PREPARING_VIDEO"

    @staticmethod
    def _fail_item(item: ProductVideoProductionItem, code: str) -> None:
        item.status = "FAILED"
        item.safe_error_code = code
        item.completed_at = utc_now()

    def _execution_jobs(self, batch: ProductVideoProductionBatch) -> list[ExecutionJob]:
        ids: set[int] = set()
        for item in batch.items:
            for key, value in item.stage_state_json.items():
                if key.endswith("_job_id") and isinstance(value, int):
                    ids.add(value)
                elif key.endswith("_job_ids") and isinstance(value, list):
                    ids.update(
                        job_id
                        for job_id in value
                        if isinstance(job_id, int) and job_id > 0
                    )
        if not ids:
            return []
        return list(
            self.session.scalars(
                select(ExecutionJob).where(ExecutionJob.id.in_(ids))
            ).all()
        )

    @staticmethod
    def _sync_batch_status(batch: ProductVideoProductionBatch) -> None:
        if batch.status in {"PAUSED", "CANCELLED"}:
            return
        statuses = [item.status for item in batch.items]
        if statuses and all(status == "SUCCEEDED" for status in statuses):
            batch.status = "SUCCEEDED"
            batch.completed_at = utc_now()
        elif statuses and all(status == "FAILED" for status in statuses):
            batch.status = "FAILED"
            batch.completed_at = utc_now()
        elif any(status == "FAILED" for status in statuses):
            batch.status = "PARTIAL_FAILED"
        elif statuses and all(status == "CANCELLED" for status in statuses):
            batch.status = "CANCELLED"
            batch.completed_at = utc_now()
        elif any(status == "RUNNING" for status in statuses):
            batch.status = "RUNNING"
        else:
            batch.status = "WAITING"

    def _by_idempotency(self, key: str) -> ProductVideoProductionBatch | None:
        return self.session.scalar(
            select(ProductVideoProductionBatch)
            .options(selectinload(ProductVideoProductionBatch.items))
            .where(ProductVideoProductionBatch.idempotency_key == key)
        )

    def _required(self, product_id: int, batch_id: int) -> ProductVideoProductionBatch:
        batch = self.session.scalar(
            select(ProductVideoProductionBatch)
            .options(selectinload(ProductVideoProductionBatch.items))
            .where(
                ProductVideoProductionBatch.id == batch_id,
                ProductVideoProductionBatch.product_id == product_id,
            )
        )
        if batch is None:
            raise AppError("Product video production batch was not found", 404)
        return batch

    @staticmethod
    def _create_read(
        batch: ProductVideoProductionBatch, *, reused: bool
    ) -> ProductVideoProductionCreateRead:
        return ProductVideoProductionCreateRead(
            batch=ProductVideoProductionBatchRead.model_validate(batch),
            items=[
                ProductVideoProductionItemRead.model_validate(item)
                for item in batch.items
            ],
            reused=reused,
        )
