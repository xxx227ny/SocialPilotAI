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
from app.models import VideoRenderArtifact
from app.repositories.product import ProductRepository
from app.repositories.social import SocialRepository
from app.schemas.social import (
    InstagramMediaSpecificationRead,
    InstagramPublishingMetadata,
    InstagramSubmitPreflightRead,
    PublishArtifactCandidateRead,
)
from app.services.instagram_media_probe import (
    InstagramMediaProbe,
    InstagramMediaProbeError,
    InstagramMediaSpecification,
    validate_instagram_reel_media,
)
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_render_operation_service import (
    VerifiedVideoArtifact,
    VideoArtifactAccessService,
)

INSTAGRAM_PREFLIGHT_LIFETIME = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class FrozenInstagramPublishInput:
    product_id: int
    social_account_id: int
    professional_account_id: str
    artifact_id: int
    render_task_id: int
    video_project_id: int
    copy_matrix_id: int
    marketing_strategy_id: int
    content_type: str
    size_bytes: int
    sha256: str
    safe_path_digest: str
    media: InstagramMediaSpecification
    caption: str
    input_digest: str
    verified: VerifiedVideoArtifact


class InstagramPublishPreflightService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        artifact_storage: VideoArtifactStorage,
        media_probe: InstagramMediaProbe,
    ) -> None:
        self.session = session
        self.settings = settings
        self.artifact_access = VideoArtifactAccessService(session, artifact_storage)
        self.media_probe = media_probe
        self.products = ProductRepository(session)
        self.social = SocialRepository(session)

    def run(
        self,
        product_id: int,
        data: InstagramPublishingMetadata,
        *,
        expires_at: datetime | None = None,
    ) -> InstagramSubmitPreflightRead:
        self._require_enabled()
        frozen = self.freeze(product_id, data)
        expiry = _as_utc(expires_at or datetime.now(UTC) + INSTAGRAM_PREFLIGHT_LIFETIME)
        now = datetime.now(UTC)
        if expiry <= now or expiry > now + INSTAGRAM_PREFLIGHT_LIFETIME:
            raise AppError("Instagram publishing Preflight expiry is invalid", 409)
        preflight_digest = _digest(
            {
                "contract": "instagram-reel-submit-preflight-v1",
                "input_digest": frozen.input_digest,
                "expires_at": expiry.isoformat(),
            }
        )
        account = self.social.get_account(data.social_account_id)
        missing: list[str] = []
        if account is None or account.connection_status != "CONNECTED":
            missing.append("Instagram Professional account is not connected")
        if account is None or not account.access_token_ciphertext:
            missing.append("Instagram authorization is unavailable")
        return InstagramSubmitPreflightRead(
            status="READY" if not missing else "BLOCKED",
            ready=not missing,
            missing_requirements=missing,
            input_digest=frozen.input_digest,
            preflight_digest=preflight_digest,
            expires_at=expiry,
            product_id=frozen.product_id,
            social_account_id=frozen.social_account_id,
            professional_account_id=frozen.professional_account_id,
            artifact_id=frozen.artifact_id,
            render_task_id=frozen.render_task_id,
            video_project_id=frozen.video_project_id,
            copy_matrix_id=frozen.copy_matrix_id,
            marketing_strategy_id=frozen.marketing_strategy_id,
            content_type=frozen.content_type,
            size_bytes=frozen.size_bytes,
            sha256=frozen.sha256,
            safe_path_digest=frozen.safe_path_digest,
            media=InstagramMediaSpecificationRead(**frozen.media.stable_payload()),
            caption_length=len(frozen.caption),
            share_to_feed=data.share_to_feed,
        )

    def freeze(
        self, product_id: int, data: InstagramPublishingMetadata
    ) -> FrozenInstagramPublishInput:
        self._require_enabled()
        product = self.products.get(product_id)
        account = self.social.get_account(data.social_account_id)
        if product is None:
            raise AppError("Product not found", 404)
        if (
            account is None
            or account.product_id != product_id
            or account.platform != "instagram"
        ):
            raise AppError("Instagram account not found for Product", 404)
        verified = self.artifact_access.resolve_verified(data.artifact_id)
        task = verified.artifact.video_render_task
        project = task.video_project if task is not None else None
        copy_matrix = project.copy_matrix if project is not None else None
        strategy = project.marketing_strategy if project is not None else None
        if (
            task is None
            or project is None
            or copy_matrix is None
            or strategy is None
            or project.product_id != product_id
            or project.platform != "Instagram Reels"
            or copy_matrix.product_id != product_id
            or strategy.product_id != product_id
            or project.copy_matrix_id != copy_matrix.id
            or project.marketing_strategy_id != strategy.id
            or copy_matrix.marketing_strategy_id != strategy.id
        ):
            raise AppError("Instagram artifact source identity is invalid", 409)
        actual_size = verified.path.stat().st_size
        actual_sha = _sha256_file(verified.path)
        if actual_size != verified.size_bytes or actual_sha != verified.sha256:
            raise AppError("Instagram artifact integrity has changed", 409)
        try:
            media = self.media_probe.probe(verified.path)
            validate_instagram_reel_media(
                media,
                content_type=verified.content_type,
                size_bytes=actual_size,
            )
        except InstagramMediaProbeError:
            raise AppError("Instagram Reel media is not eligible", 409) from None
        caption = build_instagram_caption(data.description, data.tags)
        path_identity = hashlib.sha256(
            str(verified.artifact.storage_path).encode("utf-8")
        ).hexdigest()
        stable = {
            "contract": "instagram-reel-submit-v1",
            "product": {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "selling_points": product.selling_points,
                "target_markets": product.target_markets,
            },
            "account": {
                "id": account.id,
                "professional_account_id": account.provider_account_id,
                "scopes": account.scopes,
                "status": account.connection_status,
            },
            "artifact": {
                "id": verified.artifact.id,
                "sha256": actual_sha,
                "size_bytes": actual_size,
                "content_type": verified.content_type,
                "safe_path_digest": path_identity,
            },
            "render_task": {
                "id": task.id,
                "status": task.status,
                "video_project_id": task.video_project_id,
                "scene_sequence": task.scene_sequence,
                "duration_seconds": task.duration_seconds,
                "aspect_ratio": task.aspect_ratio,
                "resolution": task.resolution,
            },
            "video_project": {
                "id": project.id,
                "product_id": project.product_id,
                "marketing_strategy_id": project.marketing_strategy_id,
                "copy_matrix_id": project.copy_matrix_id,
                "platform": project.platform,
                "title": project.title,
                "concept": project.concept,
                "duration_seconds": project.duration_seconds,
                "aspect_ratio": project.aspect_ratio,
                "scenes": project.scenes,
                "cta": project.cta,
            },
            "copy_matrix": {
                "id": copy_matrix.id,
                "product_id": copy_matrix.product_id,
                "marketing_strategy_id": copy_matrix.marketing_strategy_id,
                "copies": copy_matrix.copies,
            },
            "strategy": {
                "id": strategy.id,
                "product_id": strategy.product_id,
                "positioning": strategy.positioning,
                "audience_insights": strategy.audience_insights,
                "angles": strategy.angles,
                "risks": strategy.risks,
                "evidence": strategy.evidence,
            },
            "media": media.stable_payload(),
            "metadata": {
                "title": data.title,
                "description": data.description,
                "tags": data.tags,
                "caption": caption,
                "share_to_feed": data.share_to_feed,
                "privacy_status": "public",
                "made_for_kids": False,
                "synthetic_media": True,
                "notify_subscribers": False,
            },
        }
        return FrozenInstagramPublishInput(
            product_id=product_id,
            social_account_id=account.id,
            professional_account_id=account.provider_account_id,
            artifact_id=verified.artifact.id,
            render_task_id=task.id,
            video_project_id=project.id,
            copy_matrix_id=copy_matrix.id,
            marketing_strategy_id=strategy.id,
            content_type=verified.content_type,
            size_bytes=actual_size,
            sha256=actual_sha,
            safe_path_digest=path_identity,
            media=media,
            caption=caption,
            input_digest=_digest(stable),
            verified=verified,
        )

    def list_candidates(self, product_id: int) -> list[PublishArtifactCandidateRead]:
        if self.products.get(product_id) is None:
            raise AppError("Product not found", 404)
        candidates: list[PublishArtifactCandidateRead] = []
        for artifact in self.session.scalars(
            select(VideoRenderArtifact).order_by(VideoRenderArtifact.id)
        ):
            try:
                verified = self.artifact_access.resolve_verified(artifact.id)
                task = verified.artifact.video_render_task
                project = task.video_project
                if (
                    project.product_id != product_id
                    or project.platform != "Instagram Reels"
                ):
                    continue
            except (AppError, AttributeError):
                continue
            candidates.append(
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
        return candidates

    def _require_enabled(self) -> None:
        if not self.settings.enable_instagram_publishing:
            raise AppError("Instagram publishing is disabled by the server", 503)


def build_instagram_caption(description: str, tags: list[str]) -> str:
    hashtags = " ".join(f"#{tag}" for tag in tags)
    caption = "\n\n".join(part for part in (description, hashtags) if part)
    if len(caption) > 2200:
        raise AppError("Instagram caption is too long", 422)
    return caption


def preflight_digest(input_digest: str, expires_at: datetime) -> str:
    return _digest(
        {
            "contract": "instagram-reel-submit-preflight-v1",
            "input_digest": input_digest,
            "expires_at": _as_utc(expires_at).isoformat(),
        }
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
