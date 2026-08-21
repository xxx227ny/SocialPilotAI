from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    CopyMatrix,
    ExecutionAttempt,
    ExecutionJob,
    MarketingBrief,
    MarketingStrategy,
    Product,
)
from app.providers import TextGenerationProvider
from app.providers.live_configuration import effective_qwen_api_key
from app.providers.qwen_provider import QwenProvider
from app.schemas.copy import CopyJobEnqueueRequest, CopyMatrixSchema
from app.services.copy_generation_service import CopyGenerationService
from app.services.copy_job_service import CopyJobService
from app.services.copy_preflight import CopyPreflightService

pytestmark = [pytest.mark.smoke, pytest.mark.qwen_smoke]

PLATFORMS = ["TikTok", "Instagram", "Facebook", "Pinterest"]


def _new_path(name: str) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value)
    if not value or not path.is_absolute() or not path.parent.is_dir():
        pytest.fail(f"{name} must be in an existing absolute directory")
    if path.exists():
        pytest.fail(f"{name} must point to a new file")
    return path


class _CountingQwen(TextGenerationProvider):
    def __init__(self) -> None:
        self.provider = QwenProvider(settings)
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        assert self.calls == 1
        return self.provider.generate(prompt)


def test_qwen_real_four_platform_copy_matrix() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    output_path = _new_path("QWEN_COPY_MATRIX_OUTPUT")
    product = Product(
        id=1,
        name="Fictional teal portable blender",
        category="Portable kitchen appliance",
        description="A cordless blender for fresh drinks away from home.",
        selling_points=[
            "portable design",
            "rechargeable power",
            "easy cleaning",
        ],
        target_markets=["US"],
    )
    strategy = MarketingStrategy(
        id=1,
        product_id=1,
        positioning="Fresh smoothies anywhere in seconds",
        audience_insights=["Busy commuters value convenience and easy cleanup"],
        angles=["Portable fresh-drink routine", "Rechargeable everyday convenience"],
        risks=["Do not make medical, weight-loss, or unsupported performance claims"],
        evidence=["Portable", "Rechargeable", "Easy to clean"],
    )

    provider = QwenProvider(settings)
    raw = provider.generate(CopyGenerationService._build_prompt(product, strategy))
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    parsed["product_id"] = product.id
    matrix = CopyMatrixSchema.model_validate(parsed)
    assert [copy.platform for copy in matrix.copies] == PLATFORMS
    assert len({copy.caption.casefold() for copy in matrix.copies}) == 4
    assert len({copy.hook.casefold() for copy in matrix.copies}) == 4
    assert all(copy.hashtags for copy in matrix.copies)

    output_path.write_text(
        json.dumps(
            {
                "product": product.name,
                "provider_model": settings.qwen_model,
                "copies": [copy.model_dump() for copy in matrix.copies],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "provider_calls": 1,
                "platforms": PLATFORMS,
                "caption_lengths": [len(copy.caption) for copy in matrix.copies],
            },
            sort_keys=True,
        )
    )


def test_qwen_real_copy_queue_worker_and_persistence() -> None:
    if not effective_qwen_api_key(settings):
        pytest.skip("Token Plan credentials are not configured")
    output_path = _new_path("QWEN_COPY_QUEUE_OUTPUT")
    database_path = _new_path("QWEN_COPY_QUEUE_DATABASE")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    live_settings = settings.model_copy(update={"enable_copy_execution": True})
    with sessions() as session:
        product = Product(
            name="Fictional teal portable blender",
            category="Portable kitchen appliance",
            description="A cordless blender for fresh drinks away from home.",
            selling_points=["Portable", "Rechargeable", "Easy to clean"],
            target_markets=["US"],
        )
        session.add(product)
        session.flush()
        brief = MarketingBrief(
            product_id=product.id,
            audience="Target markets [US]. Busy commuters",
            language="English",
            platforms=PLATFORMS,
            tone="Clear, energetic, and practical",
            objective="Generate a four-platform launch copy matrix",
        )
        strategy = MarketingStrategy(
            product_id=product.id,
            positioning="Fresh smoothies anywhere in seconds",
            audience_insights=["Busy commuters value convenience"],
            angles=["Portable fresh-drink routine"],
            risks=["No unsupported claims"],
            evidence=["Portable", "Rechargeable", "Easy to clean"],
        )
        session.add_all([brief, strategy])
        session.commit()
        checked = CopyPreflightService(session, live_settings).run(
            brief.id, strategy.id
        )
        assert checked.ready_for_execution is True
        created = CopyJobService(session, live_settings).enqueue(
            brief.id,
            strategy.id,
            CopyJobEnqueueRequest(
                product_id=product.id,
                strategy_id=strategy.id,
                input_digest=checked.input_digest,
                preflight_digest=checked.preflight_digest,
                preflight_expires_at=checked.expires_at,
                cost_confirmed=True,
            ),
        )
        assert created.job.max_attempts == 1
        assert created.job.estimated_cost == live_settings.qwen_copy_estimated_cost
        job_id, product_id, brief_id, strategy_id = (
            created.job.id,
            product.id,
            brief.id,
            strategy.id,
        )

    provider = _CountingQwen()
    registry = build_execution_handler_registry(
        session_factory=sessions,
        settings=live_settings,
        qwen_provider_factory=lambda _: provider,
    )
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="real-qwen-copy-worker",
        heartbeat_interval_seconds=0.1,
    )
    assert worker.run_once().status == WorkerRunStatus.SUCCEEDED
    assert worker.run_once().status == WorkerRunStatus.NO_JOB
    assert provider.calls == 1

    with sessions() as session:
        job = session.get(ExecutionJob, job_id)
        assert job is not None and job.status == "SUCCEEDED"
        assert job.result_entity_type == "copy_matrix"
        matrix = session.get(CopyMatrix, job.result_entity_id)
        attempt = session.query(ExecutionAttempt).one()
        assert matrix is not None
        assert matrix.product_id == product_id
        assert matrix.marketing_strategy_id == strategy_id
        assert [copy["platform"] for copy in matrix.copies] == PLATFORMS
        assert attempt.provider_call_count == 1
        assert attempt.provider_submission_state == "RESPONSE_RECEIVED"
        evidence = {
            "provider_calls": provider.calls,
            "product_id": product_id,
            "marketing_brief_id": brief_id,
            "marketing_strategy_id": strategy_id,
            "job_id": job.id,
            "job_status": job.status,
            "attempt_id": attempt.id,
            "attempt_status": attempt.status,
            "max_attempts": job.max_attempts,
            "estimated_cost": str(job.estimated_cost),
            "currency": job.currency,
            "copy_matrix_id": matrix.id,
            "result_entity_id": job.result_entity_id,
            "copies": matrix.copies,
        }
    output_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine.dispose()
    print(
        json.dumps(
            {
                "provider_calls": provider.calls,
                "job_status": evidence["job_status"],
                "platforms": PLATFORMS,
                "copy_matrix_id": evidence["copy_matrix_id"],
            },
            sort_keys=True,
        )
    )
