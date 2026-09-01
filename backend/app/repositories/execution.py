from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, desc, exists, or_, select, update
from sqlalchemy.orm import Session, aliased, selectinload

from app.models.execution import ExecutionAttempt, ExecutionJob


class ExecutionJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: ExecutionJob) -> None:
        self.session.add(job)
        self.session.flush()

    def add_attempt(self, attempt: ExecutionAttempt) -> None:
        self.session.add(attempt)
        self.session.flush()

    def get(self, job_id: int) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob)
            .options(selectinload(ExecutionJob.attempts))
            .where(ExecutionJob.id == job_id)
        )

    def get_by_idempotency_key(
        self, key: str, workspace_id: int | None
    ) -> ExecutionJob | None:
        return self.session.scalar(
            select(ExecutionJob)
            .options(selectinload(ExecutionJob.attempts))
            .where(
                ExecutionJob.idempotency_key == key,
                ExecutionJob.workspace_id == workspace_id,
            )
        )

    def list(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
    ) -> list[ExecutionJob]:
        statement = select(ExecutionJob).options(selectinload(ExecutionJob.attempts))
        if status is not None:
            statement = statement.where(ExecutionJob.status == status)
        if job_type is not None:
            statement = statement.where(ExecutionJob.job_type == job_type)
        if source_type is not None:
            statement = statement.where(ExecutionJob.source_type == source_type)
        if source_id is not None:
            statement = statement.where(ExecutionJob.source_id == source_id)
        return list(
            self.session.scalars(
                statement.order_by(
                    desc(ExecutionJob.priority),
                    ExecutionJob.created_at,
                    ExecutionJob.id,
                )
            ).all()
        )

    def running_with_expired_lease(
        self, now: datetime, workspace_id: int | None = None
    ) -> list[ExecutionJob]:
        conditions = [
            ExecutionJob.status == "RUNNING",
            ExecutionJob.lease_expires_at.is_not(None),
            ExecutionJob.lease_expires_at <= now,
        ]
        if workspace_id is not None:
            conditions.append(ExecutionJob.workspace_id == workspace_id)
        return list(
            self.session.scalars(
                select(ExecutionJob)
                .options(selectinload(ExecutionJob.attempts))
                .where(*conditions)
                .order_by(ExecutionJob.id)
            ).all()
        )

    def claim_next(
        self,
        *,
        owner_digest: str,
        lease_expires_at: datetime,
        now: datetime,
        job_types: list[str],
        workspace_id: int | None = None,
    ) -> int | None:
        active = aliased(ExecutionJob)
        active_same_key = exists(
            select(active.id)
            .where(
                active.status == "RUNNING",
                active.concurrency_key == ExecutionJob.concurrency_key,
                active.id != ExecutionJob.id,
                or_(
                    active.workspace_id == ExecutionJob.workspace_id,
                    and_(
                        active.workspace_id.is_(None),
                        ExecutionJob.workspace_id.is_(None),
                    ),
                ),
            )
            .correlate(ExecutionJob)
        )
        conditions = [
            ExecutionJob.status == "QUEUED",
            ExecutionJob.attempt_count < ExecutionJob.max_attempts,
            or_(
                ExecutionJob.estimated_cost == 0,
                ExecutionJob.cost_confirmed.is_(True),
            ),
            or_(ExecutionJob.concurrency_key.is_(None), ~active_same_key),
        ]
        if job_types:
            conditions.append(ExecutionJob.job_type.in_(job_types))
        if workspace_id is not None:
            conditions.append(ExecutionJob.workspace_id == workspace_id)
        candidate = (
            select(ExecutionJob.id)
            .where(and_(*conditions))
            .order_by(
                desc(ExecutionJob.priority),
                ExecutionJob.created_at,
                ExecutionJob.id,
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            update(ExecutionJob)
            .where(
                ExecutionJob.id == candidate,
                ExecutionJob.status == "QUEUED",
            )
            .values(
                status="RUNNING",
                attempt_count=ExecutionJob.attempt_count + 1,
                lease_owner_digest=owner_digest,
                lease_expires_at=lease_expires_at,
                safe_error_code=None,
                safe_error_details=None,
                completed_at=None,
                uncertain=False,
                updated_at=now,
            )
            .returning(ExecutionJob.id)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def latest_attempt(self, job_id: int) -> ExecutionAttempt | None:
        return self.session.scalar(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.execution_job_id == job_id)
            .order_by(desc(ExecutionAttempt.attempt_number))
            .limit(1)
        )
