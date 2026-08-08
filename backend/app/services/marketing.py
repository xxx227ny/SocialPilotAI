import re

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import MarketingBrief, Product
from app.repositories.marketing import MarketingRepository
from app.schemas.marketing import MarketingTaskCreate, MarketingTaskRead

SUPPORTED_MARKET_ALIASES = {
    "us": "US",
    "usa": "US",
    "united states": "US",
    "ca": "CA",
    "canada": "CA",
    "uk": "UK",
    "gb": "UK",
    "united kingdom": "UK",
    "de": "DE",
    "germany": "DE",
    "fr": "FR",
    "france": "FR",
    "au": "AU",
    "australia": "AU",
    "jp": "JP",
    "japan": "JP",
    "sg": "SG",
    "singapore": "SG",
}
TARGET_MARKET_AUDIENCE_PATTERN = re.compile(r"^Target markets \[([^]]+)]\. ")


class MarketingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = MarketingRepository(session)

    def create(self, data: MarketingTaskCreate) -> MarketingTaskRead:
        product = self.session.get(Product, data.product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        target_markets = self._validated_target_markets(product)
        snapshot = ",".join(target_markets)
        persisted_data = data.model_copy(
            update={"audience": f"Target markets [{snapshot}]. {data.audience}"}
        )
        return self._to_read(self.repository.create(persisted_data), target_markets)

    def list_for_product(self, product_id: int) -> list[MarketingTaskRead]:
        product = self.session.get(Product, product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        return [
            self._to_read(task, product.target_markets)
            for task in self.repository.list_for_product(product_id)
        ]

    def get(self, task_id: int) -> MarketingTaskRead:
        task = self.repository.get(task_id)
        if task is None:
            raise AppError("Marketing task not found", status_code=404)
        product = self.session.get(Product, task.product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        return self._to_read(task, product.target_markets)

    def get_latest_for_product(self, product_id: int) -> MarketingTaskRead | None:
        product = self.session.get(Product, product_id)
        if product is None:
            raise AppError("Product not found", status_code=404)
        task = self.repository.get_latest_for_product(product_id)
        if task is None:
            return None
        return self._to_read(task, product.target_markets)

    @staticmethod
    def _validated_target_markets(product: Product) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for market in product.target_markets:
            canonical = SUPPORTED_MARKET_ALIASES.get(market.strip().casefold())
            if canonical is None:
                raise AppError(
                    "Product target markets contain an unsupported value",
                    status_code=422,
                )
            if canonical not in seen:
                normalized.append(canonical)
                seen.add(canonical)
        if not 1 <= len(normalized) <= 5:
            raise AppError(
                "Product must have between 1 and 5 target markets",
                status_code=422,
            )
        return normalized

    @staticmethod
    def _to_read(
        task: MarketingBrief, target_markets: list[str]
    ) -> MarketingTaskRead:
        match = TARGET_MARKET_AUDIENCE_PATTERN.match(task.audience)
        saved_target_markets = (
            match.group(1).split(",") if match is not None else target_markets
        )
        return MarketingTaskRead.model_validate(
            {
                "id": task.id,
                "product_id": task.product_id,
                "audience": task.audience,
                "language": task.language,
                "platforms": task.platforms,
                "tone": task.tone,
                "objective": task.objective,
                "target_markets": saved_target_markets,
                "created_at": task.created_at,
            }
        )
