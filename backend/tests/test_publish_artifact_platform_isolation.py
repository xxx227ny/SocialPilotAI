from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import VideoRenderArtifact
from app.services.instagram_publish_preflight import InstagramPublishPreflightService
from app.services.social_service import YouTubePublishingService
from app.services.tiktok_publish_preflight import TikTokPublishPreflightService
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from tests.test_social_publishing import create_publishable_artifact


class UnusedMediaProbe:
    def probe(self, path: Path) -> None:
        raise AssertionError(f"candidate listing must not probe media: {path}")


def test_publish_candidates_are_isolated_by_target_platform(
    db_session: Session, tmp_path: Path
) -> None:
    settings = Settings(_env_file=None)
    storage = LocalVideoArtifactStorage(tmp_path.resolve(), 1_000_000)
    product_id, artifact_id = create_publishable_artifact(db_session, storage)
    artifact = db_session.get(VideoRenderArtifact, artifact_id)
    assert artifact is not None
    project = artifact.video_render_task.video_project

    youtube = YouTubePublishingService(db_session, settings, None, storage)
    instagram = InstagramPublishPreflightService(
        db_session, settings, storage, UnusedMediaProbe()
    )
    tiktok = TikTokPublishPreflightService(
        db_session, settings, storage, UnusedMediaProbe()
    )

    expectations = {
        "YouTube Shorts": ([artifact_id], [], []),
        "Instagram Reels": ([], [artifact_id], []),
        "TikTok": ([], [], [artifact_id]),
    }
    for platform, expected in expectations.items():
        project.platform = platform
        db_session.commit()
        observed = (
            [item.artifact_id for item in youtube.list_candidates(product_id)],
            [item.artifact_id for item in instagram.list_candidates(product_id)],
            [item.artifact_id for item in tiktok.list_candidates(product_id)],
        )
        assert observed == expected
