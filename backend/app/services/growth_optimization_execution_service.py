from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import GrowthOptimizationExecution
from app.repositories.growth_optimization import GrowthOptimizationRepository
from app.schemas.growth import (
    GrowthOptimizationExecutionPreflightRead,
    GrowthOptimizationExecutionRead,
    GrowthOptimizationExecutionRequest,
    GrowthOptimizationExecutionResult,
    GrowthOptimizationPolicy,
    GrowthPlatformOptimizationAction,
)
from app.services.feedback_context_service import FeedbackContextService


class GrowthOptimizationExecutionService:
    """Execute one active plan through an auditable no-network sandbox adapter."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = GrowthOptimizationRepository(session)

    def preflight(
        self, product_id: int, run_id: int
    ) -> GrowthOptimizationExecutionPreflightRead:
        run = self.repository.get(product_id, run_id)
        if run is None:
            raise AppError("Growth optimization plan was not found", status_code=404)
        if run.status != "ACTIVE":
            raise AppError(
                "Only the active growth optimization plan can be executed",
                status_code=409,
            )
        context = FeedbackContextService(self.session).get(product_id)
        if context.context_digest != run.source_context_digest:
            raise AppError(
                "FeedbackContext changed; create a new optimization plan",
                status_code=409,
            )
        self._validate_frozen_plan(run.policy_json, run.actions_json)
        return GrowthOptimizationExecutionPreflightRead(
            product_id=product_id,
            optimization_run_id=run_id,
            source_context_digest=run.source_context_digest,
        )

    def execute(
        self,
        product_id: int,
        run_id: int,
        data: GrowthOptimizationExecutionRequest,
    ) -> GrowthOptimizationExecutionResult:
        request_digest = self._request_digest(run_id, data)
        existing = self.repository.get_execution_by_key(
            product_id, data.idempotency_key
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise AppError(
                    "Idempotency key is bound to a different sandbox execution",
                    status_code=409,
                )
            return GrowthOptimizationExecutionResult(
                execution=self._read(existing), reused=True
            )

        checked = self.preflight(product_id, run_id)
        if data.expected_context_digest != checked.source_context_digest:
            raise AppError(
                "Expected FeedbackContext does not match the active plan",
                status_code=409,
            )
        run = self.repository.get(product_id, run_id)
        if run is None:  # pragma: no cover - protected by the preflight transaction
            raise AppError("Growth optimization plan was not found", status_code=404)
        target_actions = [
            GrowthPlatformOptimizationAction.model_validate(item).model_dump(
                mode="json"
            )
            for item in run.actions_json
        ]
        before_actions = [self._before_action(item) for item in target_actions]
        execution = GrowthOptimizationExecution(
            product_id=product_id,
            optimization_run_id=run_id,
            idempotency_key=data.idempotency_key,
            request_digest=request_digest,
            source_context_digest=run.source_context_digest,
            before_actions_json=before_actions,
            target_actions_json=target_actions,
            result_actions_json=target_actions,
            status="SUCCEEDED",
            execution_mode="SANDBOX",
            provider_name="sandbox_ad_adapter",
            external_mutation_performed=False,
        )
        try:
            self.session.add(execution)
            self.session.commit()
            self.session.refresh(execution)
        except IntegrityError as exc:
            self.session.rollback()
            recovered = self.repository.get_execution_by_key(
                product_id, data.idempotency_key
            )
            if recovered is None or recovered.request_digest != request_digest:
                raise AppError(
                    "Sandbox execution conflict; outcome was not retried",
                    status_code=409,
                ) from exc
            return GrowthOptimizationExecutionResult(
                execution=self._read(recovered), reused=True
            )
        return GrowthOptimizationExecutionResult(
            execution=self._read(execution), reused=False
        )

    def list(self, product_id: int) -> list[GrowthOptimizationExecutionRead]:
        FeedbackContextService(self.session).get(product_id)
        return [
            self._read(item) for item in self.repository.list_executions(product_id)
        ]

    def rollback(
        self, product_id: int, execution_id: int
    ) -> GrowthOptimizationExecutionResult:
        execution = self.repository.get_execution(product_id, execution_id)
        if execution is None:
            raise AppError(
                "Growth optimization execution was not found", status_code=404
            )
        if execution.status == "ROLLED_BACK":
            return GrowthOptimizationExecutionResult(
                execution=self._read(execution), reused=True
            )
        execution.status = "ROLLED_BACK"
        execution.result_actions_json = execution.before_actions_json
        execution.rolled_back_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(execution)
        return GrowthOptimizationExecutionResult(
            execution=self._read(execution), reused=False
        )

    @staticmethod
    def _validate_frozen_plan(
        policy_json: dict[str, object], actions_json: list[dict[str, object]]
    ) -> None:
        policy = GrowthOptimizationPolicy.model_validate(policy_json)
        actions = [
            GrowthPlatformOptimizationAction.model_validate(item)
            for item in actions_json
        ]
        if not actions:
            raise AppError("Growth optimization plan has no actions", status_code=409)
        if any(
            abs(item.bid_adjustment_pct) > policy.maximum_bid_adjustment_pct
            for item in actions
        ):
            raise AppError(
                "Growth optimization plan exceeds the bid safety limit",
                status_code=409,
            )
        total = round(sum(item.recommended_budget for item in actions), 2)
        if total != round(policy.total_budget, 2):
            raise AppError(
                "Growth optimization plan budget is inconsistent", status_code=409
            )

    @staticmethod
    def _before_action(item: dict[str, object]) -> dict[str, object]:
        action = GrowthPlatformOptimizationAction.model_validate(item)
        return GrowthPlatformOptimizationAction(
            platform=action.platform,
            observed_roas=action.observed_roas,
            current_spend=action.current_spend,
            current_share=action.current_share,
            recommended_budget=action.current_spend,
            recommended_share=action.current_share,
            budget_change=0,
            budget_change_pct=0 if action.current_spend > 0 else None,
            bid_adjustment_pct=0,
            action="hold",
        ).model_dump(mode="json")

    @staticmethod
    def _request_digest(run_id: int, data: GrowthOptimizationExecutionRequest) -> str:
        serialized = json.dumps(
            {
                "version": "growth-sandbox-execution-v1",
                "optimization_run_id": run_id,
                "expected_context_digest": data.expected_context_digest,
                "confirm_sandbox_execution": data.confirm_sandbox_execution,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _read(
        execution: GrowthOptimizationExecution,
    ) -> GrowthOptimizationExecutionRead:
        return GrowthOptimizationExecutionRead(
            id=execution.id,
            product_id=execution.product_id,
            optimization_run_id=execution.optimization_run_id,
            idempotency_key=execution.idempotency_key,
            source_context_digest=execution.source_context_digest,
            before_actions=execution.before_actions_json,
            target_actions=execution.target_actions_json,
            result_actions=execution.result_actions_json,
            status=execution.status,  # type: ignore[arg-type]
            execution_mode=execution.execution_mode,  # type: ignore[arg-type]
            provider_name=execution.provider_name,  # type: ignore[arg-type]
            external_mutation_performed=execution.external_mutation_performed,
            created_at=execution.created_at,
            rolled_back_at=execution.rolled_back_at,
        )
