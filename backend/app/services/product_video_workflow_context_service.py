from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.repositories.batch_video import BatchVideoRepository
from app.repositories.copy import CopyMatrixRepository
from app.repositories.product import ProductRepository
from app.repositories.strategy import MarketingStrategyRepository
from app.schemas.batch_video import ProductVideoWorkflowContextRead


class ProductVideoWorkflowContextService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, product_id: int) -> ProductVideoWorkflowContextRead:
        product = ProductRepository(self.session).get(product_id)
        if product is None:
            raise AppError("Product was not found", 404)

        batch = BatchVideoRepository(self.session).get_latest_three_platform_batch(
            product_id
        )
        strategy = MarketingStrategyRepository(
            self.session
        ).get_latest_by_product(product_id)
        copy = (
            CopyMatrixRepository(self.session).get_latest_by_strategy(strategy.id)
            if strategy is not None
            else None
        )
        reference_assets = [
            asset
            for asset in product.assets
            if asset.sha256
            and asset.storage_identity
            and asset.content_type in {"image/png", "image/jpeg", "image/webp"}
        ]
        reference = max(reference_assets, key=lambda asset: asset.id, default=None)
        missing: list[str] = []
        if batch is None:
            missing.append("three_platform_batch")
        if strategy is None:
            missing.append("marketing_strategy")
        if reference is None:
            missing.append("reference_image")
        return ProductVideoWorkflowContextRead(
            product_id=product.id,
            batch_id=batch.id if batch is not None else None,
            strategy_id=strategy.id if strategy is not None else None,
            copy_matrix_id=copy.id if copy is not None else None,
            reference_asset_id=reference.id if reference is not None else None,
            ready=not missing,
            missing_requirements=missing,
        )
