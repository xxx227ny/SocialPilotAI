from pathlib import Path

from app.core.config import Settings
from app.models import ExecutionJob, VideoComposition
from app.schemas.video_composition import (
    VideoCompositionPreflightRequest,
    VideoCompositionSubmitRequest,
)
from app.services.video_composition_job_service import VideoCompositionJobService
from app.services.video_composition_preflight import VideoCompositionPreflightService
from tests.test_video_composition_preflight import _sources


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        enable_video_composition=True,
        video_artifact_storage_root=str(root),
        video_composition_temp_root=str(root / "temp"),
    )


def test_submit_is_idempotent_and_creates_one_composition_and_job(
    db_session, tmp_path
) -> None:
    product, project, storage, shots = _sources(db_session, tmp_path)
    preflight = VideoCompositionPreflightService(db_session, storage).run(
        product.id,
        VideoCompositionPreflightRequest(
            video_project_id=project.id,
            shots=shots,
        ),
    )
    request = VideoCompositionSubmitRequest(
        video_project_id=project.id,
        shots=shots,
        input_digest=preflight.input_digest,
        source_chain_digest=preflight.source_chain_digest,
        preflight_digest=preflight.preflight_digest,
        preflight_expires_at=preflight.expires_at,
        local_cpu_cost_confirmed=True,
    )
    service = VideoCompositionJobService(db_session, _settings(tmp_path))
    first = service.enqueue(product.id, request)
    second = service.enqueue(product.id, request)
    assert first.reused is False and second.reused is True
    assert first.composition.id == second.composition.id
    assert first.job.id == second.job.id
    assert db_session.query(VideoComposition).count() == 1
    assert db_session.query(ExecutionJob).count() == 1
    assert len(first.composition.shots) == 3
