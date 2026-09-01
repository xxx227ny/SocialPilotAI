from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketingStrategy
from app.repositories.workspace_scope import scope_to_owned_products
from app.schemas.strategy import MarketingStrategySchema


class MarketingStrategyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, product_id: int, data: MarketingStrategySchema
    ) -> MarketingStrategy:
        strategy = MarketingStrategy(product_id=product_id, **data.model_dump())
        self.session.add(strategy)
        self.session.commit()
        self.session.refresh(strategy)
        return strategy

    def get(self, strategy_id: int) -> MarketingStrategy | None:
        statement = select(MarketingStrategy).where(MarketingStrategy.id == strategy_id)
        return self.session.scalar(
            scope_to_owned_products(statement, MarketingStrategy, self.session)
        )

    def get_latest_by_product(self, product_id: int) -> MarketingStrategy | None:
        statement = (
            select(MarketingStrategy)
            .where(MarketingStrategy.product_id == product_id)
            .order_by(MarketingStrategy.created_at.desc(), MarketingStrategy.id.desc())
            .limit(1)
        )
        return self.session.scalar(
            scope_to_owned_products(statement, MarketingStrategy, self.session)
        )
