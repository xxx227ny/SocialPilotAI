from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DemoScenario


class DemoScenarioRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_slug(self, slug: str) -> DemoScenario | None:
        return self.session.scalar(
            select(DemoScenario).where(DemoScenario.slug == slug)
        )

    def get_by_product(self, product_id: int) -> DemoScenario | None:
        return self.session.scalar(
            select(DemoScenario).where(DemoScenario.product_id == product_id)
        )
