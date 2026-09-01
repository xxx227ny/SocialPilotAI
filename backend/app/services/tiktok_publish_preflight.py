from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.video_render_artifact import VideoRenderArtifact
from app.repositories.product import ProductRepository
from app.repositories.social import SocialRepository
from app.schemas.social import (
    PublishArtifactCandidateRead,
    TikTokMediaSpecificationRead,
    TikTokPublishingMetadata,
    TikTokSubmitPreflightRead,
)
from app.services.tiktok_media_probe import (
    TikTokMediaProbe,
    TikTokMediaProbeError,
    TikTokMediaSpecification,
    validate_tiktok_media,
)
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_render_operation_service import (
    VerifiedVideoArtifact,
    VideoArtifactAccessService,
)

TIKTOK_PREFLIGHT_LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class FrozenTikTokPublishInput:
    product_id: int
    social_account_id: int
    creator_info_snapshot_id: int
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int
    marketing_strategy_id: int
    content_type: str
    size_bytes: int
    sha256: str
    safe_path_digest: str
    caption: str
    media: TikTokMediaSpecification
    input_digest: str
    verified: VerifiedVideoArtifact


class TikTokPublishPreflightService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        storage: VideoArtifactStorage,
        media_probe: TikTokMediaProbe,
    ) -> None:
        self.session, self.settings = session, settings
        self.artifact_access = VideoArtifactAccessService(session, storage)
        self.media_probe = media_probe
        self.products = ProductRepository(session)
        self.social = SocialRepository(session)

    def run(
        self,
        product_id: int,
        data: TikTokPublishingMetadata,
        *,
        expires_at: datetime | None = None,
    ) -> TikTokSubmitPreflightRead:
        frozen = self.freeze(product_id, data)
        expiry = _utc(expires_at or datetime.now(UTC) + TIKTOK_PREFLIGHT_LIFETIME)
        now = datetime.now(UTC)
        if expiry <= now or expiry > now + TIKTOK_PREFLIGHT_LIFETIME:
            raise AppError("TikTok Preflight expiry is invalid", 409)
        digest = preflight_digest(frozen.input_digest, expiry)
        return TikTokSubmitPreflightRead(
            status="READY",
            ready=True,
            missing_requirements=[],
            input_digest=frozen.input_digest,
            preflight_digest=digest,
            expires_at=expiry,
            product_id=product_id,
            social_account_id=frozen.social_account_id,
            creator_info_snapshot_id=frozen.creator_info_snapshot_id,
            artifact_id=frozen.artifact_id,
            render_task_id=frozen.render_task_id,
            video_project_id=frozen.video_project_id,
            copy_matrix_id=frozen.copy_matrix_id,
            marketing_strategy_id=frozen.marketing_strategy_id,
            content_type=frozen.content_type,
            size_bytes=frozen.size_bytes,
            sha256=frozen.sha256,
            safe_path_digest=frozen.safe_path_digest,
            media=TikTokMediaSpecificationRead(**frozen.media.stable_payload()),
            caption_length_utf16=len(frozen.caption.encode("utf-16-le")) // 2,
        )

    def freeze(
        self, product_id: int, data: TikTokPublishingMetadata
    ) -> FrozenTikTokPublishInput:
        self._enabled()
        product = self.products.get(product_id)
        account = self.social.get_account(data.social_account_id)
        snapshot = self.social.get_tiktok_creator_snapshot(
            data.creator_info_snapshot_id
        )
        if product is None:
            raise AppError("Product not found", 404)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "tiktok"
            or account.connection_status != "CONNECTED"
        ):
            raise AppError("TikTok account not connected for Product", 409)
        if set(account.scopes) != {"user.info.basic", "video.publish"}:
            raise AppError("TikTok account scopes are incomplete", 409)
        if (
            snapshot is None
            or snapshot.product_id != product_id
            or snapshot.social_account_id != account.id
        ):
            raise AppError("TikTok creator snapshot identity mismatch", 409)
        if _utc(snapshot.expires_at) <= datetime.now(UTC):
            raise AppError("TikTok creator snapshot has expired", 409)
        if data.privacy_status not in snapshot.privacy_level_options:
            raise AppError("TikTok privacy choice is unavailable", 409)
        if (
            (snapshot.comment_disabled and not data.disable_comment)
            or (snapshot.duet_disabled and not data.disable_duet)
            or (snapshot.stitch_disabled and not data.disable_stitch)
        ):
            raise AppError("TikTok capability must remain disabled", 409)
        verified = self.artifact_access.resolve_verified(data.artifact_id)
        render = verified.artifact.video_render_task
        project = render.video_project if render else None
        copy = project.copy_matrix if project else None
        strategy = project.marketing_strategy if project else None
        if (
            render is None
            or render.status != "SUCCEEDED"
            or project is None
            or copy is None
            or strategy is None
            or project.product_id != product_id
            or project.platform != "TikTok"
            or copy.product_id != product_id
            or strategy.product_id != product_id
            or project.copy_matrix_id != copy.id
            or project.marketing_strategy_id != strategy.id
            or copy.marketing_strategy_id != strategy.id
        ):
            raise AppError("TikTok artifact source identity is invalid", 409)
        size = verified.path.stat().st_size
        sha = _sha256_file(verified.path)
        if size != verified.size_bytes or sha != verified.sha256:
            raise AppError("TikTok artifact integrity has changed", 409)
        try:
            media = self.media_probe.probe(verified.path)
            validate_tiktok_media(
                media,
                content_type=verified.content_type,
                size_bytes=size,
                max_duration_seconds=snapshot.max_video_post_duration_sec,
            )
        except TikTokMediaProbeError:
            raise AppError("TikTok media is not eligible", 409) from None
        caption = build_tiktok_caption(data.description, data.tags)
        safe_path_digest = hashlib.sha256(
            str(verified.artifact.storage_path).encode("utf-8")
        ).hexdigest()
        stable = {
            "contract": "tiktok-direct-post-v1",
            "product_id": product_id,
            "account": {
                "id": account.id,
                "identity": account.provider_account_id,
                "scopes": account.scopes,
                "status": account.connection_status,
            },
            "creator_snapshot": {
                "id": snapshot.id,
                "digest": snapshot.request_digest,
                "provider_identity_digest": snapshot.provider_identity_digest,
                "privacy": snapshot.privacy_level_options,
                "comment_disabled": snapshot.comment_disabled,
                "duet_disabled": snapshot.duet_disabled,
                "stitch_disabled": snapshot.stitch_disabled,
                "max_video_post_duration_sec": snapshot.max_video_post_duration_sec,
                "expires_at": _utc(snapshot.expires_at).isoformat(),
            },
            "artifact": {
                "id": verified.artifact.id,
                "size": size,
                "sha256": sha,
                "content_type": verified.content_type,
                "safe_path_digest": safe_path_digest,
            },
            "source": {
                "render_task_id": render.id,
                "video_project_id": project.id,
                "copy_matrix_id": copy.id,
                "marketing_strategy_id": strategy.id,
            },
            "media": media.stable_payload(),
            "caption": caption,
            "title": data.title,
            "settings": {
                "privacy_status": data.privacy_status,
                "disable_comment": data.disable_comment,
                "disable_duet": data.disable_duet,
                "disable_stitch": data.disable_stitch,
                "brand_content_toggle": data.brand_content_toggle,
                "brand_organic_toggle": data.brand_organic_toggle,
            },
        }
        return FrozenTikTokPublishInput(
            product_id,
            account.id,
            snapshot.id,
            verified.artifact.id,
            render.id,
            project.id,
            copy.id,
            strategy.id,
            verified.content_type,
            size,
            sha,
            safe_path_digest,
            caption,
            media,
            _digest(stable),
            verified,
        )

    def list_candidates(self, product_id: int) -> list[PublishArtifactCandidateRead]:
        if self.products.get(product_id) is None:
            raise AppError("Product not found", 404)
        result = []
        for artifact in self.session.scalars(
            select(VideoRenderArtifact).order_by(VideoRenderArtifact.id)
        ):
            try:
                verified = self.artifact_access.resolve_verified(artifact.id)
                task, project = (
                    verified.artifact.video_render_task,
                    verified.artifact.video_render_task.video_project,
                )
                if (
                    project.product_id != product_id
                    or project.platform != "TikTok"
                    or task.status != "SUCCEEDED"
                ):
                    continue
                result.append(
                    PublishArtifactCandidateRead(
                        artifact_id=artifact.id,
                        render_task_id=task.id,
                        video_project_id=project.id,
                        copy_matrix_id=project.copy_matrix_id,
                        content_type=verified.content_type,
                        size_bytes=verified.size_bytes,
                        sha256=verified.sha256,
                        created_at=artifact.created_at,
                    )
                )
            except (AppError, AttributeError):
                continue
        return result

    def _enabled(self) -> None:
        if not self.settings.enable_tiktok_publishing:
            raise AppError("TikTok publishing is disabled by the server", 503)


def build_tiktok_caption(description: str, tags: list[str]) -> str:
    caption = " ".join(filter(None, [description, *[f"#{tag}" for tag in tags]]))
    if len(caption.encode("utf-16-le")) // 2 > 2200:
        raise AppError("TikTok caption is too long", 422)
    return caption


def preflight_digest(input_digest: str, expires_at: datetime) -> str:
    return _digest(
        {
            "contract": "tiktok-direct-post-preflight-v1",
            "input_digest": input_digest,
            "expires_at": _utc(expires_at).isoformat(),
        }
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
