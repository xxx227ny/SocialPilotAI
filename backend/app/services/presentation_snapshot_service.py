from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import (
    AdCampaign,
    CopyMatrix,
    MarketingBrief,
    MarketingStrategy,
    PresentationSnapshot,
    Product,
    PublishTask,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.repositories.campaign import CampaignRepository
from app.repositories.presentation_snapshot import (
    PresentationSnapshotRepository,
)
from app.schemas.presentation_snapshot import (
    PresentationSnapshotCreate,
    PresentationSnapshotCreateRead,
    PresentationSnapshotRead,
)
from app.services.metrics_service import MetricsService
from app.services.video_artifact_storage import VideoArtifactStorage
from app.services.video_render_operation_service import VideoArtifactAccessService

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_CREATION_LOCK = threading.Lock()
SECTION_NAMES = (
    "marketing_brief",
    "marketing_strategy",
    "copy_matrix",
    "video_project",
    "render_task",
    "artifact",
    "publish_task",
    "campaigns",
)


@dataclass(frozen=True, slots=True)
class ArtifactSnapshotCopy:
    relative_path: str
    created: bool


class PresentationSnapshotService:
    """Capture an exact, provider-free and immutable Presentation source set."""

    def __init__(
        self,
        session: Session,
        artifact_storage: VideoArtifactStorage | None = None,
    ) -> None:
        self.session = session
        self.artifact_storage = artifact_storage
        self.repository = PresentationSnapshotRepository(session)

    def create(
        self,
        product_id: int,
        data: PresentationSnapshotCreate,
    ) -> PresentationSnapshotCreateRead:
        normalized_data = data.model_copy(
            update={"campaign_ids": sorted(data.campaign_ids)}
        )
        with SNAPSHOT_CREATION_LOCK:
            return self._create_locked(product_id, normalized_data)

    def _create_locked(
        self,
        product_id: int,
        data: PresentationSnapshotCreate,
    ) -> PresentationSnapshotCreateRead:
        product = self._require(Product, product_id, "Product")
        brief = self._optional(MarketingBrief, data.marketing_brief_id)
        strategy = self._optional(
            MarketingStrategy, data.marketing_strategy_id
        )
        copy_matrix = self._optional(CopyMatrix, data.copy_matrix_id)
        video_project = self._optional(VideoProject, data.video_project_id)
        render_task = self._optional(VideoRenderTask, data.render_task_id)
        artifact = self._optional(VideoRenderArtifact, data.artifact_id)
        publish_task = self._optional(PublishTask, data.publish_task_id)
        campaigns = self._campaigns(data.campaign_ids)

        self._validate_exact_chain(
            product_id=product_id,
            brief=brief,
            strategy=strategy,
            copy_matrix=copy_matrix,
            video_project=video_project,
            render_task=render_task,
            artifact=artifact,
            publish_task=publish_task,
            campaigns=campaigns,
        )
        artifact_capture = self._artifact_capture(artifact)
        missing = self._missing_sections(data)
        payload = self._payload(
            product=product,
            brief=brief,
            strategy=strategy,
            copy_matrix=copy_matrix,
            video_project=video_project,
            render_task=render_task,
            artifact=artifact,
            artifact_capture=artifact_capture,
            publish_task=publish_task,
            campaigns=campaigns,
            missing=missing,
        )
        digest = self._digest(payload)
        existing = self.repository.get_by_digest(digest)
        if existing is not None:
            return self._result(existing, reused=True)

        artifact_copy = self._copy_artifact(digest, artifact_capture)
        snapshot = PresentationSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            digest=digest,
            product_id=product_id,
            marketing_brief_id=data.marketing_brief_id,
            marketing_strategy_id=data.marketing_strategy_id,
            copy_matrix_id=data.copy_matrix_id,
            video_project_id=data.video_project_id,
            render_task_id=data.render_task_id,
            artifact_id=data.artifact_id,
            publish_task_id=data.publish_task_id,
            campaign_ids=list(data.campaign_ids),
            missing_sections=missing,
            snapshot_payload=payload,
            artifact_sha256=(
                artifact_capture["sha256"] if artifact_capture else None
            ),
            artifact_snapshot_path=(
                artifact_copy.relative_path if artifact_copy else None
            ),
        )
        try:
            saved, reused = self.repository.create_or_reuse(snapshot)
        except Exception:
            self.session.rollback()
            self._cleanup_failed_artifact_copy(artifact_copy)
            raise
        return self._result(saved, reused=reused)

    def get(self, snapshot_id: int) -> PresentationSnapshotRead:
        snapshot = self.repository.get(snapshot_id)
        if snapshot is None:
            raise AppError("Presentation snapshot not found", 404)
        return PresentationSnapshotRead.model_validate(snapshot)

    def list_for_product(self, product_id: int) -> list[PresentationSnapshotRead]:
        self._require(Product, product_id, "Product")
        return [
            PresentationSnapshotRead.model_validate(snapshot)
            for snapshot in self.repository.list_by_product(product_id)
        ]

    def _validate_exact_chain(
        self,
        *,
        product_id: int,
        brief: MarketingBrief | None,
        strategy: MarketingStrategy | None,
        copy_matrix: CopyMatrix | None,
        video_project: VideoProject | None,
        render_task: VideoRenderTask | None,
        artifact: VideoRenderArtifact | None,
        publish_task: PublishTask | None,
        campaigns: list[AdCampaign],
    ) -> None:
        if brief is not None and brief.product_id != product_id:
            self._mismatch("MarketingBrief", product_id)
        if strategy is not None and strategy.product_id != product_id:
            self._mismatch("MarketingStrategy", product_id)
        if copy_matrix is not None:
            if strategy is None:
                raise AppError(
                    "MarketingStrategy identity is required for CopyMatrix", 409
                )
            if (
                copy_matrix.product_id != product_id
                or copy_matrix.marketing_strategy_id != strategy.id
            ):
                self._mismatch("CopyMatrix", product_id)
        if video_project is not None:
            if strategy is None or copy_matrix is None:
                raise AppError(
                    "Strategy and CopyMatrix identities are required for VideoProject",
                    409,
                )
            if (
                video_project.product_id != product_id
                or video_project.marketing_strategy_id != strategy.id
                or video_project.copy_matrix_id != copy_matrix.id
            ):
                self._mismatch("VideoProject", product_id)
        if render_task is not None:
            if video_project is None:
                raise AppError(
                    "VideoProject identity is required for RenderTask", 409
                )
            if render_task.video_project_id != video_project.id:
                self._mismatch("RenderTask", product_id)
        if artifact is not None:
            if render_task is None:
                raise AppError("RenderTask identity is required for Artifact", 409)
            if artifact.video_render_task_id != render_task.id:
                self._mismatch("Artifact", product_id)
        if publish_task is not None:
            if artifact is None:
                raise AppError("Artifact identity is required for PublishTask", 409)
            if (
                publish_task.product_id != product_id
                or publish_task.artifact_id != artifact.id
            ):
                self._mismatch("PublishTask", product_id)
        if any(campaign.product_id != product_id for campaign in campaigns):
            self._mismatch("Campaign", product_id)

    def _artifact_capture(
        self, artifact: VideoRenderArtifact | None
    ) -> dict[str, object] | None:
        if artifact is None:
            return None
        if self.artifact_storage is None:
            raise AppError("Artifact storage is not configured", 503)
        verified = VideoArtifactAccessService(
            self.session, self.artifact_storage
        ).resolve_verified(artifact.id)
        actual_sha256 = self._file_digest(verified.path)
        if actual_sha256 != verified.sha256:
            raise AppError("Stable video artifact hash does not match metadata", 409)
        return {
            "path": verified.path,
            "content_type": verified.content_type,
            "size_bytes": verified.size_bytes,
            "sha256": actual_sha256,
            "render_task_id": verified.artifact.video_render_task_id,
        }

    def _copy_artifact(
        self,
        digest: str,
        capture: dict[str, object] | None,
    ) -> ArtifactSnapshotCopy | None:
        if capture is None:
            return None
        if self.artifact_storage is None:
            raise AppError("Artifact storage is not configured", 503)
        path = capture["path"]
        content_type = capture["content_type"]
        if not hasattr(path, "read_bytes") or not isinstance(content_type, str):
            raise AppError("Stable video artifact capture is invalid", 409)
        content = path.read_bytes()
        immutable_store = getattr(self.artifact_storage, "store_immutable", None)
        if callable(immutable_store):
            stored, created = immutable_store(
                task_id=int(digest[:12], 16),
                content=content,
                content_type=content_type,
            )
        else:
            stored = self.artifact_storage.store(
                task_id=int(digest[:12], 16),
                content=content,
                content_type=content_type,
            )
            created = True
        if stored.sha256 != capture["sha256"]:
            raise AppError("Presentation artifact snapshot hash mismatch", 409)
        return ArtifactSnapshotCopy(stored.relative_path, created)

    def _cleanup_failed_artifact_copy(
        self,
        artifact_copy: ArtifactSnapshotCopy | None,
    ) -> None:
        if (
            artifact_copy is None
            or not artifact_copy.created
            or self.artifact_storage is None
        ):
            return
        referenced = self.repository.get_by_artifact_snapshot_path(
            artifact_copy.relative_path
        )
        if referenced is None:
            self.artifact_storage.delete(artifact_copy.relative_path)

    def _payload(
        self,
        *,
        product: Product,
        brief: MarketingBrief | None,
        strategy: MarketingStrategy | None,
        copy_matrix: CopyMatrix | None,
        video_project: VideoProject | None,
        render_task: VideoRenderTask | None,
        artifact: VideoRenderArtifact | None,
        artifact_capture: dict[str, object] | None,
        publish_task: PublishTask | None,
        campaigns: list[AdCampaign],
        missing: list[str],
    ) -> dict[str, object]:
        metrics = MetricsService.calculate(campaigns) if campaigns else None
        payload: dict[str, object] = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "source_ids": {
                "product_id": product.id,
                "marketing_brief_id": brief.id if brief else None,
                "marketing_strategy_id": strategy.id if strategy else None,
                "copy_matrix_id": copy_matrix.id if copy_matrix else None,
                "video_project_id": video_project.id if video_project else None,
                "render_task_id": render_task.id if render_task else None,
                "artifact_id": artifact.id if artifact else None,
                "publish_task_id": publish_task.id if publish_task else None,
                "campaign_ids": [campaign.id for campaign in campaigns],
            },
            "missing_sections": missing,
            "product": self._product_data(product),
            "marketing_brief": self._brief_data(brief),
            "marketing_strategy": self._strategy_data(strategy),
            "copy_matrix": self._copy_data(copy_matrix),
            "video_project": self._video_data(video_project),
            "render_task": self._render_data(render_task),
            "artifact": self._artifact_data(artifact, artifact_capture),
            "publish_task": self._publish_data(publish_task),
            "campaigns": [self._campaign_data(item) for item in campaigns],
            "campaign_metrics": (
                metrics.model_dump(mode="json") if metrics else None
            ),
        }
        return json.loads(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )

    @staticmethod
    def _product_data(product: Product) -> dict[str, object]:
        return {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "selling_points": product.selling_points,
            "target_markets": product.target_markets,
            "created_at": _iso(product.created_at),
            "updated_at": _iso(product.updated_at),
        }

    @staticmethod
    def _brief_data(brief: MarketingBrief | None) -> dict[str, object] | None:
        if brief is None:
            return None
        return {
            "id": brief.id,
            "product_id": brief.product_id,
            "audience": brief.audience,
            "language": brief.language,
            "platforms": brief.platforms,
            "tone": brief.tone,
            "objective": brief.objective,
            "created_at": _iso(brief.created_at),
        }

    @staticmethod
    def _strategy_data(
        strategy: MarketingStrategy | None,
    ) -> dict[str, object] | None:
        if strategy is None:
            return None
        return {
            "id": strategy.id,
            "product_id": strategy.product_id,
            "positioning": strategy.positioning,
            "audience_insights": strategy.audience_insights,
            "angles": strategy.angles,
            "risks": strategy.risks,
            "evidence": strategy.evidence,
            "created_at": _iso(strategy.created_at),
        }

    @staticmethod
    def _copy_data(copy_matrix: CopyMatrix | None) -> dict[str, object] | None:
        if copy_matrix is None:
            return None
        return {
            "id": copy_matrix.id,
            "product_id": copy_matrix.product_id,
            "marketing_strategy_id": copy_matrix.marketing_strategy_id,
            "copies": copy_matrix.copies,
            "created_at": _iso(copy_matrix.created_at),
        }

    @staticmethod
    def _video_data(video: VideoProject | None) -> dict[str, object] | None:
        if video is None:
            return None
        return {
            "id": video.id,
            "product_id": video.product_id,
            "marketing_strategy_id": video.marketing_strategy_id,
            "copy_matrix_id": video.copy_matrix_id,
            "platform": video.platform,
            "title": video.title,
            "concept": video.concept,
            "duration_seconds": video.duration_seconds,
            "aspect_ratio": video.aspect_ratio,
            "scenes": video.scenes,
            "cta": video.cta,
            "status": video.status,
            "created_at": _iso(video.created_at),
            "updated_at": _iso(video.updated_at),
        }

    @staticmethod
    def _render_data(task: VideoRenderTask | None) -> dict[str, object] | None:
        if task is None:
            return None
        return {
            "id": task.id,
            "video_project_id": task.video_project_id,
            "scene_sequence": task.scene_sequence,
            "status": task.status,
            "provider_name": task.provider_name,
            "duration_seconds": task.duration_seconds,
            "aspect_ratio": task.aspect_ratio,
            "resolution": task.resolution,
            "created_at": _iso(task.created_at),
            "updated_at": _iso(task.updated_at),
        }

    @staticmethod
    def _artifact_data(
        artifact: VideoRenderArtifact | None,
        capture: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if artifact is None or capture is None:
            return None
        return {
            "id": artifact.id,
            "video_render_task_id": artifact.video_render_task_id,
            "metadata": artifact.artifact_metadata,
            "content_type": capture["content_type"],
            "size_bytes": capture["size_bytes"],
            "sha256": capture["sha256"],
            "created_at": _iso(artifact.created_at),
            "updated_at": _iso(artifact.updated_at),
        }

    @staticmethod
    def _publish_data(task: PublishTask | None) -> dict[str, object] | None:
        if task is None:
            return None
        return {
            "id": task.id,
            "product_id": task.product_id,
            "social_account_id": task.social_account_id,
            "artifact_id": task.artifact_id,
            "platform": task.platform,
            "title": task.title,
            "description": task.description,
            "tags": task.tags,
            "privacy_status": task.privacy_status,
            "made_for_kids": task.made_for_kids,
            "synthetic_media": task.synthetic_media,
            "notify_subscribers": task.notify_subscribers,
            "status": task.status,
            "provider_video_id": task.provider_video_id,
            "uncertain": task.uncertain,
            "safe_error_code": task.safe_error_code,
            "submitted_at": _iso(task.submitted_at),
            "completed_at": _iso(task.completed_at),
        }

    @staticmethod
    def _campaign_data(campaign: AdCampaign) -> dict[str, object]:
        return {
            "id": campaign.id,
            "product_id": campaign.product_id,
            "platform": campaign.platform,
            "campaign_name": campaign.campaign_name,
            "date": _iso(campaign.date),
            "impressions": campaign.impressions,
            "clicks": campaign.clicks,
            "conversions": campaign.conversions,
            "spend": str(campaign.spend),
            "revenue": str(campaign.revenue),
            "created_at": _iso(campaign.created_at),
        }

    def _campaigns(self, campaign_ids: list[int]) -> list[AdCampaign]:
        campaigns = CampaignRepository(self.session).list_by_ids(campaign_ids)
        by_id = {campaign.id: campaign for campaign in campaigns}
        if any(campaign_id not in by_id for campaign_id in campaign_ids):
            raise AppError("Campaign not found", 404)
        return [by_id[campaign_id] for campaign_id in campaign_ids]

    def _optional(self, model: type, source_id: int | None):  # type: ignore[no-untyped-def]
        if source_id is None:
            return None
        return self._require(model, source_id, model.__name__)

    def _require(self, model: type, source_id: int, label: str):  # type: ignore[no-untyped-def]
        record = self.session.get(model, source_id)
        if record is None:
            raise AppError(f"{label} not found", 404)
        return record

    @staticmethod
    def _missing_sections(data: PresentationSnapshotCreate) -> list[str]:
        values = {
            "marketing_brief": data.marketing_brief_id,
            "marketing_strategy": data.marketing_strategy_id,
            "copy_matrix": data.copy_matrix_id,
            "video_project": data.video_project_id,
            "render_task": data.render_task_id,
            "artifact": data.artifact_id,
            "publish_task": data.publish_task_id,
            "campaigns": data.campaign_ids or None,
        }
        return [name for name in SECTION_NAMES if values[name] is None]

    @staticmethod
    def _digest(payload: dict[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _file_digest(path) -> str:  # type: ignore[no-untyped-def]
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _mismatch(label: str, product_id: int) -> None:
        raise AppError(
            f"{label} does not belong to the exact Product chain #{product_id}",
            409,
        )

    @staticmethod
    def _result(
        snapshot: PresentationSnapshot,
        *,
        reused: bool,
    ) -> PresentationSnapshotCreateRead:
        return PresentationSnapshotCreateRead(
            snapshot=PresentationSnapshotRead.model_validate(snapshot),
            reused=reused,
            provider_calls=0,
        )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
