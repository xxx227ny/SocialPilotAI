from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.execution.handlers.batch_video_variant import BatchVideoVariantPrepareV1Handler
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    BatchVideoJob,
    BatchVideoVariant,
    ExecutionAttempt,
    ExecutionJob,
    Product,
)
from app.schemas.batch_video import BatchVideoCreateRequest, BatchVideoRequest
from app.services.batch_video_job_service import (
    BatchVideoJobService,
    aggregate_batch_status,
)
from app.services.batch_video_preflight import BatchVideoPreflightService


def _batch(session, name: str, key: str):
    product = Product(
        name=name,
        category="Test",
        description="Batch control fixture",
        selling_points=["Stable"],
        target_markets=["CN"],
    )
    session.add(product)
    session.commit()
    request = BatchVideoRequest(
        product_ids=[product.id],
        platforms=["youtube", "tiktok"],
        variants_per_platform=2,
        language="en-US",
        max_concurrency=2,
        idempotency_key=key,
    )
    checked = BatchVideoPreflightService(session).run(request)
    return BatchVideoJobService(session).create(
        BatchVideoCreateRequest(
            **request.model_dump(),
            request_digest=checked.request_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        )
    )


def test_pause_resume_cancel_are_idempotent_and_batch_scoped(db_session) -> None:
    first = _batch(db_session, "First", "batch-control-first")
    second = _batch(db_session, "Second", "batch-control-second")
    service = BatchVideoJobService(db_session)

    assert service.pause(first.batch.id).status == "PAUSED"
    assert service.pause(first.batch.id).status == "PAUSED"
    assert {v.status for v in service.list_variants(second.batch.id)} == {"WAITING"}
    assert service.resume(first.batch.id).status == "WAITING"
    assert service.resume(first.batch.id).status == "WAITING"
    assert service.cancel(first.batch.id).status == "CANCELLED"
    assert service.cancel(first.batch.id).status == "CANCELLED"
    assert {v.status for v in service.list_variants(first.batch.id)} == {"CANCELLED"}


def test_aggregation_reports_partial_failed_for_failed_and_cancelled_children(
    db_session,
) -> None:
    created = _batch(db_session, "Aggregate", "batch-control-aggregate")
    batch = db_session.get(BatchVideoJob, created.batch.id)
    jobs = (
        db_session.query(ExecutionJob)
        .filter(ExecutionJob.source_type == "batch_video_variant")
        .order_by(ExecutionJob.id)
        .all()
    )
    jobs[0].status = "FAILED"
    jobs[0].completed_at = jobs[0].created_at
    db_session.commit()
    db_session.refresh(batch)
    assert aggregate_batch_status(batch.variants) == "PARTIAL_FAILED"
    for job in jobs[1:]:
        job.status = "CANCELLED"
        job.completed_at = job.created_at
    db_session.commit()
    db_session.refresh(batch)
    assert aggregate_batch_status(batch.variants) == "PARTIAL_FAILED"


def test_idempotency_conflict_and_safe_not_found(db_session) -> None:
    created = _batch(db_session, "Identity", "batch-control-identity")
    product = Product(
        name="Other",
        category="Test",
        description="Different digest",
        selling_points=["Stable"],
        target_markets=[],
    )
    db_session.add(product)
    db_session.commit()
    request = BatchVideoRequest(
        product_ids=[product.id],
        platforms=["instagram"],
        variants_per_platform=1,
        language="en-US",
        max_concurrency=1,
        idempotency_key=created.batch.idempotency_key,
    )
    checked = BatchVideoPreflightService(db_session).run(request)
    with pytest.raises(AppError) as conflict:
        BatchVideoJobService(db_session).create(
            BatchVideoCreateRequest(
                **request.model_dump(),
                request_digest=checked.request_digest,
                preflight_digest=checked.preflight_digest,
                preflight_expires_at=checked.expires_at,
                cost_confirmed=True,
            )
        )
    assert conflict.value.status_code == 409
    with pytest.raises(AppError) as missing:
        BatchVideoJobService(db_session).get_batch(999999)
    assert missing.value.status_code == 404


def test_exact_id_api_create_recover_and_safe_404(client, db_session) -> None:
    product = Product(
        name="API product",
        category="Test",
        description="Exact API recovery",
        selling_points=["Stable"],
        target_markets=[],
    )
    db_session.add(product)
    db_session.commit()
    request = {
        "product_ids": [product.id],
        "platforms": ["youtube"],
        "variants_per_platform": 2,
        "duration_seconds": 15,
        "aspect_ratio": "9:16",
        "language": "en-US",
        "priority": 50,
        "max_concurrency": 1,
        "creative_angle": None,
        "idempotency_key": "batch-api-exact",
    }
    preflight = client.post("/api/v1/batch-video-jobs/preflight", json=request)
    assert preflight.status_code == 200
    checked = preflight.json()
    assert checked["current_stage_cost"] == "0"
    assert checked["cost_scope"] == "orchestration_only"
    assert checked["downstream_provider_cost_status"] == "NOT_ESTIMATED"
    created = client.post(
        "/api/v1/batch-video-jobs",
        json={
            **request,
            "request_digest": checked["request_digest"],
            "preflight_digest": checked["preflight_digest"],
            "preflight_expires_at": checked["expires_at"],
            "cost_confirmed": True,
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    batch_id = created_body["batch"]["id"]
    for response_batch in (
        created_body["batch"],
        client.get(f"/api/v1/batch-video-jobs/{batch_id}").json(),
    ):
        assert Decimal(response_batch["current_stage_cost"]) == Decimal("0")
        assert response_batch["cost_scope"] == "orchestration_only"
        assert response_batch["downstream_provider_cost_status"] == "NOT_ESTIMATED"
    variants = client.get(f"/api/v1/batch-video-jobs/{batch_id}/variants")
    assert variants.status_code == 200 and len(variants.json()) == 2
    expected_variant = variants.json()[0]
    exact_variant = client.get(f"/api/v1/batch-video-variants/{expected_variant['id']}")
    assert exact_variant.status_code == 200
    assert {
        key: exact_variant.json()[key]
        for key in (
            "id",
            "batch_video_job_id",
            "product_id",
            "platform",
            "variant_index",
            "execution_job_id",
        )
    } == {
        key: expected_variant[key]
        for key in (
            "id",
            "batch_video_job_id",
            "product_id",
            "platform",
            "variant_index",
            "execution_job_id",
        )
    }
    batch_missing = client.get("/api/v1/batch-video-jobs/999999")
    variant_missing = client.get("/api/v1/batch-video-variants/999999")
    assert batch_missing.status_code == variant_missing.status_code == 404
    assert batch_missing.json() == variant_missing.json()
    safe_body = batch_missing.text.casefold()
    assert all(
        forbidden not in safe_body
        for forbidden in ("sql", "select ", "path", "candidate", "user", "traceback")
    )


def test_batch_controls_gate_real_worker_and_preserve_terminal_history(
    db_session,
) -> None:
    first = _batch(db_session, "Controlled first", "batch-worker-control-first")
    second = _batch(db_session, "Independent second", "batch-worker-control-second")
    sessions = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    registry = ExecutionHandlerRegistry()
    registry.register(BatchVideoVariantPrepareV1Handler(session_factory=sessions))
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="batch-control-worker",
        lease_seconds=30,
        heartbeat_interval_seconds=1,
    )

    service = BatchVideoJobService(db_session)
    assert service.pause(first.batch.id).status == "PAUSED"
    assert service.pause(first.batch.id).status == "PAUSED"
    independent = worker.run_once()
    assert independent.status == WorkerRunStatus.SUCCEEDED
    independent_job = db_session.get(ExecutionJob, independent.job_id)
    independent_variant = db_session.get(BatchVideoVariant, independent_job.source_id)
    assert independent_variant.batch_video_job_id == second.batch.id

    assert service.resume(first.batch.id).status == "WAITING"
    assert service.resume(first.batch.id).status == "WAITING"
    completed = worker.run_once()
    assert completed.status == WorkerRunStatus.SUCCEEDED
    completed_job = db_session.get(ExecutionJob, completed.job_id)
    completed_variant = db_session.get(BatchVideoVariant, completed_job.source_id)
    assert completed_variant.batch_video_job_id == first.batch.id
    first_attempt_ids = [
        item.id
        for item in db_session.query(ExecutionAttempt)
        .filter(ExecutionAttempt.execution_job_id == completed_job.id)
        .all()
    ]
    assert len(first_attempt_ids) == 1

    service.pause(first.batch.id)
    service.cancel(first.batch.id)
    service.resume(first.batch.id)
    service.pause(first.batch.id)
    jobs = (
        db_session.query(ExecutionJob)
        .join(BatchVideoVariant, BatchVideoVariant.execution_job_id == ExecutionJob.id)
        .filter(BatchVideoVariant.batch_video_job_id == first.batch.id)
        .order_by(ExecutionJob.id)
        .all()
    )
    assert sum(item.status == "SUCCEEDED" for item in jobs) == 1
    assert sum(item.status == "CANCELLED" for item in jobs) == 3
    assert [
        item.id
        for item in db_session.query(ExecutionAttempt)
        .filter(ExecutionAttempt.execution_job_id == completed_job.id)
        .all()
    ] == first_attempt_ids
    assert (
        db_session.query(BatchVideoVariant)
        .filter_by(batch_video_job_id=first.batch.id)
        .count()
        == 4
    )
    assert (
        db_session.query(ExecutionJob)
        .filter(ExecutionJob.id.in_([item.execution_job_id for item in first.variants]))
        .count()
        == 4
    )
    second_statuses = {item.status for item in service.list_variants(second.batch.id)}
    assert second_statuses == {"WAITING", "READY_FOR_SCRIPT"}
