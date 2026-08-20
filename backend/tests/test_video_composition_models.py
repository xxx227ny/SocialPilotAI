import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models import Product, VideoComposition, VideoProject
from app.schemas.video_composition import VideoCompositionPreflightRequest


def _shots() -> list[dict[str, object]]:
    return [
        {
            "sequence": 1,
            "start_ms": 0,
            "end_ms": 5000,
            "trim_start_ms": 0,
            "trim_end_ms": 5000,
            "render_task_id": 1,
            "artifact_id": 1,
        },
        {
            "sequence": 2,
            "start_ms": 5000,
            "end_ms": 10000,
            "trim_start_ms": 0,
            "trim_end_ms": 5000,
            "render_task_id": 2,
            "artifact_id": 2,
        },
        {
            "sequence": 3,
            "start_ms": 10000,
            "end_ms": 15000,
            "trim_start_ms": 0,
            "trim_end_ms": 5000,
            "render_task_id": 3,
            "artifact_id": 3,
        },
    ]


@pytest.mark.parametrize("mutation", ["gap", "overlap", "short", "sequence", "trim"])
def test_timeline_rejects_invalid_mutations(mutation: str) -> None:
    shots = _shots()
    if mutation == "gap":
        shots[1]["start_ms"] = 5001
    if mutation == "overlap":
        shots[1]["start_ms"] = 4999
    if mutation == "short":
        shots[2]["end_ms"] = 14999
    if mutation == "sequence":
        shots[1]["sequence"] = 4
    if mutation == "trim":
        shots[0]["trim_end_ms"] = 4999
    with pytest.raises(ValidationError):
        VideoCompositionPreflightRequest(video_project_id=1, shots=shots)


def test_timeline_accepts_exact_fifteen_seconds() -> None:
    value = VideoCompositionPreflightRequest(video_project_id=1, shots=_shots())
    assert len(value.shots) == 3


def test_timeline_accepts_one_exact_fifteen_second_cloud_shot() -> None:
    value = VideoCompositionPreflightRequest(
        video_project_id=1,
        shots=[
            {
                "sequence": 1,
                "start_ms": 0,
                "end_ms": 15000,
                "trim_start_ms": 0,
                "trim_end_ms": 15000,
                "render_task_id": 1,
                "artifact_id": 1,
            }
        ],
    )
    assert len(value.shots) == 1
    assert value.shots[0].end_ms == 15000


def test_composition_database_contract(db_session) -> None:
    product = Product(
        name="P",
        category="C",
        description="D",
        selling_points=["Portable design"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="T",
        concept="C",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[],
        cta="C",
        status="planned",
    )
    db_session.add(project)
    db_session.flush()
    invalid = VideoComposition(
        product_id=product.id,
        video_project_id=project.id,
        input_digest="a" * 64,
        source_chain_digest="b" * 64,
        idempotency_key="invalid",
        duration_ms=14999,
        status="READY",
    )
    db_session.add(invalid)
    with pytest.raises(IntegrityError):
        db_session.commit()
