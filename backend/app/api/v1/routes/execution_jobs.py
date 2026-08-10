from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.session import get_db
from app.execution.handlers.qwen_copy_matrix import QWEN_COPY_MATRIX_GENERATE_V1
from app.execution.handlers.qwen_strategy import QWEN_STRATEGY_GENERATE_V1
from app.execution.handlers.qwen_video_project import (
    QWEN_VIDEO_PROJECT_GENERATE_V1,
)
from app.schemas.execution import (
    ExecutionJobClaimRead,
    ExecutionJobClaimRequest,
    ExecutionJobCompleteRequest,
    ExecutionJobCreate,
    ExecutionJobCreateRead,
    ExecutionJobFailRequest,
    ExecutionJobHeartbeatRequest,
    ExecutionJobRead,
    ExecutionJobRetryRequest,
    ExecutionJobUnknownRequest,
)
from app.services.execution_queue_service import ExecutionQueueService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/execution-jobs",
    response_model=ExecutionJobCreateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_job(
    data: ExecutionJobCreate, db: DbSession
) -> ExecutionJobCreateRead:
    if data.job_type in {
        QWEN_STRATEGY_GENERATE_V1,
        QWEN_COPY_MATRIX_GENERATE_V1,
        QWEN_VIDEO_PROJECT_GENERATE_V1,
    }:
        raise AppError(
            "Qwen jobs must use their confirmed business enqueue endpoint",
            409,
        )
    return ExecutionQueueService(db).create(data)


@router.get("/execution-jobs", response_model=list[ExecutionJobRead])
def list_execution_jobs(
    db: DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    job_type: str | None = None,
    source_type: str | None = None,
    source_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[ExecutionJobRead]:
    return ExecutionQueueService(db).list(
        status=status_filter,
        job_type=job_type,
        source_type=source_type,
        source_id=source_id,
    )


@router.post("/execution-jobs/claim", response_model=ExecutionJobClaimRead)
def claim_execution_job(
    data: ExecutionJobClaimRequest, db: DbSession
) -> ExecutionJobClaimRead:
    return ExecutionJobClaimRead(job=ExecutionQueueService(db).claim(data))


@router.get("/execution-jobs/{job_id}", response_model=ExecutionJobRead)
def get_execution_job(job_id: int, db: DbSession) -> ExecutionJobRead:
    return ExecutionQueueService(db).get(job_id)


@router.post("/execution-jobs/{job_id}/pause", response_model=ExecutionJobRead)
def pause_execution_job(job_id: int, db: DbSession) -> ExecutionJobRead:
    return ExecutionQueueService(db).pause(job_id)


@router.post("/execution-jobs/{job_id}/resume", response_model=ExecutionJobRead)
def resume_execution_job(job_id: int, db: DbSession) -> ExecutionJobRead:
    return ExecutionQueueService(db).resume(job_id)


@router.post("/execution-jobs/{job_id}/cancel", response_model=ExecutionJobRead)
def cancel_execution_job(job_id: int, db: DbSession) -> ExecutionJobRead:
    return ExecutionQueueService(db).cancel(job_id)


@router.post("/execution-jobs/{job_id}/retry", response_model=ExecutionJobRead)
def retry_execution_job(
    job_id: int, data: ExecutionJobRetryRequest, db: DbSession
) -> ExecutionJobRead:
    return ExecutionQueueService(db).retry(job_id, data)


@router.post("/execution-jobs/{job_id}/heartbeat", response_model=ExecutionJobRead)
def heartbeat_execution_job(
    job_id: int, data: ExecutionJobHeartbeatRequest, db: DbSession
) -> ExecutionJobRead:
    return ExecutionQueueService(db).heartbeat(job_id, data)


@router.post("/execution-jobs/{job_id}/complete", response_model=ExecutionJobRead)
def complete_execution_job(
    job_id: int, data: ExecutionJobCompleteRequest, db: DbSession
) -> ExecutionJobRead:
    return ExecutionQueueService(db).complete(job_id, data)


@router.post("/execution-jobs/{job_id}/fail", response_model=ExecutionJobRead)
def fail_execution_job(
    job_id: int, data: ExecutionJobFailRequest, db: DbSession
) -> ExecutionJobRead:
    return ExecutionQueueService(db).fail(job_id, data)


@router.post(
    "/execution-jobs/{job_id}/mark-submit-unknown",
    response_model=ExecutionJobRead,
)
def mark_execution_job_submit_unknown(
    job_id: int, data: ExecutionJobUnknownRequest, db: DbSession
) -> ExecutionJobRead:
    return ExecutionQueueService(db).mark_submit_unknown(job_id, data)
