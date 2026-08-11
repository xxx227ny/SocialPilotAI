import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    BindingYouTubeProviderDep,
    VideoArtifactStorageDep,
    YouTubePublishingGateDep,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.execution import ExecutionJobCreateRead
from app.schemas.social import (
    DisconnectRead,
    DisconnectRequest,
    PublishArtifactCandidateRead,
    PublishTaskIdentityRequest,
    PublishTaskRead,
    SocialAccountRead,
    YouTubeConnectRead,
    YouTubeConnectRequest,
    YouTubePreflightRead,
    YouTubePublishingMetadata,
    YouTubePublishRequest,
)
from app.services.social_security import digest_oauth_state
from app.services.social_service import (
    SocialAccountService,
    YouTubePublishingService,
)
from app.services.youtube_publish_job_service import YouTubePublishJobService

router = APIRouter()
OAUTH_BROWSER_COOKIE = "social_oauth_browser"
DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/social-accounts/youtube/connect", response_model=YouTubeConnectRead
)
def connect_youtube(
    data: YouTubeConnectRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: SettingsDep,
    provider: BindingYouTubeProviderDep,
) -> YouTubeConnectRead:
    browser_session = request.cookies.get(OAUTH_BROWSER_COOKIE)
    if not browser_session:
        browser_session = secrets.token_urlsafe(32)
        response.set_cookie(
            OAUTH_BROWSER_COOKIE,
            browser_session,
            max_age=600,
            httponly=True,
            secure=False,
            samesite="lax",
            path="/api/v1/social-accounts/youtube",
        )
    return SocialAccountService(db, settings, provider).connect(
        data.product_id,
        browser_session_digest=digest_oauth_state(browser_session),
    )


@router.get("/social-accounts/youtube/callback", response_class=RedirectResponse)
async def youtube_callback(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    provider: BindingYouTubeProviderDep,
    state: str = Query(min_length=20, max_length=200),
    code: str | None = Query(default=None, max_length=2000),
    error: str | None = Query(default=None, max_length=200),
) -> RedirectResponse:
    location = await SocialAccountService(db, settings, provider).callback(
        state=state,
        browser_session_digest=digest_oauth_state(
            request.cookies.get(OAUTH_BROWSER_COOKIE, "")
        ),
        code=code,
        error=error,
    )
    return RedirectResponse(location, status_code=303)


@router.get("/social-accounts", response_model=list[SocialAccountRead])
def list_social_accounts(
    db: DbSession,
    settings: SettingsDep,
    product_id: int = Query(gt=0),
) -> list[SocialAccountRead]:
    return SocialAccountService(db, settings, None).list_accounts(product_id)


@router.get("/social-accounts/{account_id}", response_model=SocialAccountRead)
def get_social_account(
    account_id: int,
    db: DbSession,
    settings: SettingsDep,
    product_id: int = Query(gt=0),
) -> SocialAccountRead:
    return SocialAccountService(db, settings, None).get_account(
        account_id, product_id
    )


@router.post(
    "/social-accounts/{account_id}/disconnect", response_model=DisconnectRead
)
async def disconnect_social_account(
    account_id: int,
    data: DisconnectRequest,
    db: DbSession,
    settings: SettingsDep,
    provider: BindingYouTubeProviderDep,
) -> DisconnectRead:
    return await SocialAccountService(db, settings, provider).disconnect(
        account_id,
        product_id=data.product_id,
        revoke_google_authorization=data.revoke_google_authorization,
    )


@router.get(
    "/products/{product_id}/publishing/youtube/artifacts",
    response_model=list[PublishArtifactCandidateRead],
)
def list_youtube_publish_artifacts(
    product_id: int,
    db: DbSession,
    settings: SettingsDep,
    storage: VideoArtifactStorageDep,
) -> list[PublishArtifactCandidateRead]:
    return YouTubePublishingService(db, settings, None, storage).list_candidates(
        product_id
    )


@router.post(
    "/products/{product_id}/publishing/youtube/preflight",
    response_model=YouTubePreflightRead,
)
def preflight_youtube_publish(
    product_id: int,
    data: YouTubePublishingMetadata,
    db: DbSession,
    settings: SettingsDep,
    gate: YouTubePublishingGateDep,
    storage: VideoArtifactStorageDep,
) -> YouTubePreflightRead:
    del gate
    return YouTubePublishingService(db, settings, None, storage).preflight(
        product_id, data
    )


@router.post(
    "/products/{product_id}/publishing/youtube",
    response_model=ExecutionJobCreateRead,
    status_code=201,
)
def publish_youtube_video(
    product_id: int,
    data: YouTubePublishRequest,
    db: DbSession,
    settings: SettingsDep,
    storage: VideoArtifactStorageDep,
) -> ExecutionJobCreateRead:
    return YouTubePublishJobService(db, settings, storage).enqueue_submit(
        product_id, data
    )


@router.get("/publish-tasks/{task_id}", response_model=PublishTaskRead)
def get_publish_task(
    task_id: int,
    db: DbSession,
    settings: SettingsDep,
    storage: VideoArtifactStorageDep,
    product_id: int = Query(gt=0),
) -> PublishTaskRead:
    return YouTubePublishingService(db, settings, None, storage).get_task(
        task_id, product_id
    )


@router.get(
    "/products/{product_id}/publish-tasks", response_model=list[PublishTaskRead]
)
def list_publish_tasks(
    product_id: int,
    db: DbSession,
    settings: SettingsDep,
    storage: VideoArtifactStorageDep,
) -> list[PublishTaskRead]:
    return YouTubePublishingService(db, settings, None, storage).list_tasks(
        product_id
    )


@router.post(
    "/publish-tasks/{task_id}/refresh",
    response_model=ExecutionJobCreateRead,
    status_code=201,
)
def refresh_publish_task(
    task_id: int,
    data: PublishTaskIdentityRequest,
    db: DbSession,
    settings: SettingsDep,
    storage: VideoArtifactStorageDep,
) -> ExecutionJobCreateRead:
    return YouTubePublishJobService(db, settings, storage).enqueue_refresh(
        task_id, data
    )
