from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VideoProject
from app.schemas.video import VideoPlanSchema


class VideoProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        product_id: int,
        marketing_strategy_id: int,
        copy_matrix_id: int,
        plan: VideoPlanSchema,
    ) -> VideoProject:
        project = VideoProject(
            product_id=product_id,
            marketing_strategy_id=marketing_strategy_id,
            copy_matrix_id=copy_matrix_id,
            platform=plan.platform,
            title=plan.title,
            concept=plan.concept,
            duration_seconds=plan.duration_seconds,
            aspect_ratio=plan.aspect_ratio,
            scenes=[scene.model_dump() for scene in plan.scenes],
            cta=plan.cta,
            status="planned",
        )
        self.session.add(project)
        self.session.commit()
        self.session.refresh(project)
        return project

    def get(self, video_project_id: int) -> VideoProject | None:
        return self.session.get(VideoProject, video_project_id)

    def get_by_initial_identity(
        self,
        *,
        product_id: int,
        marketing_strategy_id: int,
        copy_matrix_id: int,
        platform: str,
        duration_seconds: int,
        aspect_ratio: str,
    ) -> VideoProject | None:
        statement = select(VideoProject).where(
            VideoProject.product_id == product_id,
            VideoProject.marketing_strategy_id == marketing_strategy_id,
            VideoProject.copy_matrix_id == copy_matrix_id,
            VideoProject.platform == platform,
            VideoProject.duration_seconds == duration_seconds,
            VideoProject.aspect_ratio == aspect_ratio,
        )
        return self.session.scalar(statement.limit(1))

    def create_for_exact_chain(
        self,
        product_id: int,
        marketing_strategy_id: int,
        copy_matrix_id: int,
        plan: VideoPlanSchema,
    ) -> VideoProject:
        project = VideoProject(
            product_id=product_id,
            marketing_strategy_id=marketing_strategy_id,
            copy_matrix_id=copy_matrix_id,
            platform=plan.platform,
            title=plan.title,
            concept=plan.concept,
            duration_seconds=plan.duration_seconds,
            aspect_ratio=plan.aspect_ratio,
            scenes=[scene.model_dump() for scene in plan.scenes],
            cta=plan.cta,
            status="planned",
        )
        try:
            self.session.add(project)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return project

    def get_latest_by_product(self, product_id: int) -> VideoProject | None:
        statement = (
            select(VideoProject)
            .where(VideoProject.product_id == product_id)
            .order_by(VideoProject.created_at.desc(), VideoProject.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)
