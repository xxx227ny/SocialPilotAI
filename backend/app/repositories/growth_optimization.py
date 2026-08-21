from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    GrowthAutomationControl,
    GrowthAutomationCycle,
    GrowthOptimizationExecution,
    GrowthOptimizationRun,
)


class GrowthOptimizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, product_id: int, run_id: int) -> GrowthOptimizationRun | None:
        return self.session.scalar(
            select(GrowthOptimizationRun).where(
                GrowthOptimizationRun.id == run_id,
                GrowthOptimizationRun.product_id == product_id,
            )
        )

    def get_by_key(
        self, product_id: int, idempotency_key: str
    ) -> GrowthOptimizationRun | None:
        return self.session.scalar(
            select(GrowthOptimizationRun).where(
                GrowthOptimizationRun.product_id == product_id,
                GrowthOptimizationRun.idempotency_key == idempotency_key,
            )
        )

    def list(self, product_id: int) -> list[GrowthOptimizationRun]:
        return list(
            self.session.scalars(
                select(GrowthOptimizationRun)
                .where(GrowthOptimizationRun.product_id == product_id)
                .order_by(GrowthOptimizationRun.id.asc())
            ).all()
        )

    def get_active(self, product_id: int) -> GrowthOptimizationRun | None:
        return self.session.scalar(
            select(GrowthOptimizationRun).where(
                GrowthOptimizationRun.product_id == product_id,
                GrowthOptimizationRun.status == "ACTIVE",
            )
        )

    def get_automation_control(self, product_id: int) -> GrowthAutomationControl | None:
        return self.session.get(GrowthAutomationControl, product_id)

    def list_automation_cycles(self, product_id: int) -> list[GrowthAutomationCycle]:
        return list(
            self.session.scalars(
                select(GrowthAutomationCycle)
                .where(GrowthAutomationCycle.product_id == product_id)
                .order_by(GrowthAutomationCycle.id.desc())
            ).all()
        )

    def get_cycle_by_key(
        self, product_id: int, cycle_key: str
    ) -> GrowthAutomationCycle | None:
        return self.session.scalar(
            select(GrowthAutomationCycle).where(
                GrowthAutomationCycle.product_id == product_id,
                GrowthAutomationCycle.cycle_key == cycle_key,
            )
        )

    def get_execution(
        self, product_id: int, execution_id: int
    ) -> GrowthOptimizationExecution | None:
        return self.session.scalar(
            select(GrowthOptimizationExecution).where(
                GrowthOptimizationExecution.id == execution_id,
                GrowthOptimizationExecution.product_id == product_id,
            )
        )

    def get_execution_by_key(
        self, product_id: int, idempotency_key: str
    ) -> GrowthOptimizationExecution | None:
        return self.session.scalar(
            select(GrowthOptimizationExecution).where(
                GrowthOptimizationExecution.product_id == product_id,
                GrowthOptimizationExecution.idempotency_key == idempotency_key,
            )
        )

    def list_executions(self, product_id: int) -> list[GrowthOptimizationExecution]:
        return list(
            self.session.scalars(
                select(GrowthOptimizationExecution)
                .where(GrowthOptimizationExecution.product_id == product_id)
                .order_by(GrowthOptimizationExecution.id.asc())
            ).all()
        )
