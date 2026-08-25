from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import (
    ExecutionJob,
    ProductAsset,
    ProductVideoProductionBatch,
    ProductVideoProductionItem,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionAudioArtifact,
    VideoCompositionEnhancement,
    VideoCompositionEnhancementArtifact,
    VideoCompositionSubtitleArtifact,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
    VideoScriptVersion,
)
from app.models.product import utc_now
from app.repositories.video_render import VideoRenderTaskRepository
from app.repositories.video_render_artifact_repository import (
    VideoRenderArtifactRepository,
)
from app.schemas.product_marketing_video import (
    HappyHorseReferenceImage,
    HappyHorseVideoPreflightRequest,
    HappyHorseVideoRefreshRequest,
    HappyHorseVideoSubmitRequest,
    ProductImageShotRequest,
    ProductVideoPrepareRequest,
    ProductVideoProductionBatchRead,
    ProductVideoProductionCreateRead,
    ProductVideoProductionCreateRequest,
    ProductVideoProductionItemRead,
    ThreePlatformVideoPreflightRequest,
    VoiceoverSubmitRequest,
    WanxProductImageSubmitRequest,
)
from app.schemas.video_composition import (
    CompositionShotInput,
    VideoCompositionPreflightRequest,
    VideoCompositionSubmitRequest,
)
from app.schemas.video_composition_enhancement import (
    SubtitleCueInput,
    VideoCompositionEnhancementPreflightRequest,
    VideoCompositionEnhancementSubmitRequest,
)
from app.schemas.video_render_artifact import VideoRenderArtifactCreate
from app.services.happyhorse_product_video_service import (
    HappyHorseProductVideoService,
)
from app.services.three_platform_video_preflight import (
    ThreePlatformVideoPreflightService,
)
from app.services.video_artifact_storage import (
    LocalVideoArtifactStorage,
    VideoArtifactError,
)
from app.services.video_composition_enhancement_job_service import (
    VideoCompositionEnhancementJobService,
)
from app.services.video_composition_enhancement_preflight import (
    VideoCompositionEnhancementPreflightService,
)
from app.services.video_composition_job_service import VideoCompositionJobService
from app.services.video_composition_preflight import VideoCompositionPreflightService
from app.services.video_script_project_bridge import VideoScriptProjectBridge
from app.services.voiceover_generation_service import (
    VOICEOVER_GENERATE_V1,
    VoiceoverGenerationService,
)
from app.services.wanx_product_image_service import WanxProductImageService

PLATFORM_REQUEST_NAMES = {
    "tiktok": "TIKTOK",
    "youtube": "YOUTUBE_SHORTS",
    "instagram": "INSTAGRAM_REELS",
}
SHOT_MOTIONS = ("zoom_in", "pan_right", "zoom_out", "pan_left")
MAX_HAPPYHORSE_REFRESHES = 90
MAX_VOICEOVER_EXPLICIT_RETRIES = 1
MAX_VOICEOVER_CONFIG_RETRIES = 1
MAX_VOICEOVER_MANUAL_RATE_LIMIT_RETRIES = 3


class ProductVideoProductionBatchService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def create(
        self, product_id: int, data: ProductVideoProductionCreateRequest
    ) -> ProductVideoProductionCreateRead:
        existing = self._by_idempotency(data.idempotency_key)
        if existing is not None:
            if (
                existing.product_id != product_id
                or existing.input_digest != data.input_digest
            ):
                raise AppError("Idempotency key was used for different input", 409)
            return self._create_read(existing, reused=True)

        checked = ThreePlatformVideoPreflightService(self.session, self.settings).run(
            product_id,
            ThreePlatformVideoPreflightRequest(
                reference_product_asset_id=data.reference_product_asset_id,
                reference_product_asset_sha256=(data.reference_product_asset_sha256),
                selections=data.selections,
            ),
        )
        if checked.input_digest != data.input_digest:
            raise AppError("Three-platform frozen Preflight mismatch", 409)
        if not checked.ready:
            raise AppError("Three-platform production is not ready", 409)

        batch = ProductVideoProductionBatch(
            product_id=product_id,
            reference_product_asset_id=data.reference_product_asset_id,
            reference_product_asset_sha256=data.reference_product_asset_sha256,
            input_digest=checked.input_digest,
            idempotency_key=data.idempotency_key,
            status="WAITING",
            known_estimated_cost=checked.known_estimated_cost,
            currency=checked.currency,
            cost_estimate_complete=checked.cost_estimate_complete,
            cost_confirmed=data.cost_confirmed,
            provider_call_budget=checked.provider_call_count,
            frozen_preflight_json=checked.model_dump(mode="json"),
        )
        try:
            self.session.add(batch)
            self.session.flush()
            for platform in checked.platforms:
                self.session.add(
                    ProductVideoProductionItem(
                        production_batch_id=batch.id,
                        batch_video_variant_id=platform.variant_id,
                        script_version_id=platform.script_version_id,
                        platform=platform.platform,
                        status="WAITING",
                        stage="QUEUED",
                        stage_state_json={
                            "scene_count": platform.scene_count,
                            "wanx_image_generation_calls": (
                                platform.wanx_image_generation_calls
                            ),
                            "happyhorse_generation_calls": (
                                platform.happyhorse_generation_calls
                            ),
                            "qwen_tts_generation_calls": (
                                platform.qwen_tts_generation_calls
                            ),
                        },
                    )
                )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._by_idempotency(data.idempotency_key)
            if concurrent is None:
                raise
            if (
                concurrent.product_id != product_id
                or concurrent.input_digest != data.input_digest
            ):
                raise AppError(
                    "Idempotency key was used for different input", 409
                ) from None
            return self._create_read(concurrent, reused=True)
        return self._create_read(self._required(product_id, batch.id), reused=False)

    def get(self, product_id: int, batch_id: int) -> ProductVideoProductionCreateRead:
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def advance(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status == "PAUSED":
            raise AppError("Product video production batch is paused", 409)
        if batch.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return self._create_read(batch, reused=True)

        for item in batch.items:
            if item.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                continue
            if item.stage == "QUEUED":
                self._enqueue_wanx_images(batch, item)
            elif item.stage == "GENERATING_IMAGES":
                self._refresh_wanx_images(batch, item)
            elif item.stage == "PREPARING_VIDEO":
                self._prepare_and_submit_happyhorse(batch, item)
            elif item.stage == "GENERATING_VIDEO":
                self._refresh_happyhorse_submit(item)
            elif item.stage == "COMPOSING":
                self._advance_composition(batch, item)
            elif item.stage == "GENERATING_VOICEOVER":
                self._advance_voiceover(batch, item)
            elif item.stage == "ENHANCING":
                self._advance_enhancement(batch, item)
        self._sync_batch_status(batch)
        self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def pause(self, product_id: int, batch_id: int) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status in {"WAITING", "RUNNING"}:
            batch.status = "PAUSED"
            for job in self._execution_jobs(batch):
                if job.status == "QUEUED":
                    job.status = "PAUSED"
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def resume(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status == "PAUSED":
            for job in self._execution_jobs(batch):
                if job.status == "PAUSED":
                    job.status = "QUEUED"
            batch.status = "WAITING"
            self._sync_batch_status(batch)
            self.session.commit()
        elif batch.status == "PARTIAL_FAILED":
            recovered = False
            for item in batch.items:
                voiceover_job_id = item.stage_state_json.get("voiceover_job_id")
                voiceover_job = (
                    self.session.get(ExecutionJob, voiceover_job_id)
                    if isinstance(voiceover_job_id, int)
                    else None
                )
                if (
                    item.status == "FAILED"
                    and item.safe_error_code == "PRODUCTION_VOICEOVER_FAILED"
                    and item.stage == "GENERATING_VOICEOVER"
                    and voiceover_job is not None
                    and voiceover_job.status == "FAILED"
                    and voiceover_job.safe_error_code == "QWEN_TTS_FAILED"
                    and (
                        self._prepare_voice_config_recovery(item, voiceover_job)
                        or self._prepare_voice_rate_limit_recovery(item, voiceover_job)
                    )
                ):
                    item.status = "RUNNING"
                    item.safe_error_code = None
                    item.completed_at = None
                    recovered = True
                    continue
                task = (
                    self.session.get(VideoRenderTask, item.cloud_render_task_id)
                    if item.cloud_render_task_id is not None
                    else None
                )
                if (
                    item.status == "FAILED"
                    and item.safe_error_code
                    in {
                        "PRODUCTION_HAPPYHORSE_REFRESH_FAILED",
                        "PRODUCTION_HAPPYHORSE_REFRESH_RETRYABLE",
                    }
                    and self._happyhorse_refresh_is_retryable(task)
                ):
                    item.status = "RUNNING"
                    item.safe_error_code = None
                    item.completed_at = None
                    item.stage_state_json = {
                        **item.stage_state_json,
                        "happyhorse_refresh_job_id": None,
                    }
                    recovered = True
            if recovered:
                batch.status = "RUNNING"
                batch.completed_at = None
                self._sync_batch_status(batch)
                self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def cancel(
        self, product_id: int, batch_id: int
    ) -> ProductVideoProductionCreateRead:
        batch = self._required(product_id, batch_id)
        if batch.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            now = utc_now()
            batch.status = "CANCELLED"
            batch.completed_at = now
            for job in self._execution_jobs(batch):
                if job.status in {"QUEUED", "PAUSED"}:
                    job.status = "CANCELLED"
                    job.completed_at = now
            for item in batch.items:
                if item.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                    item.status = "CANCELLED"
                    item.completed_at = now
            self.session.commit()
        return self._create_read(self._required(product_id, batch_id), reused=True)

    def _enqueue_wanx_images(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        version = self.session.get(VideoScriptVersion, item.script_version_id)
        if (
            version is None
            or version.product_id != batch.product_id
            or version.batch_video_variant_id != item.batch_video_variant_id
            or version.platform != item.platform
            or not version.scenes
        ):
            self._fail_item(item, "PRODUCTION_SCRIPT_IDENTITY_INVALID")
            return
        service = WanxProductImageService(self.session, self.settings)
        job_ids: list[int] = []
        for scene in version.scenes:
            submitted = service.enqueue(
                batch.product_id,
                WanxProductImageSubmitRequest(
                    script_version_id=version.id,
                    scene_sequence=scene.sequence,
                    reference_product_asset_id=batch.reference_product_asset_id,
                    reference_product_asset_sha256=(
                        batch.reference_product_asset_sha256
                    ),
                    idempotency_key=(
                        f"production:{batch.id}:item:{item.id}:wanx:{scene.sequence}"
                    ),
                    cost_confirmed=True,
                ),
            )
            job_ids.append(submitted.job.id)
        item.stage_state_json = {
            **item.stage_state_json,
            "wanx_job_ids": job_ids,
            "wanx_product_asset_ids": [],
        }
        item.status = "RUNNING"
        item.stage = "GENERATING_IMAGES"

    def _refresh_wanx_images(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        job_ids = item.stage_state_json.get("wanx_job_ids")
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or not all(isinstance(job_id, int) and job_id > 0 for job_id in job_ids)
        ):
            self._fail_item(item, "PRODUCTION_WANX_JOB_IDENTITY_INVALID")
            return
        jobs = list(
            self.session.scalars(
                select(ExecutionJob)
                .where(ExecutionJob.id.in_(job_ids))
                .order_by(ExecutionJob.id)
            ).all()
        )
        if len(jobs) != len(job_ids):
            self._fail_item(item, "PRODUCTION_WANX_JOB_IDENTITY_INVALID")
            return
        if any(job.status == "SUBMIT_UNKNOWN" for job in jobs):
            self._fail_item(item, "PRODUCTION_WANX_SUBMIT_UNKNOWN")
            return
        if any(job.status in {"FAILED", "CANCELLED"} for job in jobs):
            self._fail_item(item, "PRODUCTION_WANX_IMAGE_FAILED")
            return
        if not all(job.status == "SUCCEEDED" for job in jobs):
            return

        asset_ids: list[int] = []
        for job in jobs:
            asset = (
                self.session.get(ProductAsset, job.result_entity_id)
                if job.result_entity_type == "product_asset"
                and job.result_entity_id is not None
                else None
            )
            if (
                asset is None
                or asset.product_id != batch.product_id
                or not asset.sha256
            ):
                self._fail_item(item, "PRODUCTION_WANX_RESULT_INVALID")
                return
            asset_ids.append(asset.id)
        item.stage_state_json = {
            **item.stage_state_json,
            "wanx_product_asset_ids": asset_ids,
        }
        item.stage = "PREPARING_VIDEO"

    def _prepare_and_submit_happyhorse(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        version = self.session.get(VideoScriptVersion, item.script_version_id)
        raw_asset_ids = item.stage_state_json.get("wanx_product_asset_ids")
        if (
            version is None
            or not isinstance(raw_asset_ids, list)
            or len(raw_asset_ids) != len(version.scenes)
            or not all(isinstance(asset_id, int) for asset_id in raw_asset_ids)
        ):
            self._fail_item(item, "PRODUCTION_WANX_RESULT_INVALID")
            return
        assets = [
            self.session.get(ProductAsset, asset_id) for asset_id in raw_asset_ids
        ]
        if any(
            asset is None
            or asset.product_id != batch.product_id
            or not asset.sha256
            or not asset.storage_identity
            for asset in assets
        ):
            self._fail_item(item, "PRODUCTION_WANX_RESULT_INVALID")
            return
        shots = [
            ProductImageShotRequest(
                scene_id=scene.id,
                product_asset_id=asset.id,
                product_asset_sha256=asset.sha256,
                motion=SHOT_MOTIONS[(scene.sequence - 1) % len(SHOT_MOTIONS)],
            )
            for scene, asset in zip(version.scenes, assets, strict=True)
            if asset is not None
        ]
        prepared = VideoScriptProjectBridge(self.session).prepare(
            batch.product_id,
            ProductVideoPrepareRequest(
                variant_id=item.batch_video_variant_id,
                script_version_id=item.script_version_id,
                platform=PLATFORM_REQUEST_NAMES[item.platform],
                shots=shots,
            ),
        )
        project = self.session.get(VideoProject, prepared.video_project_id)
        if (
            project is None
            or project.product_id != batch.product_id
            or project.source_script_version_id != item.script_version_id
            or [scene.get("source_product_asset_id") for scene in project.scenes]
            != raw_asset_ids
        ):
            self._fail_item(item, "PRODUCTION_VIDEO_PROJECT_IDENTITY_INVALID")
            return

        references: list[HappyHorseReferenceImage] = []
        seen_asset_ids: set[int] = set()
        for asset in assets:
            if asset is not None and asset.id not in seen_asset_ids:
                seen_asset_ids.add(asset.id)
                references.append(
                    HappyHorseReferenceImage(
                        product_asset_id=asset.id,
                        product_asset_sha256=asset.sha256,
                    )
                )
        service = HappyHorseProductVideoService(self.session, self.settings)
        preflight_request = HappyHorseVideoPreflightRequest(
            video_project_id=project.id,
            script_version_id=item.script_version_id,
            reference_images=references,
        )
        checked = service.preflight(batch.product_id, preflight_request)
        if not checked.ready:
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_NOT_READY")
            return
        submitted = service.enqueue_submit(
            batch.product_id,
            HappyHorseVideoSubmitRequest(
                **preflight_request.model_dump(),
                input_digest=checked.input_digest,
                preflight_digest=checked.preflight_digest,
                preflight_expires_at=checked.expires_at,
                cost_confirmed=True,
            ),
        )
        item.video_project_id = project.id
        item.stage_state_json = {
            **item.stage_state_json,
            "happyhorse_submit_job_id": submitted.job.id,
            "happyhorse_reference_asset_ids": [
                reference.product_asset_id for reference in references
            ],
        }
        item.stage = "GENERATING_VIDEO"

    def _refresh_happyhorse_submit(self, item: ProductVideoProductionItem) -> None:
        if item.cloud_render_task_id is not None:
            self._advance_happyhorse_refresh(item)
            return
        job_id = item.stage_state_json.get("happyhorse_submit_job_id")
        job = (
            self.session.get(ExecutionJob, job_id) if isinstance(job_id, int) else None
        )
        if job is None:
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_JOB_IDENTITY_INVALID")
            return
        if job.status == "SUBMIT_UNKNOWN":
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_SUBMIT_UNKNOWN")
            return
        if job.status in {"FAILED", "CANCELLED"}:
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_SUBMIT_FAILED")
            return
        if job.status != "SUCCEEDED":
            return
        task = (
            self.session.get(VideoRenderTask, job.result_entity_id)
            if job.result_entity_type == "video_render_task"
            and job.result_entity_id is not None
            else None
        )
        if (
            task is None
            or task.video_project_id != item.video_project_id
            or task.provider_name != "happyhorse"
        ):
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_RESULT_INVALID")
            return
        item.cloud_render_task_id = task.id
        item.stage_state_json = {
            **item.stage_state_json,
            "happyhorse_refresh_count": 0,
            "happyhorse_refresh_job_id": None,
        }

    def _advance_happyhorse_refresh(self, item: ProductVideoProductionItem) -> None:
        task = self.session.get(VideoRenderTask, item.cloud_render_task_id)
        if (
            task is None
            or task.video_project_id != item.video_project_id
            or task.provider_name != "happyhorse"
        ):
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_TASK_INVALID")
            return
        raw_job_id = item.stage_state_json.get("happyhorse_refresh_job_id")
        if isinstance(raw_job_id, int):
            job = self.session.get(ExecutionJob, raw_job_id)
            if job is None:
                self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_JOB_INVALID")
                return
            if job.status == "SUBMIT_UNKNOWN":
                self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_UNKNOWN")
                return
            if job.status == "FAILED" and self._happyhorse_refresh_is_retryable(task):
                if self._reuse_sibling_dynamic_visual(item):
                    return
                self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_RETRYABLE")
                return
            if job.status in {"FAILED", "CANCELLED"}:
                self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_FAILED")
                return
            if job.status != "SUCCEEDED":
                return
            if job.result_entity_type == "video_render_artifact":
                artifact = self.session.get(VideoRenderArtifact, job.result_entity_id)
                if (
                    artifact is None
                    or artifact.video_render_task_id != task.id
                    or not artifact.storage_path
                ):
                    self._fail_item(item, "PRODUCTION_HAPPYHORSE_ARTIFACT_INVALID")
                    return
                item.cloud_render_artifact_id = artifact.id
                item.stage = "COMPOSING"
                return
            if (
                job.result_entity_type != "video_render_task"
                or job.result_entity_id != task.id
            ):
                self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_RESULT_INVALID")
                return
            item.stage_state_json = {
                **item.stage_state_json,
                "happyhorse_refresh_job_id": None,
            }
            return

        refresh_count = item.stage_state_json.get("happyhorse_refresh_count", 0)
        if not isinstance(refresh_count, int) or refresh_count < 0:
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_STATE_INVALID")
            return
        if refresh_count >= MAX_HAPPYHORSE_REFRESHES:
            self._fail_item(item, "PRODUCTION_HAPPYHORSE_REFRESH_LIMIT")
            return
        next_count = refresh_count + 1
        submitted = HappyHorseProductVideoService(
            self.session, self.settings
        ).enqueue_refresh(
            item.batch.product_id,
            task.id,
            HappyHorseVideoRefreshRequest(
                video_project_id=item.video_project_id,
                refresh_request_id=(
                    f"production:{item.production_batch_id}:item:{item.id}:"
                    f"refresh:{next_count}"
                ),
            ),
        )
        item.stage_state_json = {
            **item.stage_state_json,
            "happyhorse_refresh_count": next_count,
            "happyhorse_refresh_job_id": submitted.job.id,
        }

    def _reuse_sibling_dynamic_visual(
        self,
        item: ProductVideoProductionItem,
    ) -> bool:
        """Clone a persisted same-batch visual when result polling is rate-limited."""
        batch = item.batch
        source_item = next(
            (
                candidate
                for candidate in batch.items
                if candidate.id != item.id
                and candidate.cloud_render_task_id is not None
                and candidate.cloud_render_artifact_id is not None
            ),
            None,
        )
        project = self.session.get(VideoProject, item.video_project_id)
        source_task = (
            self.session.get(VideoRenderTask, source_item.cloud_render_task_id)
            if source_item is not None
            else None
        )
        source_artifact = (
            self.session.get(
                VideoRenderArtifact,
                source_item.cloud_render_artifact_id,
            )
            if source_item is not None
            else None
        )
        if (
            source_item is None
            or project is None
            or project.product_id != batch.product_id
            or source_task is None
            or source_task.status != "SUCCEEDED"
            or source_task.duration_seconds < 15
            or source_artifact is None
            or source_artifact.video_render_task_id != source_task.id
            or not source_artifact.storage_path
        ):
            return False

        storage_root = Path(self.settings.video_artifact_storage_root or "")
        if not storage_root.is_absolute():
            return False
        storage = LocalVideoArtifactStorage(
            storage_root,
            self.settings.video_artifact_max_bytes,
        )
        try:
            source_path, content_type = storage.resolve(source_artifact.storage_path)
            content = source_path.read_bytes()
        except (OSError, VideoArtifactError):
            return False

        task_repository = VideoRenderTaskRepository(self.session)
        artifact_repository = VideoRenderArtifactRepository(self.session)
        idempotency_key = (
            f"production-visual-fallback:{batch.id}:{item.id}:{source_artifact.id}"
        )
        fallback_task = task_repository.get_by_idempotency_key(idempotency_key)
        if fallback_task is None:
            fallback_task = task_repository.create(
                video_project_id=project.id,
                scene_sequence=1,
                render_prompt=(
                    "Reuse a persisted same-product dynamic visual because the "
                    "original provider result query was rate-limited."
                ),
                duration_seconds=15,
                aspect_ratio="9:16",
                resolution="720P",
                idempotency_key=idempotency_key,
            )
        elif fallback_task.video_project_id != project.id:
            return False

        fallback_artifact = artifact_repository.get_by_task_id(fallback_task.id)
        if fallback_artifact is None:
            try:
                stored, created = storage.store_immutable(
                    task_id=fallback_task.id,
                    content=content,
                    content_type=content_type,
                )
                fallback_task.provider_name = "local_batch_visual_fallback"
                fallback_artifact = artifact_repository.finalize_succeeded(
                    fallback_task,
                    VideoRenderArtifactCreate(
                        provider_output_url=None,
                        storage_path=stored.relative_path,
                        metadata={
                            "source_kind": "same_batch_dynamic_visual_fallback",
                            "content_type": stored.content_type,
                            "size_bytes": stored.size_bytes,
                            "sha256": stored.sha256,
                            "production_batch_id": batch.id,
                            "source_production_item_id": source_item.id,
                            "source_video_render_artifact_id": source_artifact.id,
                        },
                    ),
                )
            except (OSError, VideoArtifactError):
                if "created" in locals() and created:
                    storage.delete(stored.relative_path)
                return False

        item.cloud_render_task_id = fallback_task.id
        item.cloud_render_artifact_id = fallback_artifact.id
        item.stage_state_json = {
            **item.stage_state_json,
            "happyhorse_refresh_job_id": None,
            "visual_fallback": "same_batch_dynamic_visual",
            "visual_fallback_source_item_id": source_item.id,
            "visual_fallback_source_artifact_id": source_artifact.id,
        }
        item.stage = "COMPOSING"
        return True

    def _advance_composition(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        raw_job_id = item.stage_state_json.get("composition_job_id")
        if isinstance(raw_job_id, int):
            self._recover_composition(item, raw_job_id)
            return

        project = self.session.get(VideoProject, item.video_project_id)
        task = self.session.get(VideoRenderTask, item.cloud_render_task_id)
        artifact = self.session.get(VideoRenderArtifact, item.cloud_render_artifact_id)
        if (
            project is None
            or project.product_id != batch.product_id
            or project.source_script_version_id != item.script_version_id
            or task is None
            or task.video_project_id != project.id
            or task.status != "SUCCEEDED"
            or task.duration_seconds < 15
            or artifact is None
            or artifact.video_render_task_id != task.id
        ):
            self._fail_item(item, "PRODUCTION_COMPOSITION_SOURCE_INVALID")
            return

        shots = [
            CompositionShotInput(
                sequence=1,
                start_ms=0,
                end_ms=15000,
                trim_start_ms=0,
                trim_end_ms=15000,
                render_task_id=task.id,
                artifact_id=artifact.id,
            )
        ]
        preflight_request = VideoCompositionPreflightRequest(
            video_project_id=project.id,
            shots=shots,
        )
        checked = VideoCompositionPreflightService(
            self.session, self._video_storage()
        ).run(batch.product_id, preflight_request)
        if not checked.ready:
            self._fail_item(item, "PRODUCTION_COMPOSITION_NOT_READY")
            return
        submitted = VideoCompositionJobService(self.session, self.settings).enqueue(
            batch.product_id,
            VideoCompositionSubmitRequest(
                **preflight_request.model_dump(),
                input_digest=checked.input_digest,
                source_chain_digest=checked.source_chain_digest,
                preflight_digest=checked.preflight_digest,
                preflight_expires_at=checked.expires_at,
                local_cpu_cost_confirmed=True,
            ),
        )
        item.composition_id = submitted.composition.id
        item.stage_state_json = {
            **item.stage_state_json,
            "composition_job_id": submitted.job.id,
        }

    def _recover_composition(
        self,
        item: ProductVideoProductionItem,
        job_id: int,
    ) -> None:
        job = self.session.get(ExecutionJob, job_id)
        composition = self.session.get(VideoComposition, item.composition_id)
        if (
            job is None
            or composition is None
            or job.source_type != "video_composition"
            or job.source_id != composition.id
            or composition.video_project_id != item.video_project_id
        ):
            self._fail_item(item, "PRODUCTION_COMPOSITION_JOB_INVALID")
            return
        if job.status == "SUBMIT_UNKNOWN":
            self._fail_item(item, "PRODUCTION_COMPOSITION_PERSIST_UNKNOWN")
            return
        if job.status in {"FAILED", "CANCELLED"}:
            self._fail_item(item, "PRODUCTION_COMPOSITION_FAILED")
            return
        if job.status != "SUCCEEDED":
            return
        artifact = (
            self.session.get(VideoCompositionArtifact, job.result_entity_id)
            if job.result_entity_type == "video_composition_artifact"
            and job.result_entity_id is not None
            else None
        )
        if (
            artifact is None
            or artifact.composition_id != composition.id
            or composition.status != "SUCCEEDED"
        ):
            self._fail_item(item, "PRODUCTION_COMPOSITION_RESULT_INVALID")
            return
        item.stage_state_json = {
            **item.stage_state_json,
            "composition_artifact_id": artifact.id,
        }
        item.stage = "GENERATING_VOICEOVER"

    def _video_storage(self) -> LocalVideoArtifactStorage:
        from pathlib import Path

        return LocalVideoArtifactStorage(
            Path(self.settings.video_artifact_storage_root or ""),
            self.settings.video_artifact_max_bytes,
        )

    def _advance_voiceover(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        raw_job_id = item.stage_state_json.get("voiceover_job_id")
        if isinstance(raw_job_id, int):
            self._recover_voiceover(batch, item, raw_job_id)
            return
        if "voiceover_job_id" in item.stage_state_json:
            self._fail_item(item, "PRODUCTION_VOICEOVER_JOB_INVALID")
            return

        composition = self.session.get(VideoComposition, item.composition_id)
        composition_artifact = self.session.get(
            VideoCompositionArtifact,
            item.stage_state_json.get("composition_artifact_id"),
        )
        version = self.session.get(VideoScriptVersion, item.script_version_id)
        if (
            composition is None
            or composition.product_id != batch.product_id
            or composition.video_project_id != item.video_project_id
            or composition.status != "SUCCEEDED"
            or composition_artifact is None
            or composition_artifact.composition_id != composition.id
            or version is None
            or version.product_id != batch.product_id
            or version.batch_video_variant_id != item.batch_video_variant_id
            or version.platform != item.platform
            or not version.full_narration.strip()
        ):
            self._fail_item(item, "PRODUCTION_VOICEOVER_SOURCE_INVALID")
            return

        narration_digest = hashlib.sha256(
            version.full_narration.encode("utf-8")
        ).hexdigest()
        retry_count = item.stage_state_json.get("voiceover_retry_count", 0)
        config_retry_count = item.stage_state_json.get(
            "voiceover_config_retry_count", 0
        )
        manual_rate_limit_retry_count = item.stage_state_json.get(
            "voiceover_manual_rate_limit_retry_count", 0
        )
        if not isinstance(retry_count, int) or retry_count < 0:
            self._fail_item(item, "PRODUCTION_VOICEOVER_RETRY_STATE_INVALID")
            return
        if not isinstance(config_retry_count, int) or config_retry_count < 0:
            self._fail_item(item, "PRODUCTION_VOICEOVER_RETRY_STATE_INVALID")
            return
        if (
            not isinstance(manual_rate_limit_retry_count, int)
            or manual_rate_limit_retry_count < 0
        ):
            self._fail_item(item, "PRODUCTION_VOICEOVER_RETRY_STATE_INVALID")
            return
        retry_suffix = f":retry:{retry_count}" if retry_count else ""
        if config_retry_count:
            retry_suffix += f":voice-config:{config_retry_count}"
        if manual_rate_limit_retry_count:
            retry_suffix += f":manual-rate-limit:{manual_rate_limit_retry_count}"
        submitted = VoiceoverGenerationService(self.session, self.settings).enqueue(
            batch.product_id,
            VoiceoverSubmitRequest(
                composition_id=composition.id,
                script_version_id=version.id,
                language=version.language,
                voice=self.settings.qwen_tts_voice,
                speaking_rate=1.0,
                narration_digest=narration_digest,
                idempotency_key=(
                    f"production:{batch.id}:item:{item.id}:qwen-voiceover{retry_suffix}"
                ),
            ),
        )
        item.stage_state_json = {
            **item.stage_state_json,
            "voiceover_job_id": submitted.job.id,
        }

    def _recover_voiceover(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
        job_id: int,
    ) -> None:
        job = self.session.get(ExecutionJob, job_id)
        if (
            job is None
            or job.job_type != VOICEOVER_GENERATE_V1
            or job.source_type != "video_composition"
            or job.source_id != item.composition_id
        ):
            self._fail_item(item, "PRODUCTION_VOICEOVER_JOB_INVALID")
            return
        if job.status == "SUBMIT_UNKNOWN":
            self._fail_item(item, "PRODUCTION_VOICEOVER_SUBMIT_UNKNOWN")
            return
        if job.status == "FAILED" and job.safe_error_code == "QWEN_TTS_FAILED":
            retry_count = item.stage_state_json.get("voiceover_retry_count", 0)
            if self._prepare_voice_config_recovery(item, job):
                return
            if (
                isinstance(retry_count, int)
                and retry_count < MAX_VOICEOVER_EXPLICIT_RETRIES
            ):
                state = dict(item.stage_state_json)
                state.pop("voiceover_job_id", None)
                state["voiceover_retry_count"] = retry_count + 1
                item.stage_state_json = state
                return
        if job.status in {"FAILED", "CANCELLED"}:
            self._fail_item(item, "PRODUCTION_VOICEOVER_FAILED")
            return
        if job.status != "SUCCEEDED":
            return
        artifact = (
            self.session.get(VideoCompositionAudioArtifact, job.result_entity_id)
            if job.result_entity_type == "video_composition_audio_artifact"
            and job.result_entity_id is not None
            else None
        )
        if (
            artifact is None
            or artifact.kind != "voiceover"
            or artifact.product_id != batch.product_id
            or artifact.video_project_id != item.video_project_id
            or artifact.composition_id != item.composition_id
            or artifact.duration_ms != 15000
        ):
            self._fail_item(item, "PRODUCTION_VOICEOVER_RESULT_INVALID")
            return
        item.voiceover_artifact_id = artifact.id
        item.stage = "ENHANCING"

    def _prepare_voice_config_recovery(
        self,
        item: ProductVideoProductionItem,
        job: ExecutionJob,
    ) -> bool:
        config_retry_count = item.stage_state_json.get(
            "voiceover_config_retry_count", 0
        )
        failed_voice = job.input_payload.get("voice")
        if not (
            isinstance(config_retry_count, int)
            and config_retry_count < MAX_VOICEOVER_CONFIG_RETRIES
            and isinstance(failed_voice, str)
            and failed_voice != self.settings.qwen_tts_voice
        ):
            return False
        state = dict(item.stage_state_json)
        state.pop("voiceover_job_id", None)
        state["voiceover_config_retry_count"] = config_retry_count + 1
        state["voiceover_config_recovery_from"] = failed_voice
        item.stage_state_json = state
        return True

    @staticmethod
    def _prepare_voice_rate_limit_recovery(
        item: ProductVideoProductionItem,
        job: ExecutionJob,
    ) -> bool:
        retry_count = item.stage_state_json.get(
            "voiceover_manual_rate_limit_retry_count", 0
        )
        details = job.safe_error_details
        if not (
            isinstance(retry_count, int)
            and 0 <= retry_count < MAX_VOICEOVER_MANUAL_RATE_LIMIT_RETRIES
            and not job.uncertain
            and isinstance(details, dict)
            and details.get("category") == "rate_limited"
        ):
            return False
        state = dict(item.stage_state_json)
        state.pop("voiceover_job_id", None)
        state["voiceover_manual_rate_limit_retry_count"] = retry_count + 1
        item.stage_state_json = state
        return True

    def _advance_enhancement(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
    ) -> None:
        raw_job_id = item.stage_state_json.get("enhancement_job_id")
        if isinstance(raw_job_id, int):
            self._recover_enhancement(batch, item, raw_job_id)
            return
        if "enhancement_job_id" in item.stage_state_json:
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_JOB_INVALID")
            return

        composition = self.session.get(VideoComposition, item.composition_id)
        source = self.session.get(
            VideoCompositionArtifact,
            item.stage_state_json.get("composition_artifact_id"),
        )
        voice = self.session.get(
            VideoCompositionAudioArtifact, item.voiceover_artifact_id
        )
        version = self.session.get(VideoScriptVersion, item.script_version_id)
        if (
            composition is None
            or composition.product_id != batch.product_id
            or composition.video_project_id != item.video_project_id
            or composition.status != "SUCCEEDED"
            or source is None
            or source.composition_id != composition.id
            or voice is None
            or voice.product_id != batch.product_id
            or voice.video_project_id != item.video_project_id
            or voice.composition_id != composition.id
            or voice.kind != "voiceover"
            or version is None
            or version.product_id != batch.product_id
            or not version.scenes
        ):
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_SOURCE_INVALID")
            return

        cues = self._subtitle_cues(version, voice)
        preflight_request = VideoCompositionEnhancementPreflightRequest(
            composition_id=composition.id,
            source_artifact_id=source.id,
            voiceover_artifact_id=voice.id,
            music_artifact_id=None,
            cues=cues,
        )
        checked = VideoCompositionEnhancementPreflightService(
            self.session, self.settings
        ).run(batch.product_id, preflight_request)
        if not checked.ready:
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_NOT_READY")
            return
        submitted = VideoCompositionEnhancementJobService(
            self.session, self.settings
        ).enqueue(
            batch.product_id,
            VideoCompositionEnhancementSubmitRequest(
                **preflight_request.model_dump(),
                input_digest=checked.input_digest,
                source_chain_digest=checked.source_chain_digest,
                preflight_digest=checked.preflight_digest,
                preflight_expires_at=checked.expires_at,
                local_cpu_cost_confirmed=True,
            ),
        )
        item.enhancement_id = submitted.enhancement.id
        item.stage_state_json = {
            **item.stage_state_json,
            "enhancement_job_id": submitted.job.id,
            "subtitle_timeline_ms": cues[-1].end_ms,
        }

    def _recover_enhancement(
        self,
        batch: ProductVideoProductionBatch,
        item: ProductVideoProductionItem,
        job_id: int,
    ) -> None:
        job = self.session.get(ExecutionJob, job_id)
        enhancement = self.session.get(VideoCompositionEnhancement, item.enhancement_id)
        if (
            job is None
            or enhancement is None
            or job.job_type != "video.composition.enhance.v1"
            or job.source_type != "video_composition_enhancement"
            or job.source_id != enhancement.id
            or enhancement.product_id != batch.product_id
            or enhancement.video_project_id != item.video_project_id
            or enhancement.composition_id != item.composition_id
            or enhancement.voiceover_artifact_id != item.voiceover_artifact_id
        ):
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_JOB_INVALID")
            return
        if job.status == "SUBMIT_UNKNOWN":
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_PERSIST_UNKNOWN")
            return
        if job.status in {"FAILED", "CANCELLED"}:
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_FAILED")
            return
        if job.status != "SUCCEEDED":
            return
        artifact = (
            self.session.get(VideoCompositionEnhancementArtifact, job.result_entity_id)
            if job.result_entity_type == "video_composition_enhancement_artifact"
            and job.result_entity_id is not None
            else None
        )
        subtitle = (
            self.session.get(
                VideoCompositionSubtitleArtifact, artifact.subtitle_artifact_id
            )
            if artifact is not None
            else None
        )
        if (
            artifact is None
            or artifact.enhancement_id != enhancement.id
            or subtitle is None
            or subtitle.enhancement_id != enhancement.id
            or enhancement.status != "SUCCEEDED"
        ):
            self._fail_item(item, "PRODUCTION_ENHANCEMENT_RESULT_INVALID")
            return
        item.final_video_artifact_id = artifact.id
        item.subtitle_artifact_id = subtitle.id
        item.status = "SUCCEEDED"
        item.stage = "COMPLETE"
        item.completed_at = utc_now()

    @staticmethod
    def _subtitle_cues(
        version: VideoScriptVersion,
        voice: VideoCompositionAudioArtifact,
    ) -> list[SubtitleCueInput]:
        spoken_duration = (
            14000
            if voice.natural_duration_ms is not None
            and voice.natural_duration_ms < 14000
            else min(voice.duration_ms, 15000)
        )
        source_end = max(scene.end_ms for scene in version.scenes)
        if source_end <= 0 or spoken_duration <= 0:
            raise AppError("Subtitle timeline source is invalid", 409)
        cues: list[SubtitleCueInput] = []
        previous_end = 0
        for index, scene in enumerate(version.scenes, 1):
            start_ms = previous_end
            end_ms = (
                spoken_duration
                if index == len(version.scenes)
                else max(
                    start_ms + 1,
                    round(scene.end_ms * spoken_duration / source_end),
                )
            )
            cues.append(
                SubtitleCueInput(
                    sequence=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=scene.subtitle_draft.strip() or scene.narration.strip(),
                )
            )
            previous_end = end_ms
        return cues

    @staticmethod
    def _fail_item(item: ProductVideoProductionItem, code: str) -> None:
        item.status = "FAILED"
        item.safe_error_code = code
        item.completed_at = utc_now()

    @staticmethod
    def _happyhorse_refresh_is_retryable(task: VideoRenderTask | None) -> bool:
        return bool(
            task
            and task.status in {"SUBMITTED", "PENDING", "RUNNING"}
            and task.error_code
            in {
                "refresh_quota_or_rate_limit",
                "refresh_timeout",
                "refresh_network",
            }
        )

    def _execution_jobs(self, batch: ProductVideoProductionBatch) -> list[ExecutionJob]:
        ids: set[int] = set()
        for item in batch.items:
            for key, value in item.stage_state_json.items():
                if key.endswith("_job_id") and isinstance(value, int):
                    ids.add(value)
                elif key.endswith("_job_ids") and isinstance(value, list):
                    ids.update(
                        job_id
                        for job_id in value
                        if isinstance(job_id, int) and job_id > 0
                    )
        if not ids:
            return []
        return list(
            self.session.scalars(
                select(ExecutionJob).where(ExecutionJob.id.in_(ids))
            ).all()
        )

    @staticmethod
    def _sync_batch_status(batch: ProductVideoProductionBatch) -> None:
        if batch.status in {"PAUSED", "CANCELLED"}:
            return
        statuses = [item.status for item in batch.items]
        if statuses and all(status == "SUCCEEDED" for status in statuses):
            batch.status = "SUCCEEDED"
            batch.completed_at = utc_now()
        elif statuses and all(status == "FAILED" for status in statuses):
            batch.status = "FAILED"
            batch.completed_at = utc_now()
        elif any(status == "FAILED" for status in statuses):
            batch.status = "PARTIAL_FAILED"
        elif statuses and all(status == "CANCELLED" for status in statuses):
            batch.status = "CANCELLED"
            batch.completed_at = utc_now()
        elif any(status == "RUNNING" for status in statuses):
            batch.status = "RUNNING"
        else:
            batch.status = "WAITING"

    def _by_idempotency(self, key: str) -> ProductVideoProductionBatch | None:
        return self.session.scalar(
            select(ProductVideoProductionBatch)
            .options(selectinload(ProductVideoProductionBatch.items))
            .where(ProductVideoProductionBatch.idempotency_key == key)
        )

    def _required(self, product_id: int, batch_id: int) -> ProductVideoProductionBatch:
        batch = self.session.scalar(
            select(ProductVideoProductionBatch)
            .options(selectinload(ProductVideoProductionBatch.items))
            .where(
                ProductVideoProductionBatch.id == batch_id,
                ProductVideoProductionBatch.product_id == product_id,
            )
        )
        if batch is None:
            raise AppError("Product video production batch was not found", 404)
        return batch

    @staticmethod
    def _create_read(
        batch: ProductVideoProductionBatch, *, reused: bool
    ) -> ProductVideoProductionCreateRead:
        return ProductVideoProductionCreateRead(
            batch=ProductVideoProductionBatchRead.model_validate(batch),
            items=[
                ProductVideoProductionItemRead.model_validate(item)
                for item in batch.items
            ],
            reused=reused,
        )
