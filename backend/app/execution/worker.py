from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Event, Lock, Thread
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.execution.contracts import (
    ExecutionContext,
    HandlerResult,
    HandlerStatus,
    LeaseLostError,
    WorkerStopRequested,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.schemas.execution import (
    ExecutionJobClaimRequest,
    ExecutionJobCompleteRequest,
    ExecutionJobFailRequest,
    ExecutionJobHeartbeatRequest,
    ExecutionJobUnknownRequest,
)
from app.services.execution_queue_service import ExecutionQueueService


class _SessionFactory(Protocol):
    def __call__(self) -> Session: ...


class WorkerRunStatus(StrEnum):
    NO_JOB = "NO_JOB"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"
    LEASE_LOST = "LEASE_LOST"
    STOPPED = "STOPPED"


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    status: WorkerRunStatus
    job_id: int | None = None


class ExecutionWorker:
    """Single-job synchronous Worker with a bounded, joined Heartbeat thread."""

    def __init__(
        self,
        *,
        session_factory: _SessionFactory,
        registry: ExecutionHandlerRegistry,
        worker_id: str,
        lease_seconds: int = 30,
        heartbeat_interval_seconds: float = 5,
    ) -> None:
        if len(worker_id) < 8:
            raise ValueError("Worker identity must contain at least 8 characters")
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("Worker lease must be between 5 and 3600 seconds")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("Heartbeat interval must be positive")
        if heartbeat_interval_seconds >= lease_seconds:
            raise ValueError("Heartbeat interval must be shorter than the lease")
        self._session_factory = session_factory
        self._registry = registry
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stop_event = Event()
        self._run_lock = Lock()
        self._thread_lock = Lock()
        self._heartbeat_lock = Lock()
        self._heartbeat_thread: Thread | None = None

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    @property
    def has_live_heartbeat(self) -> bool:
        with self._thread_lock:
            return bool(
                self._heartbeat_thread is not None
                and self._heartbeat_thread.is_alive()
            )

    def stop(self) -> None:
        """Request cooperative stop; run_once always joins its Heartbeat thread."""
        self._stop_event.set()

    def run_once(self) -> WorkerRunResult:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("ExecutionWorker is already running")
        try:
            if self._stop_event.is_set():
                return WorkerRunResult(WorkerRunStatus.STOPPED)
            with self._session_factory() as session:
                claimed = ExecutionQueueService(session).claim(
                    ExecutionJobClaimRequest(
                        worker_id=self._worker_id,
                        lease_seconds=self._lease_seconds,
                        job_types=[],
                    )
                )
            if claimed is None:
                return WorkerRunResult(WorkerRunStatus.NO_JOB)
            return self._execute_claimed(
                claimed.id, claimed.job_type, claimed.input_payload
            )
        finally:
            self._run_lock.release()

    def _execute_claimed(
        self, job_id: int, job_type: str, input_payload: dict[str, object]
    ) -> WorkerRunResult:
        lease_lost = Event()
        heartbeat_stop = Event()
        context = ExecutionContext(
            job_id=job_id,
            stop_event=self._stop_event,
            lease_lost_event=lease_lost,
            heartbeat=lambda count, external: self._heartbeat_once(
                job_id,
                provider_call_count=count,
                external_submission_possible=external,
                lease_lost=lease_lost,
            ),
        )
        heartbeat_thread = Thread(
            target=self._heartbeat_loop,
            args=(job_id, context, heartbeat_stop, lease_lost),
            name=f"execution-heartbeat-{job_id}",
            daemon=False,
        )
        self._set_heartbeat_thread(heartbeat_thread)
        heartbeat_thread.start()
        result: HandlerResult | None = None
        lease_was_lost = False
        try:
            result = self._invoke_handler(job_type, input_payload, context)
        except LeaseLostError:
            lease_was_lost = True
        except WorkerStopRequested:
            _, external_possible = context.provider_state()
            result = (
                HandlerResult.submit_unknown(
                    "WORKER_STOPPED_AFTER_EXTERNAL_SUBMISSION"
                )
                if external_possible
                else HandlerResult.failed("WORKER_STOPPED")
            )
        except Exception:
            _, external_possible = context.provider_state()
            result = (
                HandlerResult.submit_unknown("HANDLER_EXECUTION_UNCERTAIN")
                if external_possible
                else HandlerResult.failed("HANDLER_EXECUTION_FAILED")
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join()
            self._set_heartbeat_thread(None)

        if lease_was_lost or lease_lost.is_set():
            return WorkerRunResult(WorkerRunStatus.LEASE_LOST, job_id)
        if result is None:
            result = HandlerResult.failed("HANDLER_RESULT_MISSING")
        return self._finalize(job_id, context, result, lease_lost)

    def _invoke_handler(
        self,
        job_type: str,
        input_payload: dict[str, object],
        context: ExecutionContext,
    ) -> HandlerResult:
        handler = self._registry.resolve(job_type)
        if handler is None:
            return HandlerResult.failed("UNREGISTERED_JOB_TYPE")
        try:
            validated = handler.input_schema.model_validate(input_payload)
        except ValidationError:
            return HandlerResult.failed("INVALID_JOB_INPUT")
        context.checkpoint()
        result = handler.execute(context, validated)
        context.checkpoint()
        if not isinstance(result, HandlerResult):
            return HandlerResult.failed("INVALID_HANDLER_RESULT")
        return result

    def _finalize(
        self,
        job_id: int,
        context: ExecutionContext,
        result: HandlerResult,
        lease_lost: Event,
    ) -> WorkerRunResult:
        provider_call_count, external_possible = context.provider_state()
        if result.status == HandlerStatus.SUBMIT_UNKNOWN and not external_possible:
            try:
                self._heartbeat_once(
                    job_id,
                    provider_call_count=provider_call_count,
                    external_submission_possible=True,
                    lease_lost=lease_lost,
                )
            except LeaseLostError:
                return WorkerRunResult(WorkerRunStatus.LEASE_LOST, job_id)
            external_possible = True
        try:
            with self._session_factory() as session:
                service = ExecutionQueueService(session)
                if result.status == HandlerStatus.SUCCEEDED:
                    service.complete(
                        job_id,
                        ExecutionJobCompleteRequest(
                            worker_id=self._worker_id,
                            provider_name=result.provider_name,
                            provider_operation_id=result.provider_operation_id,
                            provider_call_count=provider_call_count,
                            result_entity_type=result.result_entity_type,
                            result_entity_id=result.result_entity_id,
                        ),
                    )
                    return WorkerRunResult(WorkerRunStatus.SUCCEEDED, job_id)
                if result.status == HandlerStatus.SUBMIT_UNKNOWN or external_possible:
                    service.mark_submit_unknown(
                        job_id,
                        ExecutionJobUnknownRequest(
                            worker_id=self._worker_id,
                            safe_error_code=(
                                result.safe_error_code
                                or "HANDLER_RESULT_UNCERTAIN"
                            ),
                            safe_error_details=result.safe_error_details,
                            provider_call_count=provider_call_count,
                            provider_name=result.provider_name,
                            provider_operation_id=result.provider_operation_id,
                        ),
                    )
                    return WorkerRunResult(
                        WorkerRunStatus.SUBMIT_UNKNOWN, job_id
                    )
                service.fail(
                    job_id,
                    ExecutionJobFailRequest(
                        worker_id=self._worker_id,
                        safe_error_code=(
                            result.safe_error_code or "HANDLER_EXECUTION_FAILED"
                        ),
                        safe_error_details=result.safe_error_details,
                        provider_call_count=provider_call_count,
                    ),
                )
                return WorkerRunResult(WorkerRunStatus.FAILED, job_id)
        except AppError as error:
            if error.status_code == 409:
                lease_lost.set()
                return WorkerRunResult(WorkerRunStatus.LEASE_LOST, job_id)
            raise

    def _heartbeat_loop(
        self,
        job_id: int,
        context: ExecutionContext,
        heartbeat_stop: Event,
        lease_lost: Event,
    ) -> None:
        while not heartbeat_stop.wait(self._heartbeat_interval_seconds):
            provider_call_count, external_possible = context.provider_state()
            try:
                self._heartbeat_once(
                    job_id,
                    provider_call_count=provider_call_count,
                    external_submission_possible=external_possible,
                    lease_lost=lease_lost,
                )
            except LeaseLostError:
                return

    def _heartbeat_once(
        self,
        job_id: int,
        *,
        provider_call_count: int,
        external_submission_possible: bool,
        lease_lost: Event,
    ) -> None:
        with self._heartbeat_lock:
            try:
                with self._session_factory() as session:
                    ExecutionQueueService(session).heartbeat(
                        job_id,
                        ExecutionJobHeartbeatRequest(
                            worker_id=self._worker_id,
                            lease_seconds=self._lease_seconds,
                            provider_call_count=provider_call_count,
                            external_submission_possible=external_submission_possible,
                        ),
                    )
            except Exception as error:
                lease_lost.set()
                raise LeaseLostError(
                    "Execution heartbeat could not renew lease"
                ) from error

    def _set_heartbeat_thread(self, thread: Thread | None) -> None:
        with self._thread_lock:
            self._heartbeat_thread = thread
