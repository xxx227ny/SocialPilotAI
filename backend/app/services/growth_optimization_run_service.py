from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import GrowthOptimizationRun
from app.repositories.growth_optimization import GrowthOptimizationRepository
from app.schemas.growth import (
    GrowthOptimizationPolicy,
    GrowthOptimizationRunActivateRead,
    GrowthOptimizationRunCreateRead,
    GrowthOptimizationRunCreateRequest,
    GrowthOptimizationRunRead,
    GrowthPlatformOptimizationAction,
)
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_budget_optimizer import GrowthBudgetOptimizer


class GrowthOptimizationRunService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = GrowthOptimizationRepository(session)

    def create(
        self, product_id: int, data: GrowthOptimizationRunCreateRequest
    ) -> GrowthOptimizationRunCreateRead:
        planned = GrowthBudgetOptimizer(self.session).plan(product_id, data)
        request_digest = self._request_digest(data)
        existing = self.repository.get_by_key(product_id, data.idempotency_key)
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AppError(
                    "Idempotency key is bound to a different optimization plan",
                    status_code=409,
                )
            return GrowthOptimizationRunCreateRead(
                run=self._read(existing),
                reused=True,
                automatic_internal_application=(existing.status == "ACTIVE"),
            )

        now = datetime.now(UTC)
        status = "ACTIVE" if data.activate_internal else "PROPOSED"
        try:
            if status == "ACTIVE":
                self._supersede_active(product_id)
            run = GrowthOptimizationRun(
                product_id=product_id,
                idempotency_key=data.idempotency_key,
                request_digest=request_digest,
                source_context_digest=planned.source_context_digest,
                source_recommendation_digest=planned.source_recommendation_digest,
                policy_json=planned.policy.model_dump(mode="json"),
                actions_json=[item.model_dump(mode="json") for item in planned.actions],
                current_total_spend=Decimal(str(planned.current_total_spend)),
                recommended_total_budget=Decimal(str(planned.recommended_total_budget)),
                status=status,
                execution_scope="INTERNAL_PLAN_ONLY",
                external_execution_status="NOT_CONNECTED",
                activated_at=now if status == "ACTIVE" else None,
            )
            self.session.add(run)
            self.session.commit()
            self.session.refresh(run)
            return GrowthOptimizationRunCreateRead(
                run=self._read(run),
                reused=False,
                automatic_internal_application=(status == "ACTIVE"),
            )
        except IntegrityError as exc:
            self.session.rollback()
            recovered = self.repository.get_by_key(product_id, data.idempotency_key)
            if recovered is None or recovered.request_digest != request_digest:
                raise AppError(
                    "Optimization plan conflict; outcome was not retried",
                    status_code=409,
                ) from exc
            return GrowthOptimizationRunCreateRead(
                run=self._read(recovered),
                reused=True,
                automatic_internal_application=(recovered.status == "ACTIVE"),
            )

    def list(self, product_id: int) -> list[GrowthOptimizationRunRead]:
        FeedbackContextService(self.session).get(product_id)
        return [self._read(item) for item in self.repository.list(product_id)]

    def activate(
        self, product_id: int, run_id: int
    ) -> GrowthOptimizationRunActivateRead:
        run = self.repository.get(product_id, run_id)
        if run is None:
            raise AppError("Growth optimization plan was not found", status_code=404)
        context = FeedbackContextService(self.session).get(product_id)
        if context.context_digest != run.source_context_digest:
            raise AppError(
                "FeedbackContext changed; create a new optimization plan",
                status_code=409,
            )
        if run.status == "ACTIVE":
            return GrowthOptimizationRunActivateRead(run=self._read(run), reused=True)
        self._supersede_active(product_id)
        run.status = "ACTIVE"
        run.activated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(run)
        return GrowthOptimizationRunActivateRead(run=self._read(run), reused=False)

    def _supersede_active(self, product_id: int) -> None:
        self.session.execute(
            update(GrowthOptimizationRun)
            .where(
                GrowthOptimizationRun.product_id == product_id,
                GrowthOptimizationRun.status == "ACTIVE",
            )
            .values(status="SUPERSEDED")
        )

    @staticmethod
    def _request_digest(data: GrowthOptimizationRunCreateRequest) -> str:
        serialized = json.dumps(
            {
                "version": "growth-optimization-run-v1",
                "analysis": data.analysis.model_dump(mode="json"),
                "policy": data.policy.model_dump(mode="json"),
                "activate_internal": data.activate_internal,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(run: GrowthOptimizationRun) -> GrowthOptimizationRunRead:
        return GrowthOptimizationRunRead(
            id=run.id,
            product_id=run.product_id,
            idempotency_key=run.idempotency_key,
            source_context_digest=run.source_context_digest,
            source_recommendation_digest=run.source_recommendation_digest,
            policy=GrowthOptimizationPolicy.model_validate(run.policy_json),
            actions=[
                GrowthPlatformOptimizationAction.model_validate(item)
                for item in run.actions_json
            ],
            current_total_spend=float(run.current_total_spend),
            recommended_total_budget=float(run.recommended_total_budget),
            status=run.status,  # type: ignore[arg-type]
            execution_scope=run.execution_scope,  # type: ignore[arg-type]
            external_execution_status=run.external_execution_status,  # type: ignore[arg-type]
            created_at=run.created_at,
            activated_at=run.activated_at,
        )
