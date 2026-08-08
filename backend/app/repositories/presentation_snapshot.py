from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PresentationSnapshot


class PresentationSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, snapshot_id: int) -> PresentationSnapshot | None:
        return self.session.get(PresentationSnapshot, snapshot_id)

    def get_by_digest(self, digest: str) -> PresentationSnapshot | None:
        return self.session.scalar(
            select(PresentationSnapshot).where(
                PresentationSnapshot.digest == digest
            )
        )

    def list_by_product(self, product_id: int) -> list[PresentationSnapshot]:
        statement = (
            select(PresentationSnapshot)
            .where(PresentationSnapshot.product_id == product_id)
            .order_by(PresentationSnapshot.created_at, PresentationSnapshot.id)
        )
        return list(self.session.scalars(statement).all())

    def get_by_artifact_snapshot_path(
        self, artifact_snapshot_path: str
    ) -> PresentationSnapshot | None:
        return self.session.scalar(
            select(PresentationSnapshot).where(
                PresentationSnapshot.artifact_snapshot_path
                == artifact_snapshot_path
            )
        )

    def create_or_reuse(
        self, snapshot: PresentationSnapshot
    ) -> tuple[PresentationSnapshot, bool]:
        self.session.add(snapshot)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get_by_digest(snapshot.digest)
            if existing is None:
                raise
            return existing, True
        self.session.refresh(snapshot)
        return snapshot, False
