from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.models import CopyMatrix, MarketingStrategy, Product
from app.schemas.copy import CopyMatrixSchema, TaskBoundCopyMatrixSchema


class CopyMatrixRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        product_id: int,
        marketing_strategy_id: int,
        data: CopyMatrixSchema,
    ) -> CopyMatrix:
        copy_matrix = CopyMatrix(
            product_id=product_id,
            marketing_strategy_id=marketing_strategy_id,
            copies=[copy.model_dump() for copy in data.copies],
        )
        self.session.add(copy_matrix)
        self.session.commit()
        self.session.refresh(copy_matrix)
        return copy_matrix

    def get(self, copy_matrix_id: int) -> CopyMatrix | None:
        return self.session.get(CopyMatrix, copy_matrix_id)

    def get_latest_by_product(self, product_id: int) -> CopyMatrix | None:
        statement = (
            select(CopyMatrix)
            .where(CopyMatrix.product_id == product_id)
            .order_by(CopyMatrix.created_at.desc(), CopyMatrix.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_latest_valid_source_chain(
        self, product_id: int
    ) -> tuple[Product, MarketingStrategy, CopyMatrix] | None:
        """Select one exact Product/Strategy/CopyMatrix chain by latest CopyMatrix."""
        statement = (
            select(Product, MarketingStrategy, CopyMatrix)
            .join(CopyMatrix, CopyMatrix.product_id == Product.id)
            .join(
                MarketingStrategy,
                CopyMatrix.marketing_strategy_id == MarketingStrategy.id,
            )
            .where(
                Product.id == product_id,
                CopyMatrix.product_id == Product.id,
                MarketingStrategy.product_id == Product.id,
                CopyMatrix.marketing_strategy_id == MarketingStrategy.id,
            )
            .order_by(CopyMatrix.created_at.desc(), CopyMatrix.id.desc())
            .limit(1)
        )
        row = self.session.execute(statement).one_or_none()
        if row is None:
            return None
        return row[0], row[1], row[2]

    def create_for_exact_strategy(
        self,
        product_id: int,
        marketing_strategy_id: int,
        data: TaskBoundCopyMatrixSchema,
        *,
        commit: bool = True,
    ) -> CopyMatrix:
        """Persist validated task-bound copies without changing the legacy ORM rule."""
        try:
            result = self.session.execute(
                insert(CopyMatrix).values(
                    product_id=product_id,
                    marketing_strategy_id=marketing_strategy_id,
                    copies=[copy.model_dump() for copy in data.copies],
                )
            )
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except Exception:
            self.session.rollback()
            raise
        inserted_id = result.inserted_primary_key[0]
        copy_matrix = self.get(inserted_id)
        if copy_matrix is None:
            raise RuntimeError("Created CopyMatrix could not be reloaded")
        return copy_matrix

    def get_latest_by_strategy(
        self, marketing_strategy_id: int
    ) -> CopyMatrix | None:
        statement = (
            select(CopyMatrix)
            .where(
                CopyMatrix.marketing_strategy_id == marketing_strategy_id
            )
            .order_by(CopyMatrix.created_at.desc(), CopyMatrix.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)
