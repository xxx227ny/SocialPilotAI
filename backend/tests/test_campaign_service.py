from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import AdCampaign, Product
from app.services.campaign_service import CampaignService


def create_product(db_session: Session) -> Product:
    product = Product(
        name="Portable Blender",
        category="Appliance",
        description="Portable blender",
        selling_points=["Portable"],
        target_markets=["USA"],
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def test_import_valid_csv_after_full_validation(db_session: Session) -> None:
    product = create_product(db_session)
    content = (
        b"platform,campaign_name,date,impressions,clicks,conversions,spend,revenue\n"
        b"TikTok,Launch,2026-07-01,1000,60,6,120.00,360.00\n"
        b"Instagram,Retargeting,2026-07-02,500,25,3,75.00,180.00\n"
    )

    result = CampaignService(db_session).import_csv(product.id, "ads.csv", content)

    assert result.imported_count == 2
    assert db_session.scalar(select(func.count()).select_from(AdCampaign)) == 2


def test_invalid_later_row_writes_nothing(db_session: Session) -> None:
    product = create_product(db_session)
    content = (
        b"platform,campaign_name,date,impressions,clicks,conversions,spend,revenue\n"
        b"TikTok,Valid,2026-07-01,1000,60,6,120.00,360.00\n"
        b"Facebook,Invalid,2026-07-02,100,120,3,20.00,50.00\n"
    )

    try:
        CampaignService(db_session).import_csv(product.id, "ads.csv", content)
    except AppError as exc:
        assert exc.status_code == 422
        assert "row 3" in exc.message
    else:
        raise AssertionError("invalid CSV should be rejected")

    assert db_session.scalar(select(func.count()).select_from(AdCampaign)) == 0
