import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.db.base import Base
from app.execution.handlers.qwen_video_script import QwenVideoScriptGenerateV1Handler
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    BatchVideoVariant,
    ExecutionAttempt,
    ExecutionJob,
    VideoScriptVersion,
)
from app.providers.base import TextGenerationProvider
from app.providers.live_configuration import (
    provider_error_from_metadata,
    provider_failure_metadata,
)
from app.schemas.video_script_version import (
    QwenScriptJobCreateRequest,
    QwenScriptPreflightRequest,
    QwenScriptProviderOutput,
)
from app.services.qwen_video_script_generation_service import (
    select_timed_narration,
    validate_timed_four_act_contract,
)
from app.services.qwen_video_script_job_service import QwenVideoScriptJobService
from app.services.qwen_video_script_preflight import QwenVideoScriptPreflightService
from app.services.video_script_version_service import VideoScriptVersionService
from tests.test_qwen_video_script_preflight import qwen_settings, strategy_for
from tests.test_video_script_preflight import ready_variant
from tests.test_video_script_versions import create_request

VALID_RESPONSE = json.dumps(
    {
        "title": "Generated title",
        "concept": "Generated concept",
        "hook": "Generated hook",
        "cta": "Generated CTA",
        "scenes": [
            {
                "sequence": 1,
                "start_ms": 0,
                "end_ms": 3000,
                "shot_type": "wide",
                "visual_description": "Show product",
                "action_description": "Move product",
                "narration": "Fresh smoothies travel wherever your day goes.",
                "subtitle_draft": "Fresh smoothies travel wherever your day goes.",
            },
            {
                "sequence": 2,
                "start_ms": 3000,
                "end_ms": 8000,
                "shot_type": "close",
                "visual_description": "Show active blending",
                "action_description": "Operate the sealed product",
                "narration": "Rechargeable power blends fruit smoothly without cords.",
                "subtitle_draft": (
                    "Rechargeable power blends fruit smoothly without cords."
                ),
            },
            {
                "sequence": 3,
                "start_ms": 8000,
                "end_ms": 12000,
                "shot_type": "proof",
                "visual_description": "Show easy cleaning",
                "action_description": "Rinse the product",
                "narration": "Quick rinsing keeps cleanup simple after blending.",
                "subtitle_draft": "Quick rinsing keeps cleanup simple after blending.",
            },
            {
                "sequence": 4,
                "start_ms": 12000,
                "end_ms": 15000,
                "shot_type": "hero",
                "visual_description": "Show final product",
                "action_description": "Present the call to action",
                "narration": "Choose portable freshness and blend anywhere today.",
                "subtitle_draft": "Choose portable freshness and blend anywhere today.",
            },
        ],
    }
)

OVER_BUDGET_RESPONSE = json.dumps(
    {
        "title": "Generated title",
        "concept": "Generated concept",
        "hook": "Generated hook",
        "cta": "Generated CTA",
        "scenes": [
            {
                "sequence": index,
                "start_ms": (index - 1) * 3000,
                "end_ms": index * 3000,
                "shot_type": "product",
                "visual_description": f"Scene {index}",
                "action_description": "Show the product",
                "narration": narration,
                "subtitle_draft": narration,
            }
            for index, narration in enumerate(
                (
                    "Fresh smoothies are ready wherever your day takes you.",
                    "Add your favorite fruit and a splash of water.",
                    "Press blend and watch the portable blender spring to life.",
                    "Enjoy smooth results with easy cleanup after every drink.",
                    "Grab yours today and blend fresh flavor anywhere.",
                ),
                1,
            )
        ],
    }
)


class FakeQwen(TextGenerationProvider):
    def __init__(
        self, response: str = VALID_RESPONSE, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.calls = 0
        self.prompt_digests: list[int] = []
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompt_digests.append(hash(prompt))
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


def test_over_budget_narration_is_rejected_without_dropping_scenes() -> None:
    output = QwenScriptProviderOutput.model_validate_json(OVER_BUDGET_RESPONSE)
    with pytest.raises(AppError, match="cannot fit"):
        select_timed_narration(output)


def test_four_act_contract_enforces_timeline_subtitles_and_word_budgets() -> None:
    output = QwenScriptProviderOutput.model_validate_json(VALID_RESPONSE)
    validate_timed_four_act_contract(output, english=True)
    assert len(select_timed_narration(output, min_words=24).split()) == 28

    under_budget = output.model_copy(deep=True)
    under_budget.scenes[0].narration = "Blend fresh drinks anywhere instantly."
    under_budget.scenes[0].subtitle_draft = under_budget.scenes[0].narration
    with pytest.raises(AppError, match="per-scene word budget"):
        validate_timed_four_act_contract(under_budget, english=True)

    wrong_timeline = output.model_copy(deep=True)
    wrong_timeline.scenes[0].end_ms = 2999
    with pytest.raises(AppError, match="timed four-act contract"):
        validate_timed_four_act_contract(wrong_timeline, english=True)

    mismatched_subtitle = output.model_copy(deep=True)
    mismatched_subtitle.scenes[0].subtitle_draft = "Different subtitle"
    with pytest.raises(AppError, match="subtitles must match narration"):
        validate_timed_four_act_contract(mismatched_subtitle, english=True)


def enqueue(session, variant, strategy, settings, key: str):
    request = QwenScriptPreflightRequest(
        idempotency_key=key,
        strategy_id=strategy.id,
        copy_matrix_id=None,
        parent_version_id=variant.active_script_version_id,
    )
    checked = QwenVideoScriptPreflightService(session, settings).run(
        variant.id, request
    )
    payload = QwenScriptJobCreateRequest(
        **request.model_dump(),
        frozen_input_digest=checked.frozen_input_digest,
        preflight_digest=checked.preflight_digest,
        preflight_expires_at=checked.expires_at,
        estimated_cost_min=checked.estimated_cost_min,
        estimated_cost_max=checked.estimated_cost_max,
        currency=checked.currency,
        cost_estimate_basis=checked.cost_estimate_basis,
        cost_confirmed=True,
    )
    return QwenVideoScriptJobService(session, settings).enqueue(
        variant.id, payload
    ), payload


def worker(factory, provider, settings) -> ExecutionWorker:
    registry = ExecutionHandlerRegistry()
    registry.register(
        QwenVideoScriptGenerateV1Handler(
            session_factory=factory, provider=provider, settings=settings
        )
    )
    return ExecutionWorker(
        session_factory=factory,
        registry=registry,
        worker_id="qwen-script-worker",
        heartbeat_interval_seconds=0.1,
    )


def test_worker_is_unique_provider_boundary_and_creates_immutable_unreviewed_version(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'qwen.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = qwen_settings()
    with factory() as session:
        variant = ready_variant(session)
        strategy = strategy_for(session, variant.product_id)
        manual = (
            VideoScriptVersionService(session)
            .create(
                variant.id, create_request(session, variant.id, key="manual-parent")
            )
            .version
        )
        VideoScriptVersionService(session).activate(variant.id, manual.id)
        created, payload = enqueue(session, variant, strategy, settings, "qwen-success")
        assert created.job.max_attempts == 1
        assert created.job.attempt_count == 0
        assert created.job.estimated_cost == Decimal("0.08")
        assert created.job.cost_confirmed is True
        job_id, variant_id, active_id = created.job.id, variant.id, manual.id
    fake = FakeQwen()
    execution_worker = worker(factory, fake, settings)
    assert fake.calls == 0
    assert execution_worker.run_once().status == WorkerRunStatus.SUCCEEDED
    assert fake.calls == 1
    assert "exactly 4 scenes" in fake.prompts[0]
    assert "scene 1 is the hook from 0 to 3000 ms" in fake.prompts[0]
    assert (
        "scene 2 actively operates the product from 3000 to 8000 ms" in fake.prompts[0]
    )
    assert "scene 3 visibly proves the remaining benefits" in fake.prompts[0]
    assert "scene 4 gives the CTA from 12000 to 15000 ms" in fake.prompts[0]
    assert "English narration in each scene must contain 6-8 words" in fake.prompts[0]
    assert "Count words before returning the JSON" in fake.prompts[0]
    assert execution_worker.run_once().status == WorkerRunStatus.NO_JOB
    with factory() as session:
        job = session.get(ExecutionJob, job_id)
        variant = session.get(BatchVideoVariant, variant_id)
        assert job is not None and variant is not None
        version = session.get(VideoScriptVersion, job.result_entity_id)
        assert job.status == "SUCCEEDED" and job.provider_name == "qwen"
        assert job.result_entity_type == "video_script_version"
        assert version is not None and version.id == job.result_entity_id
        assert (
            version.source_type,
            version.created_by_kind,
            version.review_status,
        ) == ("QWEN_GENERATED", "QWEN_PROVIDER", "UNREVIEWED")
        assert version.parent_version_id == active_id
        assert variant.active_script_version_id == active_id
        expected_narration = (
            "Fresh smoothies travel wherever your day goes. "
            "Rechargeable power blends fruit smoothly without cords. "
            "Quick rinsing keeps cleanup simple after blending. "
            "Choose portable freshness and blend anywhere today."
        )
        assert version.full_narration == expected_narration
        assert version.full_subtitle_draft == expected_narration
        assert [scene.subtitle_draft for scene in version.scenes] == [
            "Fresh smoothies travel wherever your day goes.",
            "Rechargeable power blends fruit smoothly without cords.",
            "Quick rinsing keeps cleanup simple after blending.",
            "Choose portable freshness and blend anywhere today.",
        ]
        assert version.source_execution_job_id == job.id
        attempt = session.query(ExecutionAttempt).one()
        assert (attempt.provider_call_count, attempt.provider_submission_state) == (
            1,
            "RESPONSE_RECEIVED",
        )
        reused = QwenVideoScriptJobService(session, settings).enqueue(
            variant_id, payload
        )
        assert reused.reused is True and reused.job.id == job_id
        assert session.query(ExecutionJob).count() == 1
        assert session.query(ExecutionAttempt).count() == 1
        assert session.query(VideoScriptVersion).count() == 2
    assert fake.calls == 1
    engine.dispose()


def test_invalid_response_explicit_failure_and_submit_unknown_never_retry(
    tmp_path,
) -> None:
    cases = (
        (FakeQwen(response='{"title":"bad"}'), "FAILED", "RESPONSE_RECEIVED"),
        (
            FakeQwen(
                error=provider_error_from_metadata(
                    provider_failure_metadata(
                        provider="qwen",
                        phase="response",
                        provider_code="permission_denied",
                        uncertain=False,
                        potentially_billable=False,
                    )
                )
            ),
            "FAILED",
            "EXPLICIT_FAILURE",
        ),
        (
            FakeQwen(
                error=provider_error_from_metadata(
                    provider_failure_metadata(
                        provider="qwen",
                        phase="response",
                        provider_code="response_uncertain",
                        uncertain=True,
                        potentially_billable=True,
                    )
                )
            ),
            "SUBMIT_UNKNOWN",
            "SUBMIT_UNKNOWN",
        ),
    )
    for index, (fake, expected_status, expected_submission) in enumerate(cases, 1):
        engine = create_engine(
            f"sqlite:///{(tmp_path / f'failure-{index}.db').as_posix()}"
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        settings = qwen_settings()
        with factory() as session:
            variant = ready_variant(session)
            strategy = strategy_for(session, variant.product_id)
            created, _ = enqueue(
                session, variant, strategy, settings, f"qwen-case-{index}"
            )
            job_id = created.job.id
        execution_worker = worker(factory, fake, settings)
        result = execution_worker.run_once()
        assert result.status.value == expected_status
        assert execution_worker.run_once().status == WorkerRunStatus.NO_JOB
        with factory() as session:
            job = session.get(ExecutionJob, job_id)
            attempt = session.query(ExecutionAttempt).one()
            assert job is not None and job.status == expected_status
            assert attempt.provider_submission_state == expected_submission
            assert attempt.provider_call_count == 1
            assert session.query(VideoScriptVersion).count() == 0
        assert fake.calls == 1
        engine.dispose()


def test_two_sessions_concurrent_enqueue_converges_without_duplicate_quota(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'enqueue-race.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = qwen_settings()
    with factory() as session:
        variant = ready_variant(session)
        strategy = strategy_for(session, variant.product_id)
        request = QwenScriptPreflightRequest(
            idempotency_key="qwen-concurrent-enqueue",
            strategy_id=strategy.id,
            copy_matrix_id=None,
            parent_version_id=None,
        )
        checked = QwenVideoScriptPreflightService(session, settings).run(
            variant.id, request
        )
        payload = QwenScriptJobCreateRequest(
            **request.model_dump(),
            frozen_input_digest=checked.frozen_input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            estimated_cost_min=checked.estimated_cost_min,
            estimated_cost_max=checked.estimated_cost_max,
            currency=checked.currency,
            cost_estimate_basis=checked.cost_estimate_basis,
            cost_confirmed=True,
        )
        variant_id = variant.id
    barrier = Barrier(2)

    def submit() -> tuple[int, bool]:
        with factory() as session:
            barrier.wait()
            result = QwenVideoScriptJobService(session, settings).enqueue(
                variant_id, payload
            )
            return result.job.id, result.reused

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result() for future in (pool.submit(submit), pool.submit(submit))
        ]
    assert len({result[0] for result in results}) == 1
    assert sorted(result[1] for result in results) == [False, True]
    with factory() as session:
        assert session.query(ExecutionJob).count() == 1
        variant = session.get(BatchVideoVariant, variant_id)
        assert variant is not None
        assert variant.batch.qwen_script_calls_reserved == 1
    engine.dispose()
