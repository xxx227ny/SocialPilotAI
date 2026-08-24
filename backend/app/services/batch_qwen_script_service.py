from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import BatchVideoJob, BatchVideoVariant, VideoScriptVersion
from app.schemas.batch_video import (
    BatchQwenScriptCreateRead,
    BatchQwenScriptCreateRequest,
    BatchQwenScriptItemRead,
    BatchQwenScriptPreflightRead,
    BatchQwenScriptRequest,
)
from app.schemas.execution import ExecutionJobRead
from app.schemas.video_script_version import (
    QwenScriptJobCreateRequest,
    QwenScriptPreflightRead,
    QwenScriptPreflightRequest,
)
from app.services.qwen_video_script_generation_service import (
    TIMED_FOUR_ACT_SCENE_COUNT,
)
from app.services.qwen_video_script_job_service import QwenVideoScriptJobService
from app.services.qwen_video_script_preflight import QwenVideoScriptPreflightService
from app.services.video_script_version_service import VideoScriptVersionService

PLATFORMS = ("tiktok", "youtube", "instagram")


class BatchQwenScriptService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def preflight(
        self,
        batch_id: int,
        data: BatchQwenScriptRequest,
        *,
        expires_at: datetime | None = None,
    ) -> BatchQwenScriptPreflightRead:
        variants = self._variants(batch_id, data)
        expiry = expires_at
        items = []
        for variant in variants:
            request = self._request(batch_id, variant.id, data)
            checked = QwenVideoScriptPreflightService(self.session, self.settings).run(
                variant.id, request, expires_at=expiry
            )
            expiry = checked.expires_at
            items.append(checked)
        currencies = {item.currency for item in items}
        bases = {item.cost_estimate_basis for item in items}
        if len(currencies) != 1 or len(bases) != 1 or None in bases:
            raise AppError("Batch Qwen script cost policy is inconsistent", 409)
        material = {
            "contract": "batch-qwen-script-preflight-v1",
            "batch_id": batch_id,
            "product_id": data.product_id,
            "variant_ids": [item.variant_id for item in items],
            "strategy_id": data.strategy_id,
            "copy_matrix_id": data.copy_matrix_id,
            "items": [
                {
                    "variant_id": item.variant_id,
                    "frozen_input_digest": item.frozen_input_digest,
                    "preflight_digest": item.preflight_digest,
                    "estimated_cost_min": str(item.estimated_cost_min),
                    "estimated_cost_max": str(item.estimated_cost_max),
                }
                for item in items
            ],
            "expires_at": expiry.isoformat(),
        }
        digest = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        qwen_cost_min = sum(
            (item.estimated_cost_min or Decimal("0") for item in items),
            Decimal("0"),
        )
        qwen_cost_max = sum(
            (item.estimated_cost_max or Decimal("0") for item in items),
            Decimal("0"),
        )
        wanx_calls = len(items) * TIMED_FOUR_ACT_SCENE_COUNT
        downstream_cost = (
            self.settings.wanx_image_estimated_cost * wanx_calls
            + self.settings.happyhorse_estimated_cost * len(items)
        )
        return BatchQwenScriptPreflightRead(
            **data.model_dump(),
            batch_id=batch_id,
            items=items,
            preflight_digest=digest,
            expires_at=expiry,
            ready_for_execution=all(item.ready_for_execution for item in items),
            estimated_provider_calls=len(items),
            estimated_cost_min=qwen_cost_min,
            estimated_cost_max=qwen_cost_max,
            wanx_image_generation_calls=wanx_calls,
            happyhorse_generation_calls=len(items),
            qwen_tts_generation_calls=len(items),
            known_downstream_cost=downstream_cost,
            total_known_cost_min=qwen_cost_min + downstream_cost,
            total_known_cost_max=qwen_cost_max + downstream_cost,
            currency=currencies.pop(),
            cost_estimate_basis=bases.pop(),
        )

    def create_or_recover(
        self, batch_id: int, data: BatchQwenScriptCreateRequest
    ) -> BatchQwenScriptCreateRead:
        checked = self.preflight(
            batch_id,
            self._base_request(data),
            expires_at=data.preflight_expires_at,
        )
        if checked.preflight_digest != data.preflight_digest:
            raise AppError("Batch Qwen script Preflight changed", 409)
        items: list[BatchQwenScriptItemRead] = []
        for item in checked.items:
            request = self._request_from_checked(batch_id, data, item)
            created = QwenVideoScriptJobService(self.session, self.settings).enqueue(
                item.variant_id, request
            )
            job = created.job
            version_id = None
            active = False
            if job.status == "SUCCEEDED":
                version_id = self._result_version(item.variant_id, job)
                activation = VideoScriptVersionService(self.session).activate(
                    item.variant_id, version_id
                )
                active = activation.active_script_version_id == version_id
            status = self._item_status(job.status, active)
            items.append(
                BatchQwenScriptItemRead(
                    variant_id=item.variant_id,
                    platform=item.platform,
                    status=status,
                    job=job,
                    script_version_id=version_id,
                    active=active,
                    safe_error_code=job.safe_error_code,
                )
            )
        return BatchQwenScriptCreateRead(
            batch_id=batch_id,
            status=self._aggregate(items),
            items=items,
        )

    def _variants(
        self, batch_id: int, data: BatchQwenScriptRequest
    ) -> list[BatchVideoVariant]:
        batch = self.session.get(BatchVideoJob, batch_id)
        if batch is None:
            raise AppError("Batch Qwen script resource was not found", 404)
        if len(set(data.variant_ids)) != 3:
            raise AppError("Batch Qwen script Variants must be unique", 422)
        variants = [
            self.session.get(BatchVideoVariant, item) for item in data.variant_ids
        ]
        if any(item is None for item in variants):
            raise AppError("Batch Qwen script resource was not found", 404)
        exact = [item for item in variants if item is not None]
        if any(
            item.batch_video_job_id != batch.id
            or item.product_id != data.product_id
            or item.status != "READY_FOR_SCRIPT"
            for item in exact
        ):
            raise AppError("Batch Qwen script source identity is invalid", 409)
        if {item.platform for item in exact} != set(PLATFORMS):
            raise AppError("Batch Qwen script requires the three target platforms", 422)
        return sorted(exact, key=lambda item: PLATFORMS.index(item.platform))

    @staticmethod
    def _request(
        batch_id: int,
        variant_id: int,
        data: BatchQwenScriptRequest,
    ) -> QwenScriptPreflightRequest:
        return QwenScriptPreflightRequest(
            idempotency_key=(
                f"batch-script:{batch_id}:{variant_id}:{data.strategy_id}:"
                f"{data.copy_matrix_id or 0}"
            ),
            strategy_id=data.strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            parent_version_id=None,
        )

    @classmethod
    def _request_from_checked(
        cls,
        batch_id: int,
        data: BatchQwenScriptCreateRequest,
        item: QwenScriptPreflightRead,
    ) -> QwenScriptJobCreateRequest:
        if (
            item.estimated_cost_min is None
            or item.estimated_cost_max is None
            or item.cost_estimate_basis is None
        ):
            raise AppError("Batch Qwen script cost is unavailable", 409)
        base = cls._request(
            batch_id,
            item.variant_id,
            cls._base_request(data),
        )
        return QwenScriptJobCreateRequest(
            idempotency_key=base.idempotency_key,
            strategy_id=item.strategy_id,
            copy_matrix_id=item.copy_matrix_id,
            parent_version_id=item.parent_version_id,
            frozen_input_digest=item.frozen_input_digest,
            preflight_digest=item.preflight_digest,
            preflight_expires_at=item.expires_at,
            estimated_cost_min=item.estimated_cost_min,
            estimated_cost_max=item.estimated_cost_max,
            currency=item.currency,
            cost_estimate_basis=item.cost_estimate_basis,
            cost_confirmed=True,
        )

    @staticmethod
    def _base_request(data: BatchQwenScriptCreateRequest) -> BatchQwenScriptRequest:
        return BatchQwenScriptRequest.model_validate(
            data.model_dump(
                include={
                    "product_id",
                    "variant_ids",
                    "strategy_id",
                    "copy_matrix_id",
                }
            )
        )

    def _result_version(self, variant_id: int, job: ExecutionJobRead) -> int:
        if job.result_entity_type != "video_script_version" or not job.result_entity_id:
            raise AppError("Batch Qwen script result identity is invalid", 409)
        version = self.session.get(VideoScriptVersion, job.result_entity_id)
        if (
            version is None
            or version.batch_video_variant_id != variant_id
            or version.source_execution_job_id != job.id
            or version.source_type != "QWEN_GENERATED"
            or version.created_by_kind != "QWEN_PROVIDER"
            or version.provider_name != "qwen"
        ):
            raise AppError("Batch Qwen script result identity is invalid", 409)
        return version.id

    @staticmethod
    def _item_status(job_status: str, active: bool) -> str:
        if active:
            return "READY"
        if job_status in {"QUEUED", "PAUSED"}:
            return "QUEUED"
        if job_status == "RUNNING":
            return "RUNNING"
        if job_status == "SUBMIT_UNKNOWN":
            return "SUBMIT_UNKNOWN"
        return "FAILED"

    @staticmethod
    def _aggregate(items: list[BatchQwenScriptItemRead]) -> str:
        statuses = {item.status for item in items}
        if statuses == {"READY"}:
            return "READY"
        if statuses <= {"FAILED", "SUBMIT_UNKNOWN"}:
            return "FAILED"
        if statuses & {"FAILED", "SUBMIT_UNKNOWN"}:
            return "PARTIAL_FAILED"
        return "RUNNING"
