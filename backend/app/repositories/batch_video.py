from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Product
from app.models.batch_video import BatchVideoJob, BatchVideoVariant
from app.repositories.workspace_scope import (
    current_workspace_id,
    scope_to_owned_products,
)


class BatchVideoRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_batch(self, batch_id: int) -> BatchVideoJob | None:
        statement = (
            select(BatchVideoJob)
            .options(
                selectinload(BatchVideoJob.variants).selectinload(
                    BatchVideoVariant.execution_job
                )
            )
            .where(BatchVideoJob.id == batch_id)
        )
        return self.session.scalar(self._scope_batch(statement))

    def get_by_idempotency(self, key: str) -> BatchVideoJob | None:
        return self.session.scalar(
            self._scope_batch(
                select(BatchVideoJob).where(BatchVideoJob.idempotency_key == key)
            )
        )

    def get_by_digest(self, digest: str) -> BatchVideoJob | None:
        return self.session.scalar(
            self._scope_batch(
                select(BatchVideoJob).where(BatchVideoJob.request_digest == digest)
            )
        )

    def get_variant(self, variant_id: int) -> BatchVideoVariant | None:
        statement = scope_to_owned_products(
            select(BatchVideoVariant)
            .options(selectinload(BatchVideoVariant.execution_job))
            .where(BatchVideoVariant.id == variant_id),
            BatchVideoVariant,
            self.session,
        )
        return self.session.scalar(statement)

    def list_variants(self, batch_id: int) -> list[BatchVideoVariant]:
        statement = scope_to_owned_products(
            select(BatchVideoVariant)
            .options(selectinload(BatchVideoVariant.execution_job))
            .where(BatchVideoVariant.batch_video_job_id == batch_id)
            .order_by(
                BatchVideoVariant.product_id,
                BatchVideoVariant.platform,
                BatchVideoVariant.variant_index,
            ),
            BatchVideoVariant,
            self.session,
        )
        return list(self.session.scalars(statement).all())

    def _scope_batch(self, statement):
        workspace_id = current_workspace_id(self.session)
        if workspace_id is None:
            return statement
        owned_batch_ids = (
            select(BatchVideoVariant.batch_video_job_id)
            .where(
                BatchVideoVariant.product_id.in_(
                    select(Product.id).where(Product.workspace_id == workspace_id)
                )
            )
        )
        return statement.where(BatchVideoJob.id.in_(owned_batch_ids))
