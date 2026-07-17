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
