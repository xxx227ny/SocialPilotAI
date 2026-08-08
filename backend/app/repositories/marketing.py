from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketingBrief
from app.schemas.marketing import MarketingTaskCreate


class MarketingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, data: MarketingTaskCreate) -> MarketingBrief:
        task = MarketingBrief(**data.model_dump())
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def get(self, task_id: int) -> MarketingBrief | None:
        return self.session.get(MarketingBrief, task_id)

    def list_for_product(self, product_id: int) -> list[MarketingBrief]:
        statement = (
            select(MarketingBrief)
            .where(MarketingBrief.product_id == product_id)
            .order_by(MarketingBrief.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_latest_for_product(self, product_id: int) -> MarketingBrief | None:
        statement = (
            select(MarketingBrief)
            .where(MarketingBrief.product_id == product_id)
            .order_by(MarketingBrief.created_at.desc(), MarketingBrief.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)
