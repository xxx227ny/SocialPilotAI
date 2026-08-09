from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event, Lock
from typing import Protocol

from pydantic import BaseModel

from app.schemas.execution import reject_sensitive_keys

_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")


class HandlerStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"


class LeaseLostError(RuntimeError):
    """Raised when a Handler can no longer safely mutate its claimed Job."""


class WorkerStopRequested(RuntimeError):
    """Raised at a cooperative checkpoint after a safe stop was requested."""


class _HeartbeatCallback(Protocol):
    def __call__(
        self, provider_call_count: int, external_submission_possible: bool
    ) -> None: ...


class ExecutionContext:
    """Lease-aware, secret-free context exposed to a registered Handler."""

    def __init__(
        self,
        *,
        job_id: int,
        stop_event: Event,
        lease_lost_event: Event,
        heartbeat: _HeartbeatCallback,
    ) -> None:
        self.job_id = job_id
        self._stop_event = stop_event
        self._lease_lost_event = lease_lost_event
        self._heartbeat = heartbeat
        self._state_lock = Lock()
        self._provider_call_count = 0
        self._external_submission_possible = False

    def checkpoint(self) -> None:
        if self._lease_lost_event.is_set():
            raise LeaseLostError("Execution lease is no longer owned")
        if self._stop_event.is_set():
            raise WorkerStopRequested("Execution worker stop was requested")

    def wait(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Wait duration cannot be negative")
        self._stop_event.wait(seconds)
        self.checkpoint()

    def before_provider_call(
        self, *, may_submit_external: bool = False
    ) -> int:
        """Persist the safety boundary before an Adapter makes a Provider call."""
        self.checkpoint()
        with self._state_lock:
            self._provider_call_count += 1
            if may_submit_external:
                self._external_submission_possible = True
            call_count = self._provider_call_count
            external_possible = self._external_submission_possible
        self._heartbeat(call_count, external_possible)
        self.checkpoint()
        return call_count

    def provider_state(self) -> tuple[int, bool]:
        with self._state_lock:
            return (
                self._provider_call_count,
                self._external_submission_possible,
            )


@dataclass(frozen=True, slots=True)
class HandlerResult:
    status: HandlerStatus
    safe_error_code: str | None = None
    safe_error_details: dict[str, object] = field(default_factory=dict)
    provider_name: str | None = None
    provider_operation_id: str | None = None
    result_entity_type: str | None = None
    result_entity_id: int | None = None

    def __post_init__(self) -> None:
        reject_sensitive_keys(self.safe_error_details)
        if not isinstance(self.status, HandlerStatus):
            raise ValueError("Handler status is invalid")
        if self.provider_name is not None and not 1 <= len(self.provider_name) <= 80:
            raise ValueError("Provider name is invalid")
        if self.provider_operation_id is not None and not (
            1 <= len(self.provider_operation_id) <= 255
        ):
            raise ValueError("Provider operation identity is invalid")
        if (self.result_entity_type is None) != (self.result_entity_id is None):
            raise ValueError("Result entity type and ID must be supplied together")
        if self.result_entity_type is not None and not (
            1 <= len(self.result_entity_type) <= 80
            and re.fullmatch(r"[a-z0-9_.-]+", self.result_entity_type)
            and self.result_entity_id is not None
            and self.result_entity_id > 0
        ):
            raise ValueError("Result entity reference is invalid")
        if self.status != HandlerStatus.SUCCEEDED and self.result_entity_type:
            raise ValueError("Only successful Handler results may reference an entity")
        if self.status == HandlerStatus.SUCCEEDED:
            if self.safe_error_code is not None:
                raise ValueError("Successful Handler result cannot have an error code")
            return
        if not self.safe_error_code:
            raise ValueError("Non-success Handler result requires a safe error code")
        if _SAFE_ERROR_CODE.fullmatch(self.safe_error_code) is None:
            raise ValueError("Handler safe error code is invalid")

    @classmethod
    def succeeded(
        cls,
        *,
        provider_name: str | None = None,
        provider_operation_id: str | None = None,
        result_entity_type: str | None = None,
        result_entity_id: int | None = None,
    ) -> HandlerResult:
        return cls(
            status=HandlerStatus.SUCCEEDED,
            provider_name=provider_name,
            provider_operation_id=provider_operation_id,
            result_entity_type=result_entity_type,
            result_entity_id=result_entity_id,
        )

    @classmethod
    def failed(
        cls,
        safe_error_code: str,
        *,
        safe_error_details: dict[str, object] | None = None,
    ) -> HandlerResult:
        return cls(
            status=HandlerStatus.FAILED,
            safe_error_code=safe_error_code,
            safe_error_details=safe_error_details or {},
        )

    @classmethod
    def submit_unknown(
        cls,
        safe_error_code: str,
        *,
        safe_error_details: dict[str, object] | None = None,
        provider_name: str | None = None,
        provider_operation_id: str | None = None,
    ) -> HandlerResult:
        return cls(
            status=HandlerStatus.SUBMIT_UNKNOWN,
            safe_error_code=safe_error_code,
            safe_error_details=safe_error_details or {},
            provider_name=provider_name,
            provider_operation_id=provider_operation_id,
        )


class ExecutionHandlerAdapter(Protocol):
    """Exact Job Type adapter contract; implementations must be pre-registered."""

    job_type: str
    input_schema: type[BaseModel]

    def execute(
        self, context: ExecutionContext, payload: BaseModel
    ) -> HandlerResult: ...
