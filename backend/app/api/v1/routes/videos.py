from typing import Annotated

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import TextProviderDep
from app.db.session import get_db
from app.schemas.video import VideoProjectRequest, VideoProjectSchema
from app.services.content_studio_service import ContentStudioService

router = APIRouter(prefix="/products")
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/{product_id}/video-projects", response_model=VideoProjectSchema
)
def generate_video_project(
    product_id: int,
    db: DbSession,
    provider: TextProviderDep,
    request: Annotated[VideoProjectRequest, Body()],
) -> VideoProjectSchema:
    return ContentStudioService(db, provider).generate_for_product(
        product_id, request
    )
