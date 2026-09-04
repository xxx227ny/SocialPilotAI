from __future__ import annotations

from sqlalchemy import MetaData, Table, func, inspect, select, update
from sqlalchemy.orm import Session, selectinload

from app.execution.workspace_context import current_execution_workspace_id
from app.models import Product, ProductAsset, Workspace
from app.schemas.product import ProductAssetCreate, ProductCreate, ProductUpdate


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @property
    def workspace_id(self) -> int | None:
        value = self.session.info.get("workspace_id")
        if value is None:
            value = current_execution_workspace_id()
        return int(value) if value is not None else None

    def create(
        self,
        data: ProductCreate,
        *,
        create_request_key: str | None = None,
        create_request_digest: str | None = None,
    ) -> Product:
        workspace_id = self.workspace_id
        product = Product(
            workspace_id=workspace_id,
            display_number=self._allocate_display_number(workspace_id),
            create_request_key=create_request_key,
            create_request_digest=create_request_digest,
            **data.model_dump(),
        )
        self.session.add(product)
        self.session.commit()
        return self.get(product.id)  # type: ignore[return-value]

    def _allocate_display_number(self, workspace_id: int | None) -> int:
        if workspace_id is not None:
            next_value = self.session.scalar(
                update(Workspace)
                .where(Workspace.id == workspace_id)
                .values(next_product_number=Workspace.next_product_number + 1)
                .returning(Workspace.next_product_number)
            )
            if next_value is None:
                raise RuntimeError("Product workspace does not exist")
            return int(next_value) - 1

        # Compatibility path for legacy/demo execution without an authenticated
        # workspace. Authenticated product creation always uses the atomic
        # workspace counter above.
        highest = self.session.scalar(
            select(func.max(Product.display_number)).where(Product.workspace_id.is_(None))
        )
        return int(highest or 0) + 1

    def get_by_create_request_key(self, request_key: str) -> Product | None:
        statement = select(Product).options(selectinload(Product.assets)).where(
            Product.create_request_key == request_key
        )
        workspace_id = self.workspace_id
        if workspace_id is None:
            statement = statement.where(Product.workspace_id.is_(None))
        else:
            statement = statement.where(Product.workspace_id == workspace_id)
        return self.session.scalar(statement)

    def list(self) -> list[Product]:
        statement = (
            select(Product)
            .options(selectinload(Product.assets))
            .order_by(Product.created_at.desc())
        )
        workspace_id = self.workspace_id
        if workspace_id is not None:
            statement = statement.where(Product.workspace_id == workspace_id)
        return list(self.session.scalars(statement).all())

    def get(self, product_id: int) -> Product | None:
        statement = (
            select(Product)
            .options(selectinload(Product.assets))
            .where(Product.id == product_id)
        )
        workspace_id = self.workspace_id
        if workspace_id is not None:
            statement = statement.where(Product.workspace_id == workspace_id)
        return self.session.scalar(statement)

    def update(self, product: Product, data: ProductUpdate) -> Product:
        for field, value in data.model_dump(
            exclude_unset=True, exclude_none=True
        ).items():
            setattr(product, field, value)
        self.session.commit()
        return self.get(product.id)  # type: ignore[return-value]

    def add_asset(self, product_id: int, data: ProductAssetCreate) -> ProductAsset:
        asset = ProductAsset(product_id=product_id, **data.model_dump())
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def get_asset(self, product_id: int, asset_id: int) -> ProductAsset | None:
        return self.session.scalar(
            select(ProductAsset).where(
                ProductAsset.id == asset_id, ProductAsset.product_id == product_id
            )
        )

    def get_asset_by_sha(self, product_id: int, sha256: str) -> ProductAsset | None:
        return self.session.scalar(
            select(ProductAsset).where(
                ProductAsset.product_id == product_id,
                ProductAsset.sha256 == sha256,
            )
        )

    def persist_asset(self, asset: ProductAsset) -> ProductAsset:
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def workspace_asset_usage_bytes(self) -> int:
        workspace_id = self.workspace_id
        if workspace_id is None:
            return 0
        value = self.session.scalar(
            select(func.coalesce(func.sum(ProductAsset.size_bytes), 0))
            .join(Product, Product.id == ProductAsset.product_id)
            .where(Product.workspace_id == workspace_id)
        )
        return int(value or 0)

    def referencing_tables(
        self,
        referred_table: str,
        record_id: int,
        *,
        excluded_tables: set[str] | None = None,
    ) -> list[str]:
        excluded = excluded_tables or set()
        bind = self.session.get_bind()
        schema = inspect(bind)
        references: list[str] = []
        metadata = MetaData()
        for table_name in sorted(schema.get_table_names()):
            if table_name in excluded:
                continue
            for foreign_key in schema.get_foreign_keys(table_name):
                if foreign_key.get("referred_table") != referred_table:
                    continue
                local_columns = foreign_key.get("constrained_columns") or []
                remote_columns = foreign_key.get("referred_columns") or []
                if len(local_columns) != 1 or remote_columns != ["id"]:
                    continue
                table = Table(table_name, metadata, autoload_with=bind)
                column = table.c[local_columns[0]]
                if self.session.execute(
                    select(column).where(column == record_id).limit(1)
                ).first():
                    references.append(table_name)
                    break
        return references

    def delete_asset(self, asset: ProductAsset) -> None:
        self.session.delete(asset)
        self.session.commit()

    def delete_product(self, product: Product) -> None:
        self.session.delete(product)
        self.session.commit()
