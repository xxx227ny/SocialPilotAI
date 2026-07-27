import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import VideoRenderArtifact
from app.providers.base import ProviderConnectionError
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_service import create_video_project, render_request


class MockVisualProvider(VisualGenerationProvider):
    def __init__(
        self,
        *,
        submission: VisualTaskSubmission | None = None,
        snapshots: list[VisualTaskSnapshot] | None = None,
        submit_error: Exception | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.submission = submission or VisualTaskSubmission(
            provider_task_id="provider-task-001",
            provider_request_id="provider-request-001",
            status="PENDING",
        )
        self.snapshots = list(snapshots or [])
        self.submit_error = submit_error
        self.fetch_error = fetch_error
        self.submit_calls = 0
        self.fetch_calls = 0
        self.last_request: VisualGenerationRequest | None = None

    async def submit(
        self, request: VisualGenerationRequest
    ) -> VisualTaskSubmission:
        self.submit_calls += 1
        self.last_request = request
        if self.submit_error is not None:
            raise self.submit_error
        return self.submission

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        self.fetch_calls += 1
        if self.fetch_error is not None:
            raise self.fetch_error
        if not self.snapshots:
            raise AssertionError("Mock provider has no fetch snapshot")
        snapshot = self.snapshots.pop(0)
        assert snapshot.provider_task_id == provider_task_id
        return snapshot


def enabled_render_settings() -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=True,
    )


def execution_service(
    db_session: Session,
    provider: MockVisualProvider,
) -> VideoRenderExecutionService:
    return VideoRenderExecutionService(
        db_session,
        provider,
        enabled_render_settings(),
    )


def create_render_task(db_session: Session):
    project = create_video_project(db_session)
    return VideoRenderService(db_session).create_render_task(
        project.id, render_request()
    )


def test_service_gate_blocks_submit_and_refresh_before_provider(
    db_session: Session,
) -> None:
    task = create_render_task(db_session)
    provider = MockVisualProvider()
    service = VideoRenderExecutionService(
        db_session,
        provider,
        Settings(_env_file=None),
    )

    for operation in (service.submit, service.refresh):
        try:
            asyncio.run(operation(task.id))
        except AppError as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError("disabled service execution must fail closed")

    db_session.refresh(task)
    assert task.status == "CREATED"
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0


def submit_task(
    db_session: Session, provider: MockVisualProvider
):
    task = create_render_task(db_session)
    result = asyncio.run(
        execution_service(db_session, provider).submit(task.id)
    )
    return task, result


def test_submit_saves_provider_result(db_session: Session) -> None:
    provider = MockVisualProvider()
    task, result = submit_task(db_session, provider)

    assert provider.submit_calls == 1
    assert provider.last_request is not None
    assert provider.last_request.prompt == task.render_prompt
    assert result.task.status == "PENDING"
    assert result.task.provider_name == "mockvisual"
    assert result.task.provider_task_id == "provider-task-001"
    assert result.external_call is True


def test_duplicate_submit_is_rejected(db_session: Session) -> None:
    provider = MockVisualProvider()
    task, _ = submit_task(db_session, provider)

    try:
        asyncio.run(
            execution_service(db_session, provider).submit(task.id)
        )
    except AppError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("a submitted task must not be submitted twice")

    assert provider.submit_calls == 1


def test_non_created_task_is_rejected(db_session: Session) -> None:
    task = create_render_task(db_session)
    VideoRenderService(db_session).transition_status(task.id, "CANCELED")
    provider = MockVisualProvider()

    try:
        asyncio.run(
            execution_service(db_session, provider).submit(task.id)
        )
    except AppError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("only CREATED tasks can be submitted")

    assert provider.submit_calls == 0


def test_submit_provider_error_is_safe_and_persisted(
    db_session: Session,
) -> None:
    task = create_render_task(db_session)
    provider = MockVisualProvider(
        submit_error=ProviderConnectionError("sensitive upstream detail")
    )

    try:
        asyncio.run(
            execution_service(db_session, provider).submit(task.id)
        )
    except AppError as exc:
        assert exc.status_code == 502
        assert exc.message == "Visual generation provider request failed"
        assert "sensitive" not in exc.message
    else:
        raise AssertionError("provider failures must be converted to AppError")

    db_session.refresh(task)
    assert task.status == "FAILED"
    assert task.error_code == "PROVIDER_SUBMIT_ERROR"
    assert "sensitive" not in (task.error_message or "")


def test_refresh_running_status(db_session: Session) -> None:
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001", status="RUNNING"
            )
        ]
    )
    task, _ = submit_task(db_session, provider)

    result = asyncio.run(
        execution_service(db_session, provider).refresh(task.id)
    )

    assert result.task.status == "RUNNING"
    assert result.artifact is None
    assert provider.fetch_calls == 1


def test_refresh_succeeded_creates_artifact(db_session: Session) -> None:
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                provider_request_id="fetch-request-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
                metadata={"usage": {"duration": 4}},
            )
        ]
    )
    task, _ = submit_task(db_session, provider)

    result = asyncio.run(
        execution_service(db_session, provider).refresh(task.id)
    )

    assert result.task.status == "SUCCEEDED"
    assert result.artifact is not None
    assert result.artifact.provider_output_url == (
        "https://provider.example/video.mp4"
    )
    assert result.artifact.artifact_metadata["provider_request_id"] == (
        "fetch-request-001"
    )


def test_refresh_failed_saves_provider_error(db_session: Session) -> None:
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="FAILED",
                error_code="CONTENT_REJECTED",
                error_message="The content policy rejected the task",
            )
        ]
    )
    task, _ = submit_task(db_session, provider)

    result = asyncio.run(
        execution_service(db_session, provider).refresh(task.id)
    )

    assert result.task.status == "FAILED"
    assert result.task.error_code == "CONTENT_REJECTED"
    assert result.task.error_message == "The content policy rejected the task"
    assert result.artifact is None


def test_refresh_succeeded_is_idempotent(db_session: Session) -> None:
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
            )
        ]
    )
    task, _ = submit_task(db_session, provider)
    service = execution_service(db_session, provider)

    first = asyncio.run(service.refresh(task.id))
    second = asyncio.run(service.refresh(task.id))

    assert first.artifact is not None
    assert second.artifact is not None
    assert first.artifact.id == second.artifact.id
    assert second.external_call is False
    assert provider.fetch_calls == 1
    assert (
        db_session.scalar(
            select(func.count()).select_from(VideoRenderArtifact)
        )
        == 1
    )
