from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import MarketingBrief, Product
from app.repositories.marketing import MarketingRepository
from app.schemas.marketing import MarketingTaskCreate


class MarketingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = MarketingRepository(session)

    def create(self, data: MarketingTaskCreate) -> MarketingBrief:
        if self.session.get(Product, data.product_id) is None:
            raise AppError("Product not found", status_code=404)
        return self.repository.create(data)
