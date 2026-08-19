from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
)


def reject_sensitive_keys(value: object) -> object:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9_]", "", str(key).casefold())
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                raise ValueError("Sensitive keys are not allowed in persisted fields")
            reject_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            reject_sensitive_keys(nested)
    return value


SafeErrorCode = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]
ProviderSubmissionState = Literal[
    "NOT_STARTED",
    "NOT_SUBMITTED",
    "EXPLICIT_FAILURE",
    "RESPONSE_RECEIVED",
    "SUBMIT_UNKNOWN",
]


class ExecutionJobCreate(BaseModel):
    job_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    source_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    source_id: int = Field(gt=0)
    input_digest: Digest
    idempotency_key: str = Field(min_length=8, max_length=200)
    input_payload: dict[str, object] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=0, le=1_000_000)
    concurrency_key: str | None = Field(default=None, min_length=1, max_length=200)
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14)
    currency: str = Field(default="USD", pattern=r"^[A-Za-z]{3}$")
    cost_confirmed: bool = False
    max_attempts: int = Field(default=1, ge=1, le=100)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class ExecutionAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_job_id: int
    attempt_number: int
    status: str
    started_at: datetime
    completed_at: datetime | None
    safe_error_code: str | None
    safe_error_details: dict[str, object] | None
    provider_call_count: int
    external_submission_possible: bool
    provider_submission_state: ProviderSubmissionState


class ExecutionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    source_type: str
    source_id: int
    input_digest: str
    idempotency_key: str
    input_payload: dict[str, object]
    priority: int
    concurrency_key: str | None
    estimated_cost: Decimal
    currency: str
    cost_confirmed: bool
    status: str
    attempt_count: int
    max_attempts: int
    lease_active: bool
    provider_name: str | None
    provider_operation_id: str | None
    result_entity_type: str | None
    result_entity_id: int | None
    submitted_at: datetime | None
    completed_at: datetime | None
    safe_error_code: str | None
    safe_error_details: dict[str, object] | None
    uncertain: bool
    created_at: datetime
    updated_at: datetime
    attempts: list[ExecutionAttemptRead] = Field(default_factory=list)


class ExecutionJobCreateRead(BaseModel):
    job: ExecutionJobRead
    reused: bool


class WorkerLeaseRequest(BaseModel):
    worker_id: str = Field(min_length=8, max_length=500)
    lease_seconds: int = Field(default=60, ge=5, le=3600)


class ExecutionJobClaimRequest(WorkerLeaseRequest):
    job_types: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("job_types")
    @classmethod
    def normalize_job_types(cls, values: list[str]) -> list[str]:
        return sorted({value.strip().casefold() for value in values if value.strip()})


class ExecutionJobClaimRead(BaseModel):
    job: ExecutionJobRead | None


class ExecutionJobHeartbeatRequest(WorkerLeaseRequest):
    provider_call_count: int | None = Field(default=None, ge=0)
    external_submission_possible: bool = False


class ExecutionJobCompleteRequest(BaseModel):
    worker_id: str = Field(min_length=8, max_length=500)
    provider_name: str | None = Field(default=None, min_length=1, max_length=80)
    provider_operation_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )
    provider_call_count: int = Field(default=0, ge=0)
    result_entity_type: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$"
    )
    result_entity_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_result_reference_pair(self) -> ExecutionJobCompleteRequest:
        if (self.result_entity_type is None) != (self.result_entity_id is None):
            raise ValueError("Result entity type and ID must be supplied together")
        return self


class ExecutionJobFailRequest(BaseModel):
    worker_id: str = Field(min_length=8, max_length=500)
    safe_error_code: SafeErrorCode
    safe_error_details: dict[str, object] = Field(default_factory=dict)
    provider_call_count: int = Field(default=0, ge=0)
    external_submission_possible: bool = False
    provider_submission_state: Literal[
        "NOT_STARTED", "NOT_SUBMITTED", "EXPLICIT_FAILURE", "RESPONSE_RECEIVED"
    ] = "NOT_STARTED"


class ExecutionJobUnknownRequest(ExecutionJobFailRequest):
    external_submission_possible: Literal[True] = True
    provider_submission_state: Literal["SUBMIT_UNKNOWN"] = "SUBMIT_UNKNOWN"
    provider_name: str | None = Field(default=None, min_length=1, max_length=80)
    provider_operation_id: str | None = Field(
        default=None, min_length=1, max_length=255
    )


class ExecutionJobRetryRequest(BaseModel):
    retry_confirmed: Literal[True]
