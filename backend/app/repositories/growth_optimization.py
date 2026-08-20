from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GrowthOptimizationRun


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
