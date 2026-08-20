from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.product import utc_now


class GrowthOptimizationRun(Base):
    __tablename__ = "growth_optimization_runs"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_growth_optimization_product_key",
        ),
        CheckConstraint(
            "status IN ('PROPOSED','ACTIVE','SUPERSEDED')",
            name="ck_growth_optimization_status",
        ),
        CheckConstraint(
            "execution_scope = 'INTERNAL_PLAN_ONLY'",
            name="ck_growth_optimization_execution_scope",
        ),
        CheckConstraint(
            "external_execution_status = 'NOT_CONNECTED'",
            name="ck_growth_optimization_external_status",
        ),
        Index(
            "uq_growth_optimization_active_product",
            "product_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_context_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    source_recommendation_digest: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    policy_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actions_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    current_total_spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recommended_total_budget: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, default="INTERNAL_PLAN_ONLY"
    )
    external_execution_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="NOT_CONNECTED"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
