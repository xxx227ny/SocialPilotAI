import hashlib
from pathlib import Path

import pytest

from app.core.exceptions import AppError
from app.models import (
    ExecutionJob,
    Product,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionShot,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.schemas.video_composition import VideoCompositionPreflightRequest
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_composition_preflight import VideoCompositionPreflightService


def _sources(db_session, root: Path):
    product = Product(
        name="Composition Product",
        category="Test",
        description="Local composition input",
        selling_points=["Deterministic"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="Three shots",
        concept="Local composition",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="Test",
        status="planned",
    )
    db_session.add(project)
    db_session.flush()
    storage = LocalVideoArtifactStorage(root, 1_000_000)
    shots = []
    for sequence in range(1, 4):
        task = VideoRenderTask(
            video_project_id=project.id,
            scene_sequence=sequence,
            status="SUCCEEDED",
            provider_name="Fake",
            render_prompt="fake",
            duration_seconds=5,
            aspect_ratio="9:16",
            resolution="1080P",
            idempotency_key=f"composition-source-{sequence}",
        )
        db_session.add(task)
        db_session.flush()
        stored = storage.store(
            task_id=task.id,
            content=f"fake-shot-{sequence}".encode(),
            content_type="video/mp4",
        )
        artifact = VideoRenderArtifact(
            video_render_task_id=task.id,
            storage_path=stored.relative_path,
            artifact_metadata={
                "content_type": "video/mp4",
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            },
        )
        db_session.add(artifact)
        db_session.flush()
        shots.append(
            {
                "sequence": sequence,
                "start_ms": (sequence - 1) * 5000,
                "end_ms": sequence * 5000,
                "trim_start_ms": 0,
                "trim_end_ms": 5000,
                "render_task_id": task.id,
                "artifact_id": artifact.id,
            }
        )
    db_session.commit()
    return product, project, storage, shots


def test_preflight_freezes_exact_sources_without_writes(db_session, tmp_path) -> None:
    product, project, storage, shots = _sources(db_session, tmp_path)
    tracked_models = (
        VideoComposition,
        VideoCompositionShot,
        VideoCompositionArtifact,
        ExecutionJob,
    )
    before = {model: db_session.query(model).count() for model in tracked_models}
    result = VideoCompositionPreflightService(db_session, storage).run(
        product.id,
        VideoCompositionPreflightRequest(video_project_id=project.id, shots=shots),
    )
    assert result.ready is True
    assert result.product_id == product.id
    assert result.video_project_id == project.id
    assert [item.sequence for item in result.shots] == [1, 2, 3]
    assert all(len(item.artifact_sha256) == 64 for item in result.shots)
    assert result.output_contract["duration_ms"] == 15000
    assert result.output_contract["audio_kind"] == "deterministic_silence_placeholder"
    assert "确定性静音 AAC 占位音轨" in result.placeholder_audio_notice
    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
    after = {model: db_session.query(model).count() for model in tracked_models}
    assert after == before


def test_preflight_rejects_wrong_source_relationship(db_session, tmp_path) -> None:
    product, project, storage, shots = _sources(db_session, tmp_path)
    shots[0]["artifact_id"] = shots[1]["artifact_id"]
    with pytest.raises(AppError) as error:
        VideoCompositionPreflightService(db_session, storage).run(
            product.id,
            VideoCompositionPreflightRequest(video_project_id=project.id, shots=shots),
        )
    assert error.value.status_code == 409


def test_preflight_digest_changes_with_exact_artifact_identity(
    db_session, tmp_path
) -> None:
    product, project, storage, shots = _sources(db_session, tmp_path)
    first = VideoCompositionPreflightService(db_session, storage).run(
        product.id,
        VideoCompositionPreflightRequest(video_project_id=project.id, shots=shots),
    )
    assert first.source_chain_digest == hashlib.sha256(
        __import__("json").dumps(
            [shot.model_dump(mode="json") for shot in first.shots],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
