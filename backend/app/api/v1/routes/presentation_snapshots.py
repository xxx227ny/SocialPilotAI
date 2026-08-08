from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import OptionalVideoArtifactStorageDep
from app.db.session import get_db
from app.schemas.presentation_snapshot import (
    PresentationSnapshotCreate,
    PresentationSnapshotCreateRead,
    PresentationSnapshotRead,
)
from app.services.presentation_snapshot_service import (
    PresentationSnapshotService,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/products/{product_id}/presentation-snapshots",
    response_model=PresentationSnapshotCreateRead,
)
def create_presentation_snapshot(
    product_id: int,
    data: PresentationSnapshotCreate,
    db: DbSession,
    artifact_storage: OptionalVideoArtifactStorageDep,
) -> PresentationSnapshotCreateRead:
    return PresentationSnapshotService(db, artifact_storage).create(
        product_id, data
    )


@router.get(
    "/presentation-snapshots/{snapshot_id}",
    response_model=PresentationSnapshotRead,
)
def get_presentation_snapshot(
    snapshot_id: int,
    db: DbSession,
) -> PresentationSnapshotRead:
    return PresentationSnapshotService(db).get(snapshot_id)


@router.get(
    "/products/{product_id}/presentation-snapshots",
    response_model=list[PresentationSnapshotRead],
)
def list_presentation_snapshots(
    product_id: int,
    db: DbSession,
) -> list[PresentationSnapshotRead]:
    return PresentationSnapshotService(db).list_for_product(product_id)
