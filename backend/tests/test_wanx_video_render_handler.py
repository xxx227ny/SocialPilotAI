from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.execution.handlers.wanx_video_render import (
    WANX_VIDEO_RENDER_REFRESH_V1,
    WANX_VIDEO_RENDER_SUBMIT_V1,
    WanxVideoRenderRefreshV1Handler,
    WanxVideoRenderSubmitV1Handler,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import ExecutionJob, VideoRenderArtifact, VideoRenderTask
from app.providers.visual_base import VisualTaskSnapshot
from app.schemas.video_render import (
    VideoRenderRefreshJobRequest,
    VideoRenderSubmitJobRequest,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_render_job_service import VideoRenderJobService
from app.services.video_render_preflight import VideoRenderPreflightService
from tests.test_video_render_execution_service import (
    FakeOutputFetcher,
    MockVisualProvider,
)
from tests.test_video_render_service import create_video_project


def render_settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_render_execution=True,
        wanx_api_key="fake-wanx-handler-key",
        wanx_workspace_id="fake-workspace",
        wanx_region="cn-beijing",
        video_artifact_storage_root=str(root.resolve()),
        video_artifact_max_bytes=1_000_000,
    )


def registry(
    sessions: sessionmaker[Session],
    provider: MockVisualProvider,
    settings: Settings,
    fetcher: FakeOutputFetcher,
) -> ExecutionHandlerRegistry:
    result = ExecutionHandlerRegistry()
    common = {
        "session_factory": sessions,
        "provider": provider,
        "settings": settings,
        "output_fetcher": fetcher,
        "artifact_storage": LocalVideoArtifactStorage(
            Path(settings.video_artifact_storage_root), 1_000_000
        ),
    }
    result.register(WanxVideoRenderSubmitV1Handler(**common))
    result.register(WanxVideoRenderRefreshV1Handler(**common))
    return result


def enqueue_submit(
    session: Session, settings: Settings, project_id: int
) -> int:
    checked = VideoRenderPreflightService(session, settings).run(project_id)
    created = VideoRenderJobService(session, settings).enqueue_submit(
        project_id,
        VideoRenderSubmitJobRequest(
            product_id=checked.product_id,
            marketing_strategy_id=checked.marketing_strategy_id,
            copy_matrix_id=checked.copy_matrix_id,
            input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        ),
    )
    return created.job.id


def test_submit_and_refresh_handlers_call_fake_wanx_exactly_once(
    db_session: Session, tmp_path: Path
) -> None:
    project = create_video_project(db_session)
    settings = render_settings(tmp_path)
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    provider = MockVisualProvider(
        snapshots=[
            VisualTaskSnapshot(
                provider_task_id="provider-task-001",
                status="SUCCEEDED",
                provider_output_url="https://provider.example/video.mp4",
            )
        ]
    )
    fetcher = FakeOutputFetcher(content=b"fake-video-render-bytes")
    submit_job_id = enqueue_submit(db_session, settings, project.id)
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry(sessions, provider, settings, fetcher),
        worker_id="wanx-handler-worker",
        heartbeat_interval_seconds=0.1,
    )

    assert worker.run_once().status == WorkerRunStatus.SUCCEEDED
    submit_job = db_session.get(ExecutionJob, submit_job_id)
    assert submit_job is not None
    assert submit_job.job_type == WANX_VIDEO_RENDER_SUBMIT_V1
    assert submit_job.result_entity_type == "video_render_task"
    task = db_session.get(VideoRenderTask, submit_job.result_entity_id)
    assert task is not None
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 0

    refresh = VideoRenderJobService(db_session, settings).enqueue_refresh(
        task.id,
        VideoRenderRefreshJobRequest(
            video_project_id=project.id,
            refresh_request_id="refresh-request-0001",
        ),
    )
    assert worker.run_once().status == WorkerRunStatus.SUCCEEDED
    db_session.expire_all()
    refresh_job = db_session.get(ExecutionJob, refresh.job.id)
    assert refresh_job is not None
    assert refresh_job.job_type == WANX_VIDEO_RENDER_REFRESH_V1
    assert refresh_job.result_entity_type == "video_render_artifact"
    artifact = db_session.get(
        VideoRenderArtifact, refresh_job.result_entity_id
    )
    assert artifact is not None
    assert artifact.artifact_metadata["sha256"]
    assert artifact.artifact_metadata["size_bytes"] == len(
        b"fake-video-render-bytes"
    )
    assert artifact.artifact_metadata["content_type"] == "video/mp4"
    assert ".." not in (artifact.storage_path or "")
    assert provider.submit_calls == 1
    assert provider.fetch_calls == 1
    assert fetcher.calls == 1
    repeated = VideoRenderJobService(db_session, settings).enqueue_refresh(
        task.id,
        VideoRenderRefreshJobRequest(
            video_project_id=project.id,
            refresh_request_id="refresh-request-0001",
        ),
    )
    assert repeated.reused is True
    assert repeated.job.id == refresh.job.id
    assert provider.fetch_calls == 1


def test_frozen_source_change_fails_before_wanx(
    db_session: Session, tmp_path: Path
) -> None:
    project = create_video_project(db_session)
    settings = render_settings(tmp_path)
    job_id = enqueue_submit(db_session, settings, project.id)
    project.title = "Changed after enqueue"
    db_session.commit()
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    provider = MockVisualProvider()
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry(
            sessions, provider, settings, FakeOutputFetcher()
        ),
        worker_id="wanx-frozen-worker",
        heartbeat_interval_seconds=0.1,
    )

    assert worker.run_once().status == WorkerRunStatus.FAILED
    db_session.expire_all()
    job = db_session.get(ExecutionJob, job_id)
    assert job is not None
    assert job.safe_error_code == "VIDEO_RENDER_FROZEN_DIGEST_MISMATCH"
    assert provider.submit_calls == 0
    assert provider.fetch_calls == 0
