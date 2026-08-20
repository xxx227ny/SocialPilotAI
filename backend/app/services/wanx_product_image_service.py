from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models import ExecutionJob, Product, VideoScriptVersion
from app.schemas.execution import ExecutionJobRead
from app.schemas.product_marketing_video import (
    JobSubmitRead,
    WanxProductImageSubmitRequest,
)
from app.services.product import ProductService

WANX_PRODUCT_IMAGE_GENERATE_V1 = "wanx.product_image.generate.v1"


class WanxProductImageService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session, self.settings = session, settings

    def enqueue(
        self, product_id: int, data: WanxProductImageSubmitRequest
    ) -> JobSubmitRead:
        if not self.settings.enable_real_product_video:
            raise AppError("Real product video execution is disabled", 503)
        if not data.cost_confirmed:
            raise AppError("Wanx image cost confirmation is required", 409)
        product, version, scene = self._source(
            product_id, data.script_version_id, data.scene_sequence
        )
        prompt = self._prompt(product, version, scene)
        material = {
            "contract": "wanx-product-image-v1",
            "product_id": product.id,
            "script_version_id": version.id,
            "script_digest": version.content_digest,
            "scene_id": scene.id,
            "scene_sequence": scene.sequence,
            "prompt": prompt,
            "model": self.settings.wanx_image_model,
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        key = f"{WANX_PRODUCT_IMAGE_GENERATE_V1}:{data.idempotency_key}"
        existing = (
            self.session.query(ExecutionJob)
            .filter_by(idempotency_key=key)
            .one_or_none()
        )
        if existing is not None:
            if existing.input_digest != digest:
                raise AppError("Wanx image idempotency conflict", 409)
            return JobSubmitRead(
                job=ExecutionJobRead.model_validate(existing), reused=True
            )
        job = ExecutionJob(
            job_type=WANX_PRODUCT_IMAGE_GENERATE_V1,
            source_type="video_storyboard_scene_version",
            source_id=scene.id,
            input_digest=digest,
            idempotency_key=key,
            input_payload={**material, "input_digest": digest},
            concurrency_key=f"wanx-product-image-scene-{scene.id}",
            estimated_cost=self.settings.wanx_image_estimated_cost,
            currency="CNY",
            cost_confirmed=True,
            max_attempts=1,
            status="QUEUED",
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return JobSubmitRead(job=ExecutionJobRead.model_validate(job), reused=False)

    def persist(self, product_id: int, content: bytes):
        return ProductService(self.session).upload_asset(
            product_id,
            file_name="wanx-product.png",
            content_type="image/png",
            content=content,
            storage_root=Path(self.settings.product_asset_storage_root or ""),
            max_bytes=self.settings.product_asset_max_bytes,
            ffmpeg_path=self.settings.video_composition_ffmpeg_path,
            ffprobe_path=self.settings.video_composition_ffprobe_path,
            process_timeout=self.settings.video_composition_process_timeout,
        )[0]

    def _source(self, product_id: int, version_id: int, sequence: int):
        product = self.session.get(Product, product_id)
        version = self.session.get(VideoScriptVersion, version_id)
        scene = (
            next(
                (item for item in version.scenes if item.sequence == sequence),
                None,
            )
            if version is not None
            else None
        )
        if (
            product is None
            or version is None
            or scene is None
            or version.product_id != product.id
        ):
            raise AppError("Wanx image source was not found", 404)
        return product, version, scene

    @staticmethod
    def _prompt(product, version, scene) -> str:
        selling_points = ", ".join(product.selling_points)
        return (
            "Create a photorealistic premium ecommerce advertising image in a "
            "vertical 9:16 composition. Keep one consistent fictional product "
            f"identity. Product: {product.name}. Category: {product.category}. "
            f"Selling points: {selling_points}. Campaign concept: {version.concept}. "
            f"Scene: {scene.visual_description}. Action: {scene.action_description}. "
            "Natural commercial lighting, complete product visible, realistic "
            "materials. Keep every product surface completely blank: no letters, "
            "numbers, labels, interface text, brand marks, logos, watermarks, or "
            "decorative writing anywhere. No split screen or collage."
        )
