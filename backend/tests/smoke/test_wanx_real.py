import asyncio
import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.models import VideoRenderArtifact, VideoRenderTask
from app.providers.live_configuration import effective_wanx_api_key
from app.providers.visual_base import VisualGenerationRequest
from app.providers.wanx_provider import WANX_REGION_HOSTS, WanxProvider
from app.services.video_render_execution_service import (
    VideoRenderExecutionService,
)
from tests.test_video_render_service import create_video_project

pytestmark = [pytest.mark.smoke, pytest.mark.wanx_smoke]

PROMPT = """Create a 3-second 9:16 social video scene.
Macro close-up of fruit dropping into a compact blender.
Three rapid ingredient cuts.
Keep the product visually consistent.
Do not add subtitles, on-screen text, logos, or audio."""
POLL_INTERVAL_SECONDS = 15
MAX_WAIT_SECONDS = 5 * 60


def _require_wanx_configuration() -> None:
    if not effective_wanx_api_key(settings):
        pytest.skip("WANX_API_KEY is not configured")
    if settings.wanx_endpoint:
        return
    workspace_id = (settings.wanx_workspace_id or "").strip()
    if not workspace_id:
        pytest.skip("WANX_ENDPOINT or WANX_WORKSPACE_ID is not configured")
    if settings.wanx_region not in WANX_REGION_HOSTS:
        pytest.skip("WANX_REGION is not supported by the configured provider")


def _create_render_task(db_session: Session) -> VideoRenderTask:
    project = create_video_project(db_session)
    project.duration_seconds = 3
    project.aspect_ratio = "9:16"
    project.scenes = [
        {
            "sequence": 1,
            "duration_seconds": 3,
            "shot_type": "Macro close-up",
            "visual_description": ("Fruit dropping into a compact blender."),
            "action": "Three rapid ingredient cuts.",
            "narration": "No audio.",
        }
    ]
    task = VideoRenderTask(
        video_project_id=project.id,
        scene_sequence=1,
        status="CREATED",
        provider_name=None,
        provider_task_id=None,
        render_prompt=PROMPT,
        duration_seconds=3,
        aspect_ratio="9:16",
        resolution="720P",
        idempotency_key="wanx-real-smoke-c3-d-2",
        error_code=None,
        error_message=None,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


async def _execute_real_smoke(db_session: Session) -> None:
    provider = WanxProvider()
    original_submit = provider.submit
    submit_calls = 0
    fetch_calls = 0

    async def submit_once(
        request: VisualGenerationRequest,
    ):
        nonlocal submit_calls
        submit_calls += 1
        if submit_calls > 1:
            raise AssertionError("Wanx smoke attempted more than one submit")
        return await original_submit(request)

    original_fetch = provider.fetch

    async def counted_fetch(provider_task_id: str):
        nonlocal fetch_calls
        fetch_calls += 1
        return await original_fetch(provider_task_id)

    provider.submit = submit_once  # type: ignore[method-assign]
    provider.fetch = counted_fetch  # type: ignore[method-assign]
    task = _create_render_task(db_session)
    service = VideoRenderExecutionService(db_session, provider)
    started = time.monotonic()

    try:
        submission = await service.submit(task.id)
    except AppError as exc:
        db_session.refresh(task)
        category = task.error_code or "WANX_SUBMIT_APP_ERROR"
        pytest.fail(
            f"Wanx submit failed: category={category}, http_status={exc.status_code}"
        )

    assert submit_calls == 1
    assert submission.external_call is True
    assert submission.task.provider_task_id
    assert submission.task.status in {"SUBMITTED", "PENDING", "RUNNING"}
    provider_task_id = submission.task.provider_task_id
    statuses = [submission.task.status]
    deadline = started + MAX_WAIT_SECONDS

    while time.monotonic() < deadline:
        await asyncio.sleep(min(POLL_INTERVAL_SECONDS, deadline - time.monotonic()))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = await asyncio.wait_for(service.refresh(task.id), timeout=remaining)
        except TimeoutError:
            break
        except AppError as exc:
            pytest.fail(
                "Wanx refresh failed: "
                f"category=WANX_REFRESH_APP_ERROR, "
                f"http_status={exc.status_code}"
            )

        assert submit_calls == 1
        assert result.task.provider_task_id == provider_task_id
        if result.task.status != statuses[-1]:
            statuses.append(result.task.status)

        if result.task.status == "SUCCEEDED":
            assert result.artifact is not None
            assert result.artifact.provider_output_url
            artifact = db_session.scalar(
                select(VideoRenderArtifact).where(
                    VideoRenderArtifact.video_render_task_id == task.id
                )
            )
            assert artifact is not None
            assert artifact.provider_output_url
            elapsed = time.monotonic() - started
            print(
                "Wanx smoke succeeded: "
                f"statuses={' -> '.join(statuses)}, "
                f"fetches={fetch_calls}, elapsed_seconds={elapsed:.1f}, "
                "artifact=yes, provider_output_url=present"
            )
            return

        if result.task.status in {"FAILED", "CANCELED"}:
            category = result.task.error_code or (f"WANX_TASK_{result.task.status}")
            pytest.fail(
                "Wanx task reached a terminal failure: "
                f"category={category}, "
                f"statuses={' -> '.join(statuses)}"
            )

    pytest.fail(
        "Wanx smoke timed out safely: "
        f"category=WANX_SMOKE_TIMEOUT, "
        f"statuses={' -> '.join(statuses)}, fetches={fetch_calls}"
    )


def test_wanx_real_render_pipeline(db_session: Session) -> None:
    _require_wanx_configuration()
    asyncio.run(_execute_real_smoke(db_session))
