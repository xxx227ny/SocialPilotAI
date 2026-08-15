from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.batch_video import BatchVideoJob, BatchVideoVariant


class BatchVideoRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_batch(self, batch_id: int) -> BatchVideoJob | None:
        return self.session.scalar(
            select(BatchVideoJob)
            .options(
                selectinload(BatchVideoJob.variants).selectinload(
                    BatchVideoVariant.execution_job
                )
            )
            .where(BatchVideoJob.id == batch_id)
        )

    def get_by_idempotency(self, key: str) -> BatchVideoJob | None:
        return self.session.scalar(
            select(BatchVideoJob).where(BatchVideoJob.idempotency_key == key)
        )

    def get_by_digest(self, digest: str) -> BatchVideoJob | None:
        return self.session.scalar(
            select(BatchVideoJob).where(BatchVideoJob.request_digest == digest)
        )

    def get_variant(self, variant_id: int) -> BatchVideoVariant | None:
        return self.session.scalar(
            select(BatchVideoVariant)
            .options(selectinload(BatchVideoVariant.execution_job))
            .where(BatchVideoVariant.id == variant_id)
        )

    def list_variants(self, batch_id: int) -> list[BatchVideoVariant]:
        return list(
            self.session.scalars(
                select(BatchVideoVariant)
                .options(selectinload(BatchVideoVariant.execution_job))
                .where(BatchVideoVariant.batch_video_job_id == batch_id)
                .order_by(
                    BatchVideoVariant.product_id,
                    BatchVideoVariant.platform,
                    BatchVideoVariant.variant_index,
                )
            ).all()
        )
