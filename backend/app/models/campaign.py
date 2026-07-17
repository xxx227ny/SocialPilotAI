from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.product import Product, utc_now


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = (
        CheckConstraint("impressions >= 0", name="ck_campaign_impressions_nonnegative"),
        CheckConstraint("clicks >= 0", name="ck_campaign_clicks_nonnegative"),
        CheckConstraint("conversions >= 0", name="ck_campaign_conversions_nonnegative"),
        CheckConstraint("spend >= 0", name="ck_campaign_spend_nonnegative"),
        CheckConstraint("revenue >= 0", name="ck_campaign_revenue_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    campaign_name: Mapped[str] = mapped_column(String(300), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, nullable=False)
    spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    product: Mapped[Product] = relationship(back_populates="ad_campaigns")
