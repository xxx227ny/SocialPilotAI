from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Product

DEMO_PRODUCT_NAME = "Portable Blender"

def seed_development_data() -> None:
    """Insert idempotent demo data only in the development environment."""
    if settings.app_environment.lower() != "development":
        return

    with SessionLocal() as session:
        existing = session.scalar(
            select(Product).where(Product.name == DEMO_PRODUCT_NAME)
        )
        if existing is not None:
            return
        session.add(
            Product(
                name=DEMO_PRODUCT_NAME,
                category="Portable Kitchen Appliance",
                description=(
                    "A portable personal blender for making fresh drinks anytime."
                ),
                selling_points=[
                    "Portable design",
                    "USB rechargeable",
                    "Easy cleaning",
                    "Healthy lifestyle",
                ],
                target_markets=["USA", "Canada"],
            )
        )
        session.commit()
