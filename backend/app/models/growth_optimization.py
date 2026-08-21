from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
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


class GrowthOptimizationExecution(Base):
    __tablename__ = "growth_optimization_executions"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "idempotency_key",
            name="uq_growth_execution_product_key",
        ),
        CheckConstraint(
            "status IN ('SUCCEEDED','ROLLED_BACK')",
            name="ck_growth_execution_status",
        ),
        CheckConstraint(
            "execution_mode = 'SANDBOX'",
            name="ck_growth_execution_mode",
        ),
        CheckConstraint(
            "provider_name = 'sandbox_ad_adapter'",
            name="ck_growth_execution_provider",
        ),
        CheckConstraint(
            "external_mutation_performed = 0",
            name="ck_growth_execution_no_external_mutation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    optimization_run_id: Mapped[int] = mapped_column(
        ForeignKey("growth_optimization_runs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_context_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    before_actions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    target_actions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    result_actions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(40), nullable=False)
    external_mutation_performed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
