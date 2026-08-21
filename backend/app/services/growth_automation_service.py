from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import GrowthAutomationControl, GrowthAutomationCycle
from app.repositories.growth_optimization import GrowthOptimizationRepository
from app.schemas.growth import (
    GrowthAutomationControlRead,
    GrowthAutomationControlUpdate,
    GrowthAutomationCycleRead,
    GrowthAutomationCycleResult,
    GrowthAutomationEvaluationRequest,
    GrowthOptimizationExecutionRequest,
    GrowthOptimizationExecutionResult,
    GrowthOptimizationPolicy,
    GrowthPlatformOptimizationAction,
)
from app.services.feedback_context_service import FeedbackContextService
from app.services.growth_optimization_execution_service import (
    GrowthOptimizationExecutionService,
)

DEFAULT_MAXIMUM_TOTAL_BUDGET = Decimal("1000.00")
DEFAULT_MAXIMUM_BUDGET_CHANGE_PCT = Decimal("0.2500")
DEFAULT_MAXIMUM_BID_ADJUSTMENT_PCT = Decimal("0.2000")


class GrowthAutomationService:
    """Control bounded automatic evaluation through the local sandbox only."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = GrowthOptimizationRepository(session)

    def get(self, product_id: int) -> GrowthAutomationControlRead:
        FeedbackContextService(self.session).get(product_id)
        control = self.repository.get_automation_control(product_id)
        return self._read(product_id, control)

    def update(
        self, product_id: int, data: GrowthAutomationControlUpdate
    ) -> GrowthAutomationControlRead:
        FeedbackContextService(self.session).get(product_id)
        control = self.repository.get_automation_control(product_id)
        now = datetime.now(UTC)
        if control is None:
            control = GrowthAutomationControl(product_id=product_id)
            self.session.add(control)
        control.mode = data.mode
        control.kill_switch_engaged = data.kill_switch_engaged
        control.maximum_total_budget = Decimal(str(data.maximum_total_budget))
        control.maximum_budget_change_pct = Decimal(str(data.maximum_budget_change_pct))
        control.maximum_bid_adjustment_pct = Decimal(
            str(data.maximum_bid_adjustment_pct)
        )
        control.monitoring_enabled = data.monitoring_enabled
        control.evaluation_interval_seconds = data.evaluation_interval_seconds
        control.next_evaluation_at = now if data.monitoring_enabled else None
        control.updated_at = now
        self.session.commit()
        self.session.refresh(control)
        return self._read(product_id, control)

    def engage_kill_switch(self, product_id: int) -> GrowthAutomationControlRead:
        FeedbackContextService(self.session).get(product_id)
        control = self.repository.get_automation_control(product_id)
        now = datetime.now(UTC)
        if control is None:
            control = GrowthAutomationControl(
                product_id=product_id,
                mode="MANUAL",
                kill_switch_engaged=True,
                maximum_total_budget=DEFAULT_MAXIMUM_TOTAL_BUDGET,
                maximum_budget_change_pct=DEFAULT_MAXIMUM_BUDGET_CHANGE_PCT,
                maximum_bid_adjustment_pct=DEFAULT_MAXIMUM_BID_ADJUSTMENT_PCT,
                updated_at=now,
            )
            self.session.add(control)
        else:
            control.kill_switch_engaged = True
            control.updated_at = now
        self.session.commit()
        self.session.refresh(control)
        return self._read(product_id, control)

    def evaluate(
        self, product_id: int, data: GrowthAutomationEvaluationRequest
    ) -> GrowthOptimizationExecutionResult:
        FeedbackContextService(self.session).get(product_id)
        control = self.repository.get_automation_control(product_id)
        if control is None or control.mode != "AUTO_SANDBOX":
            raise AppError("Growth automation is not in AUTO_SANDBOX mode", 409)
        if control.kill_switch_engaged:
            raise AppError("Growth automation Kill Switch is engaged", 409)

        run = self.repository.get_active(product_id)
        if run is None:
            raise AppError("An active growth optimization plan is required", 409)
        self._validate_safety_limits(control, run.policy_json, run.actions_json)
        result = GrowthOptimizationExecutionService(self.session).execute(
            product_id,
            run.id,
            GrowthOptimizationExecutionRequest(
                idempotency_key=data.idempotency_key,
                expected_context_digest=data.expected_context_digest,
                confirm_sandbox_execution=True,
            ),
            trigger_kind="AUTO_POLICY",
        )
        control = self.repository.get_automation_control(product_id)
        if control is None:  # pragma: no cover - protected by the prior lookup
            raise AppError("Growth automation control was not found", 409)
        if control.last_execution_id != result.execution.id:
            control.last_execution_id = result.execution.id
            control.last_evaluated_at = datetime.now(UTC)
            control.updated_at = control.last_evaluated_at
            self.session.commit()
        return result

    def list_cycles(self, product_id: int) -> list[GrowthAutomationCycleRead]:
        FeedbackContextService(self.session).get(product_id)
        return [
            self._cycle_read(item)
            for item in self.repository.list_automation_cycles(product_id)
        ]

    def run_cycle(
        self,
        product_id: int,
        *,
        force: bool = False,
        observed_at: datetime | None = None,
    ) -> GrowthAutomationCycleResult:
        now = observed_at or datetime.now(UTC)
        context = FeedbackContextService(self.session).get(product_id)
        control = self.repository.get_automation_control(product_id)
        if control is None or not control.monitoring_enabled:
            raise AppError("Growth monitoring is not enabled", 409)
        next_due = self._as_utc(control.next_evaluation_at)
        if not force and next_due is not None and next_due > now:
            return GrowthAutomationCycleResult(cycle=None, due=False)

        run = self.repository.get_active(product_id)
        next_evaluation = now + timedelta(seconds=control.evaluation_interval_seconds)
        cycle_key = hashlib.sha256(
            f"{product_id}:{now.isoformat()}:{context.context_digest}".encode()
        ).hexdigest()
        existing = self.repository.get_cycle_by_key(product_id, cycle_key)
        if existing is not None:
            return GrowthAutomationCycleResult(
                cycle=self._cycle_read(existing), due=True, reused=True
            )

        status = "NO_ACTIVE_PLAN"
        execution_id = None
        if control.kill_switch_engaged:
            status = "KILL_SWITCHED"
        elif control.mode != "AUTO_SANDBOX":
            status = "MANUAL_REVIEW_REQUIRED"
        elif run is None:
            status = "NO_ACTIVE_PLAN"
        elif run.source_context_digest != context.context_digest:
            status = "REPLAN_REQUIRED"
        else:
            previous = next(
                (
                    item
                    for item in self.repository.list_automation_cycles(product_id)
                    if item.optimization_run_id == run.id
                    and item.context_digest == context.context_digest
                    and item.status in {"EXECUTED", "NO_CHANGE"}
                ),
                None,
            )
            if previous is not None:
                status = "NO_CHANGE"
            else:
                result = self.evaluate(
                    product_id,
                    GrowthAutomationEvaluationRequest(
                        idempotency_key=f"growth-cycle-{run.id}-{context.context_digest[:24]}",
                        expected_context_digest=context.context_digest,
                    ),
                )
                status = "EXECUTED"
                execution_id = result.execution.id

        cycle = GrowthAutomationCycle(
            product_id=product_id,
            optimization_run_id=None if run is None else run.id,
            execution_id=execution_id,
            cycle_key=cycle_key,
            context_digest=context.context_digest,
            status=status,
            observed_at=now,
            next_evaluation_at=next_evaluation,
            execution_mode="SANDBOX",
            external_mutation_performed=False,
        )
        control.next_evaluation_at = next_evaluation
        control.last_evaluated_at = now
        control.updated_at = now
        self.session.add(cycle)
        self.session.commit()
        self.session.refresh(cycle)
        return GrowthAutomationCycleResult(cycle=self._cycle_read(cycle), due=True)

    @staticmethod
    def _validate_safety_limits(
        control: GrowthAutomationControl,
        policy_json: dict[str, object],
        actions_json: list[dict[str, object]],
    ) -> None:
        policy = GrowthOptimizationPolicy.model_validate(policy_json)
        actions = [
            GrowthPlatformOptimizationAction.model_validate(item)
            for item in actions_json
        ]
        if Decimal(str(policy.total_budget)) > control.maximum_total_budget:
            raise AppError("Automatic plan exceeds the total budget safety limit", 409)
        if any(
            abs(Decimal(str(item.budget_change_pct or 0)))
            > control.maximum_budget_change_pct
            for item in actions
        ):
            raise AppError("Automatic plan exceeds the budget change safety limit", 409)
        if any(
            abs(Decimal(str(item.bid_adjustment_pct)))
            > control.maximum_bid_adjustment_pct
            for item in actions
        ):
            raise AppError("Automatic plan exceeds the bid safety limit", 409)

    @staticmethod
    def _read(
        product_id: int, control: GrowthAutomationControl | None
    ) -> GrowthAutomationControlRead:
        if control is None:
            return GrowthAutomationControlRead(
                product_id=product_id,
                mode="MANUAL",
                kill_switch_engaged=True,
                maximum_total_budget=float(DEFAULT_MAXIMUM_TOTAL_BUDGET),
                maximum_budget_change_pct=float(DEFAULT_MAXIMUM_BUDGET_CHANGE_PCT),
                maximum_bid_adjustment_pct=float(DEFAULT_MAXIMUM_BID_ADJUSTMENT_PCT),
                monitoring_enabled=False,
                evaluation_interval_seconds=900,
                next_evaluation_at=None,
                last_execution_id=None,
                last_evaluated_at=None,
                updated_at=None,
                persisted=False,
            )
        return GrowthAutomationControlRead(
            product_id=product_id,
            mode=control.mode,  # type: ignore[arg-type]
            kill_switch_engaged=control.kill_switch_engaged,
            maximum_total_budget=float(control.maximum_total_budget),
            maximum_budget_change_pct=float(control.maximum_budget_change_pct),
            maximum_bid_adjustment_pct=float(control.maximum_bid_adjustment_pct),
            monitoring_enabled=control.monitoring_enabled,
            evaluation_interval_seconds=control.evaluation_interval_seconds,
            next_evaluation_at=control.next_evaluation_at,
            last_execution_id=control.last_execution_id,
            last_evaluated_at=control.last_evaluated_at,
            updated_at=control.updated_at,
            persisted=True,
        )

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    @staticmethod
    def _cycle_read(cycle: GrowthAutomationCycle) -> GrowthAutomationCycleRead:
        return GrowthAutomationCycleRead(
            id=cycle.id,
            product_id=cycle.product_id,
            optimization_run_id=cycle.optimization_run_id,
            execution_id=cycle.execution_id,
            cycle_key=cycle.cycle_key,
            context_digest=cycle.context_digest,
            status=cycle.status,  # type: ignore[arg-type]
            observed_at=cycle.observed_at,
            next_evaluation_at=cycle.next_evaluation_at,
            execution_mode="SANDBOX",
            external_mutation_performed=False,
        )
