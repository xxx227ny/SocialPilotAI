from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import utc_now

JOB_STATUSES = (
    "QUEUED",
    "PAUSED",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "SUBMIT_UNKNOWN",
    "CANCELLED",
)
ATTEMPT_STATUSES = (
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "SUBMIT_UNKNOWN",
    "LEASE_EXPIRED",
)


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','PAUSED','RUNNING','SUCCEEDED','FAILED',"
            "'SUBMIT_UNKNOWN','CANCELLED')",
            name="ck_execution_jobs_status",
        ),
        CheckConstraint("priority >= 0", name="ck_execution_jobs_priority"),
        CheckConstraint(
            "estimated_cost >= 0", name="ck_execution_jobs_estimated_cost"
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 "
            "AND attempt_count <= max_attempts",
            name="ck_execution_jobs_attempt_counts",
        ),
        CheckConstraint(
            "uncertain = (status = 'SUBMIT_UNKNOWN')",
            name="ck_execution_jobs_uncertain_status",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND lease_owner_digest IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'RUNNING' AND lease_owner_digest IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_execution_jobs_lease_state",
        ),
        UniqueConstraint("idempotency_key", name="uq_execution_jobs_idempotency"),
        Index(
            "uq_execution_jobs_running_concurrency_key",
            "concurrency_key",
            unique=True,
            sqlite_where=text(
                "concurrency_key IS NOT NULL AND status = 'RUNNING'"
            ),
            postgresql_where=text(
                "concurrency_key IS NOT NULL AND status = 'RUNNING'"
            ),
        ),
        Index(
            "ix_execution_jobs_queue_order",
            "status",
            "priority",
            "created_at",
            "id",
        ),
        Index("ix_execution_jobs_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    input_payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    cost_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="QUEUED", index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_owner_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_operation_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_details: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    attempts: Mapped[list[ExecutionAttempt]] = relationship(
        back_populates="execution_job",
        cascade="all, delete-orphan",
        order_by="ExecutionAttempt.attempt_number",
    )

    @property
    def lease_active(self) -> bool:
        if (
            self.status != "RUNNING"
            or self.lease_owner_digest is None
            or self.lease_expires_at is None
        ):
            return False
        expires_at = self.lease_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at > utc_now()


class ExecutionAttempt(Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','FAILED','SUBMIT_UNKNOWN',"
            "'LEASE_EXPIRED')",
            name="ck_execution_attempts_status",
        ),
        CheckConstraint(
            "attempt_number >= 1", name="ck_execution_attempts_number"
        ),
        CheckConstraint(
            "provider_call_count >= 0",
            name="ck_execution_attempts_provider_call_count",
        ),
        UniqueConstraint(
            "execution_job_id",
            "attempt_number",
            name="uq_execution_attempt_job_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_job_id: Mapped[int] = mapped_column(
        ForeignKey("execution_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    safe_error_details: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True
    )
    provider_call_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    external_submission_possible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    execution_job: Mapped[ExecutionJob] = relationship(back_populates="attempts")
