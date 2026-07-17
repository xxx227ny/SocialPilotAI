from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    CopyMatrix,
    MarketingStrategy,
    Product,
    VideoProject,
    VideoRenderTask,
)
from app.schemas.video_render import VideoRenderTaskCreate
from app.services.video_render_service import VideoRenderService


def create_video_project(db_session: Session) -> VideoProject:
    product = Product(
        name="Portable Blender",
        category="Appliance",
        description="Portable blender",
        selling_points=["Portable"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.flush()
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Portable daily routine.",
        audience_insights=["Busy professionals."],
        angles=["Blend anywhere"],
        risks=["Avoid health guarantees."],
        evidence=["Portable design."],
    )
    db_session.add(strategy)
    db_session.flush()
    copy_matrix = CopyMatrix(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copies=[
            {
                "platform": "TikTok",
                "hook": "Blend anywhere.",
                "caption": "Portable routine.",
                "hashtags": ["#Portable"],
                "cta": "See more.",
            },
            {
                "platform": "Instagram",
                "hook": "Fresh routine.",
                "caption": "Lifestyle.",
                "hashtags": ["#Lifestyle"],
                "cta": "Save it.",
            },
            {
                "platform": "Facebook",
                "hook": "Portable value.",
                "caption": "Functional value.",
                "hashtags": ["#Value"],
                "cta": "Learn more.",
            },
        ],
    )
    db_session.add(copy_matrix)
    db_session.flush()
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        platform="TikTok",
        title="Blend Anywhere",
        concept="A portable morning routine.",
        duration_seconds=10,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 4,
                "shot_type": "Close-up",
                "visual_description": "Fruit drops into the blender.",
                "action": "Quick ingredient cuts.",
                "narration": "Start fresh.",
            },
            {
                "sequence": 2,
                "duration_seconds": 6,
                "shot_type": "Lifestyle montage",
                "visual_description": "The blender moves from desk to gym.",
                "action": "Blend, carry, and clean.",
                "narration": "Take the routine anywhere.",
            },
        ],
        cta="Blend your next fresh moment.",
        status="planned",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


def render_request(
    key: str = "render-task-001", scene_sequence: int = 1
) -> VideoRenderTaskCreate:
    return VideoRenderTaskCreate(
        scene_sequence=scene_sequence,
        resolution="720P",
        idempotency_key=key,
    )


def test_create_local_render_task(db_session: Session) -> None:
    project = create_video_project(db_session)

    task = VideoRenderService(db_session).create_render_task(
        project.id, render_request()
    )

    assert task.status == "CREATED"
    assert task.video_project_id == project.id
    assert task.scene_sequence == 1
    assert task.duration_seconds == 4
    assert task.aspect_ratio == "9:16"
    assert task.resolution == "720P"
    assert task.provider_name is None
    assert task.provider_task_id is None
    assert "Fruit drops into the blender" in task.render_prompt


def test_video_project_must_exist(db_session: Session) -> None:
    try:
        VideoRenderService(db_session).create_render_task(999, render_request())
    except AppError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing video project should fail")


def test_scene_must_exist(db_session: Session) -> None:
    project = create_video_project(db_session)

    try:
        VideoRenderService(db_session).create_render_task(
            project.id, render_request(scene_sequence=99)
        )
    except AppError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("missing scene should fail")


def test_invalid_scene_duration_is_rejected(db_session: Session) -> None:
    project = create_video_project(db_session)
    broken_scene = dict(project.scenes[0])
    broken_scene["duration_seconds"] = 0
    project.scenes = [broken_scene, project.scenes[1]]
    db_session.commit()

    try:
        VideoRenderService(db_session).create_render_task(
            project.id, render_request()
        )
    except AppError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("non-positive scene duration should fail")


def test_idempotency_key_returns_the_same_task(db_session: Session) -> None:
    project = create_video_project(db_session)
    service = VideoRenderService(db_session)

    first = service.create_render_task(project.id, render_request())
    second = service.create_render_task(project.id, render_request())

    assert first.id == second.id
    assert (
        db_session.scalar(select(func.count()).select_from(VideoRenderTask)) == 1
    )
