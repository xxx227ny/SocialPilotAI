from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdCampaign
from app.schemas.campaign import CampaignRowSchema


class CampaignRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_many(
        self, product_id: int, rows: Sequence[CampaignRowSchema]
    ) -> list[AdCampaign]:
        campaigns = [
            AdCampaign(product_id=product_id, **row.model_dump()) for row in rows
        ]
        self.session.add_all(campaigns)
        self.session.commit()
        return campaigns

    def list_by_product(self, product_id: int) -> list[AdCampaign]:
        statement = (
            select(AdCampaign)
            .where(AdCampaign.product_id == product_id)
            .order_by(AdCampaign.date, AdCampaign.id)
        )
        return list(self.session.scalars(statement).all())

    def list_by_ids(self, campaign_ids: list[int]) -> list[AdCampaign]:
        if not campaign_ids:
            return []
        statement = (
            select(AdCampaign)
            .where(AdCampaign.id.in_(campaign_ids))
            .order_by(AdCampaign.date, AdCampaign.id)
        )
        return list(self.session.scalars(statement).all())
