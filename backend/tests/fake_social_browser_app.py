"""Local-only Fake app for browser smoke; never contacts Google or YouTube."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["SOCIALPILOT_DISABLE_DOTENV"] = "true"

from fastapi import FastAPI
from sqlalchemy import select

from app.api.dependencies import get_youtube_provider
from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models import Product, VideoRenderArtifact
from app.providers.youtube_provider import (
    YOUTUBE_SCOPES,
    OAuthTokens,
    YouTubeChannel,
    YouTubeProviderError,
    YouTubeUploadResult,
    YouTubeUploadUncertain,
    YouTubeVideoStatus,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_render_service import VideoRenderService
from tests.test_video_render_service import create_video_project, render_request


class BrowserFakeYouTubeProvider:
    def __init__(self) -> None:
        self.authorization_calls = 0
        self.exchange_calls = 0
        self.channel_calls = 0
        self.upload_calls = 0
        self.status_calls = 0
        self.refresh_calls = 0
        self.revoke_calls = 0

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        del code_challenge
        self.authorization_calls += 1
        return (
            "http://127.0.0.1:8000/api/v1/social-accounts/youtube/callback"
            f"?state={state}&code=fake-browser-code"
        )

    async def exchange_code(self, *, code: str, code_verifier: str) -> OAuthTokens:
        assert code == "fake-browser-code"
        assert len(code_verifier) >= 43
        self.exchange_calls += 1
        return OAuthTokens(
            access_token="fake-browser-access",
            refresh_token="fake-browser-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=YOUTUBE_SCOPES,
        )

    async def get_channel(self, access_token: str) -> YouTubeChannel:
        assert access_token == "fake-browser-access"
        self.channel_calls += 1
        return YouTubeChannel("UC_BROWSER_FAKE", "Browser Fake Channel")

    async def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        assert refresh_token == "fake-browser-refresh"
        self.refresh_calls += 1
        return OAuthTokens(
            access_token="fake-browser-refreshed",
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            scopes=YOUTUBE_SCOPES,
        )

    async def revoke_token(self, token: str) -> None:
        assert token.startswith("fake-browser-")
        self.revoke_calls += 1

    async def upload_video(self, **kwargs: object) -> YouTubeUploadResult:
        self.upload_calls += 1
        title = str(kwargs["title"])
        path = Path(str(kwargs["path"]))
        assert path.is_file()
        assert kwargs["made_for_kids"] is False
        if "UNCERTAIN" in title:
            raise YouTubeUploadUncertain("https://upload.example/fake-browser-session")
        if "FAILED" in title:
            raise YouTubeProviderError("fake_upload_failed", status_code=400)
        return YouTubeUploadResult(f"fake-browser-video-{self.upload_calls}")

    async def get_video_status(
        self, *, access_token: str, video_id: str
    ) -> YouTubeVideoStatus:
        assert access_token.startswith("fake-browser-")
        assert video_id.startswith("fake-browser-video-")
        self.status_calls += 1
        return YouTubeVideoStatus("SUCCEEDED")


provider = BrowserFakeYouTubeProvider()
app.dependency_overrides[get_youtube_provider] = lambda: provider
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def fake_lifespan(application: FastAPI):
    async with original_lifespan(application):
        _seed_fake_artifact()
        yield


app.router.lifespan_context = fake_lifespan


@app.get("/api/v1/fake-social-smoke/counters")
def fake_counters() -> dict[str, int]:
    return {
        "authorization": provider.authorization_calls,
        "exchange": provider.exchange_calls,
        "channel": provider.channel_calls,
        "upload": provider.upload_calls,
        "status": provider.status_calls,
        "refresh": provider.refresh_calls,
        "revoke": provider.revoke_calls,
    }


def _seed_fake_artifact() -> None:
    root_value = settings.video_artifact_storage_root
    if not root_value:
        raise RuntimeError("Fake artifact root is not configured")
    with SessionLocal() as session:
        if session.scalar(select(Product)) is not None:
            return
        project = create_video_project(session)
        service = VideoRenderService(session)
        task = service.create_render_task(
            project.id, render_request("fake-browser-render")
        )
        service.transition_status(task.id, "SUBMITTED")
        task = service.transition_status(task.id, "SUCCEEDED")
        stored = LocalVideoArtifactStorage(
            Path(root_value), settings.video_artifact_max_bytes
        ).store(
            task_id=task.id,
            content=b"fake-browser-video-content",
            content_type="video/mp4",
        )
        session.add(
            VideoRenderArtifact(
                video_render_task_id=task.id,
                storage_path=stored.relative_path,
                artifact_metadata={
                    "content_type": stored.content_type,
                    "size_bytes": stored.size_bytes,
                    "sha256": stored.sha256,
                },
            )
        )
        session.commit()
