from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import ProductVideoProductionBatch, ProductVideoProductionItem
from app.models.product import utc_now
from app.schemas.product_marketing_video import (
    ProductVideoProductionBatchRead,
    ProductVideoProductionCreateRead,
    ProductVideoProductionCreateRequest,
    ProductVideoProductionItemRead,
    ThreePlatformVideoPreflightRequest,
)
from app.services.three_platform_video_preflight import (
    ThreePlatformVideoPreflightService,
)


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

    def pause(self, product_id: int, batch_id: int) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status in {"WAITING", "RUNNING"}:
            batch.status = "PAUSED"
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def resume(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status == "PAUSED":
            batch.status = (
                "RUNNING"
                if any(item.status == "RUNNING" for item in batch.items)
                else "WAITING"
            )
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
            for item in batch.items:
                if item.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    item.status = "CANCELLED"
                    item.completed_at = now
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

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
