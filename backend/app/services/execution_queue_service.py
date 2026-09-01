from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.execution import JOB_STATUSES, ExecutionAttempt, ExecutionJob
from app.models.product import utc_now
from app.repositories.execution import ExecutionJobRepository
from app.schemas.execution import (
    ExecutionJobClaimRequest,
    ExecutionJobCompleteRequest,
    ExecutionJobCreate,
    ExecutionJobCreateRead,
    ExecutionJobFailRequest,
    ExecutionJobHeartbeatRequest,
    ExecutionJobRead,
    ExecutionJobRetryRequest,
    ExecutionJobUnknownRequest,
    reject_sensitive_keys,
)

_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_RUNNING_CONCURRENCY_INDEX = "uq_execution_jobs_running_concurrency_key"
MAX_CLAIM_CONCURRENCY_RETRIES = 2


def _owner_digest(worker_id: str) -> str:
    return hashlib.sha256(worker_id.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ExecutionQueueService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ExecutionJobRepository(session)

    def create(self, data: ExecutionJobCreate) -> ExecutionJobCreateRead:
        self._assert_safe_mapping(data.input_payload)
        digest = data.input_digest.casefold()
        key = data.idempotency_key.strip()
        if len(key) < 8:
            raise AppError("Idempotency key is invalid", 422)
        workspace_id = self.session.info.get("workspace_id")
        existing = self.repository.get_by_idempotency_key(key, workspace_id)
        if existing is not None:
            return self._idempotent_result(existing, digest)
        job = ExecutionJob(
            workspace_id=workspace_id,
            job_type=data.job_type.casefold(),
            source_type=data.source_type.casefold(),
            source_id=data.source_id,
            input_digest=digest,
            idempotency_key=key,
            input_payload=data.input_payload,
            priority=data.priority,
            concurrency_key=(
                data.concurrency_key.strip() if data.concurrency_key else None
            ),
            estimated_cost=data.estimated_cost,
            currency=data.currency.upper(),
            cost_confirmed=data.cost_confirmed,
            max_attempts=data.max_attempts,
            status="QUEUED",
        )
        try:
            self.repository.add(job)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.repository.get_by_idempotency_key(key, workspace_id)
            if concurrent is None:
                raise
            return self._idempotent_result(concurrent, digest)
        return ExecutionJobCreateRead(job=self._read(job.id), reused=False)

    def list(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        source_type: str | None = None,
        source_id: int | None = None,
    ) -> list[ExecutionJob]:
        normalized_status = status.upper() if status else None
        if normalized_status is not None and normalized_status not in JOB_STATUSES:
            raise AppError("Execution job status filter is invalid", 422)
        jobs = self.repository.list(
            status=normalized_status,
            job_type=job_type.casefold() if job_type else None,
            source_type=source_type.casefold() if source_type else None,
            source_id=source_id,
        )
        workspace_id = self.session.info.get("workspace_id")
        if workspace_id is not None:
            return [job for job in jobs if job.workspace_id == workspace_id]
        return jobs

    def get(self, job_id: int) -> ExecutionJob:
        job = self.repository.get(job_id)
        workspace_id = self.session.info.get("workspace_id")
        if job is None or (
            workspace_id is not None and job.workspace_id != workspace_id
        ):
            raise AppError("Execution job not found", 404)
        return job

    def pause(self, job_id: int) -> ExecutionJobRead:
        job = self.get(job_id)
        if job.status == "PAUSED":
            return ExecutionJobRead.model_validate(job)
        if job.status != "QUEUED":
            raise AppError("Only queued jobs can be paused", 409)
        job.status = "PAUSED"
        self.session.commit()
        return self._read(job.id)

    def resume(self, job_id: int) -> ExecutionJobRead:
        job = self.get(job_id)
        if job.status == "QUEUED":
            return ExecutionJobRead.model_validate(job)
        if job.status != "PAUSED":
            raise AppError("Only paused jobs can be resumed", 409)
        job.status = "QUEUED"
        self.session.commit()
        return self._read(job.id)

    def cancel(self, job_id: int) -> ExecutionJobRead:
        job = self.get(job_id)
        if job.status == "CANCELLED":
            return ExecutionJobRead.model_validate(job)
        if job.status not in {"QUEUED", "PAUSED"}:
            raise AppError("Running or terminal jobs cannot be cancelled", 409)
        job.status = "CANCELLED"
        job.completed_at = utc_now()
        self.session.commit()
        return self._read(job.id)

    def retry(self, job_id: int, data: ExecutionJobRetryRequest) -> ExecutionJobRead:
        del data
        job = self.get(job_id)
        if job.status != "FAILED" or job.uncertain:
            raise AppError("Only certain failed jobs can be retried", 409)
        if job.attempt_count >= job.max_attempts:
            raise AppError("Execution job has exhausted its maximum attempts", 409)
        job.status = "QUEUED"
        job.safe_error_code = None
        job.safe_error_details = None
        job.completed_at = None
        self.session.commit()
        return self._read(job.id)

    def claim(self, data: ExecutionJobClaimRequest) -> ExecutionJobRead | None:
        workspace_id = self.session.info.get("workspace_id")
        for retry in range(MAX_CLAIM_CONCURRENCY_RETRIES + 1):
            now = utc_now()
            self._recover_expired_leases(now, workspace_id=workspace_id)
            try:
                job_id = self.repository.claim_next(
                    owner_digest=_owner_digest(data.worker_id),
                    lease_expires_at=now + timedelta(seconds=data.lease_seconds),
                    now=now,
                    job_types=data.job_types,
                    workspace_id=workspace_id,
                )
            except IntegrityError as error:
                self.session.rollback()
                if not self._is_running_concurrency_conflict(error):
                    raise
                if retry == MAX_CLAIM_CONCURRENCY_RETRIES:
                    return None
                continue
            if job_id is None:
                self.session.commit()
                return None
            job = self.session.get(ExecutionJob, job_id)
            if job is None:
                self.session.rollback()
                raise RuntimeError("Claimed execution job disappeared")
            self.repository.add_attempt(
                ExecutionAttempt(
                    execution_job_id=job.id,
                    attempt_number=job.attempt_count,
                    status="RUNNING",
                    started_at=now,
                )
            )
            self.session.commit()
            return self._read(job.id)
        raise RuntimeError("Unreachable execution claim retry state")

    def heartbeat(
        self, job_id: int, data: ExecutionJobHeartbeatRequest
    ) -> ExecutionJobRead:
        now = utc_now()
        job, attempt = self._owned_running(job_id, data.worker_id, now)
        if data.provider_call_count is not None:
            if data.provider_call_count < attempt.provider_call_count:
                raise AppError("Provider call count cannot decrease", 409)
            attempt.provider_call_count = data.provider_call_count
        if data.external_submission_possible:
            attempt.external_submission_possible = True
            attempt.provider_submission_state = "SUBMIT_UNKNOWN"
            if job.submitted_at is None:
                job.submitted_at = now
        job.lease_expires_at = now + timedelta(seconds=data.lease_seconds)
        self.session.commit()
        return self._read(job.id)

    def complete(
        self, job_id: int, data: ExecutionJobCompleteRequest
    ) -> ExecutionJobRead:
        now = utc_now()
        job, attempt = self._owned_running(job_id, data.worker_id, now)
        self._set_provider_call_count(attempt, data.provider_call_count)
        job.provider_name = data.provider_name
        job.provider_operation_id = data.provider_operation_id
        job.result_entity_type = data.result_entity_type
        job.result_entity_id = data.result_entity_id
        if data.provider_operation_id is not None and job.submitted_at is None:
            job.submitted_at = now
        job.status = "SUCCEEDED"
        job.completed_at = now
        job.lease_owner_digest = None
        job.lease_expires_at = None
        job.uncertain = False
        attempt.status = "SUCCEEDED"
        attempt.provider_submission_state = (
            "RESPONSE_RECEIVED"
            if data.provider_call_count > 0 or attempt.external_submission_possible
            else "NOT_STARTED"
        )
        attempt.completed_at = now
        self.session.commit()
        return self._read(job.id)

    def fail(self, job_id: int, data: ExecutionJobFailRequest) -> ExecutionJobRead:
        now = utc_now()
        self._assert_error(data.safe_error_code, data.safe_error_details)
        job, attempt = self._owned_running(job_id, data.worker_id, now)
        certain = data.provider_submission_state in {
            "NOT_SUBMITTED",
            "EXPLICIT_FAILURE",
            "RESPONSE_RECEIVED",
        }
        if (
            data.external_submission_possible or attempt.external_submission_possible
        ) and not certain:
            raise AppError(
                "Possible external submission must be marked SUBMIT_UNKNOWN", 409
            )
        self._set_provider_call_count(attempt, data.provider_call_count)
        job.status = "FAILED"
        job.completed_at = now
        job.safe_error_code = data.safe_error_code
        job.safe_error_details = data.safe_error_details or None
        job.lease_owner_digest = None
        job.lease_expires_at = None
        job.uncertain = False
        attempt.status = "FAILED"
        attempt.provider_submission_state = data.provider_submission_state
        attempt.completed_at = now
        attempt.safe_error_code = data.safe_error_code
        attempt.safe_error_details = data.safe_error_details or None
        self.session.commit()
        return self._read(job.id)

    def mark_submit_unknown(
        self, job_id: int, data: ExecutionJobUnknownRequest
    ) -> ExecutionJobRead:
        now = utc_now()
        self._assert_error(data.safe_error_code, data.safe_error_details)
        job, attempt = self._owned_running(job_id, data.worker_id, now)
        self._set_provider_call_count(attempt, data.provider_call_count)
        attempt.external_submission_possible = True
        attempt.provider_submission_state = "SUBMIT_UNKNOWN"
        attempt.status = "SUBMIT_UNKNOWN"
        attempt.completed_at = now
        attempt.safe_error_code = data.safe_error_code
        attempt.safe_error_details = data.safe_error_details or None
        job.status = "SUBMIT_UNKNOWN"
        job.uncertain = True
        job.safe_error_code = data.safe_error_code
        job.safe_error_details = data.safe_error_details or None
        job.provider_name = data.provider_name
        job.provider_operation_id = data.provider_operation_id
        job.submitted_at = job.submitted_at or now
        job.completed_at = now
        job.lease_owner_digest = None
        job.lease_expires_at = None
        self.session.commit()
        return self._read(job.id)

    def recover_expired_leases(self) -> list[ExecutionJobRead]:
        recovered = self._recover_expired_leases(
            utc_now(), workspace_id=self.session.info.get("workspace_id")
        )
        self.session.commit()
        return [self._read(job_id) for job_id in recovered]

    def _recover_expired_leases(
        self, now: datetime, *, workspace_id: int | None = None
    ) -> list[int]:
        recovered: list[int] = []
        for job in self.repository.running_with_expired_lease(now, workspace_id):
            attempt = self.repository.latest_attempt(job.id)
            external_possible = bool(
                (attempt and attempt.external_submission_possible)
                or job.submitted_at
                or job.provider_operation_id
            )
            job.lease_owner_digest = None
            job.lease_expires_at = None
            job.completed_at = now
            if external_possible:
                job.status = "SUBMIT_UNKNOWN"
                job.uncertain = True
                job.safe_error_code = "LEASE_EXPIRED_AFTER_EXTERNAL_SUBMISSION"
                if attempt is not None:
                    attempt.status = "SUBMIT_UNKNOWN"
                    attempt.external_submission_possible = True
                    attempt.provider_submission_state = "SUBMIT_UNKNOWN"
                    attempt.safe_error_code = job.safe_error_code
                    attempt.completed_at = now
            else:
                job.uncertain = False
                job.safe_error_code = "LEASE_EXPIRED"
                if attempt is not None:
                    attempt.status = "LEASE_EXPIRED"
                    attempt.provider_submission_state = "NOT_SUBMITTED"
                    attempt.safe_error_code = job.safe_error_code
                    attempt.completed_at = now
                if job.attempt_count < job.max_attempts:
                    job.status = "QUEUED"
                    job.completed_at = None
                else:
                    job.status = "FAILED"
            recovered.append(job.id)
        return recovered

    def _owned_running(
        self, job_id: int, worker_id: str, now: datetime
    ) -> tuple[ExecutionJob, ExecutionAttempt]:
        job = self.get(job_id)
        if job.status != "RUNNING":
            raise AppError("Execution job is not running", 409)
        if job.lease_owner_digest != _owner_digest(worker_id):
            raise AppError("Execution job lease is owned by another worker", 409)
        if job.lease_expires_at is None or _aware(job.lease_expires_at) <= now:
            self._recover_expired_leases(
                now, workspace_id=self.session.info.get("workspace_id")
            )
            self.session.commit()
            raise AppError("Execution job lease has expired", 409)
        attempt = self.repository.latest_attempt(job.id)
        if attempt is None or attempt.status != "RUNNING":
            raise AppError("Execution attempt is unavailable", 409)
        return job, attempt

    def _read(self, job_id: int) -> ExecutionJobRead:
        return ExecutionJobRead.model_validate(self.get(job_id))

    @staticmethod
    def _assert_safe_mapping(value: dict[str, object]) -> None:
        try:
            reject_sensitive_keys(value)
        except ValueError as error:
            raise AppError(str(error), 422) from error

    def _assert_error(
        self, safe_error_code: str, safe_error_details: dict[str, object]
    ) -> None:
        if _SAFE_ERROR_CODE.fullmatch(safe_error_code) is None:
            raise AppError("Safe error code is invalid", 422)
        self._assert_safe_mapping(safe_error_details)

    @staticmethod
    def _set_provider_call_count(
        attempt: ExecutionAttempt, provider_call_count: int
    ) -> None:
        if provider_call_count < attempt.provider_call_count:
            raise AppError("Provider call count cannot decrease", 409)
        attempt.provider_call_count = provider_call_count

    @staticmethod
    def _idempotent_result(
        existing: ExecutionJob, digest: str
    ) -> ExecutionJobCreateRead:
        if existing.input_digest != digest:
            raise AppError("Idempotency key was used for different input", 409)
        return ExecutionJobCreateRead(
            job=ExecutionJobRead.model_validate(existing), reused=True
        )

    @staticmethod
    def _is_running_concurrency_conflict(error: IntegrityError) -> bool:
        original = error.orig
        diagnostic = getattr(original, "diag", None)
        if getattr(diagnostic, "constraint_name", None) == _RUNNING_CONCURRENCY_INDEX:
            return True
        safe_text = str(original).casefold()
        return _RUNNING_CONCURRENCY_INDEX in safe_text or (
            "unique constraint failed" in safe_text
            and "execution_jobs.concurrency_key" in safe_text
        )
