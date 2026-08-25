from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AppError
from app.models import ProductVideoProductionBatch
from app.services.video_composition_enhancement_service import (
    VideoCompositionEnhancementArtifactAccessService,
)

PLATFORM_ORDER = ("tiktok", "youtube", "instagram")


@dataclass(frozen=True, slots=True)
class ProductVideoBatchDownload:
    filename: str
    content_length: int
    stream: BinaryIO


class ProductVideoBatchDownloadService:
    def __init__(self, session: Session, settings) -> None:
        self.session = session
        self.assets = VideoCompositionEnhancementArtifactAccessService(
            session, settings
        )

    def build(self, product_id: int, batch_id: int) -> ProductVideoBatchDownload:
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

        # The streaming response owns this file and closes it after the download.
        package = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # noqa: SIM115
        entries: list[dict[str, object]] = []
        try:
            with zipfile.ZipFile(
                package, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                items = sorted(
                    batch.items,
                    key=lambda item: PLATFORM_ORDER.index(item.platform),
                )
                for item in items:
                    if (
                        item.status != "SUCCEEDED"
                        or item.final_video_artifact_id is None
                        or item.subtitle_artifact_id is None
                    ):
                        continue
                    video, video_path = self.assets.resolve_video(
                        item.final_video_artifact_id
                    )
                    subtitle, subtitle_path = self.assets.resolve_subtitle(
                        item.subtitle_artifact_id
                    )
                    video_name = f"{item.platform}/{item.platform}.mp4"
                    subtitle_name = f"{item.platform}/{item.platform}.vtt"
                    archive.write(video_path, video_name)
                    archive.write(subtitle_path, subtitle_name)
                    entries.append(
                        {
                            "platform": item.platform,
                            "video_artifact_id": video.id,
                            "video_sha256": video.sha256,
                            "video_filename": video_name,
                            "subtitle_artifact_id": subtitle.id,
                            "subtitle_sha256": subtitle.sha256,
                            "subtitle_filename": subtitle_name,
                        }
                    )
                if not entries:
                    raise AppError("No completed product videos are available", 409)
                included = [str(entry["platform"]) for entry in entries]
                manifest = {
                    "product_id": product_id,
                    "production_batch_id": batch.id,
                    "batch_status": batch.status,
                    "expected_platforms": list(PLATFORM_ORDER),
                    "included_platforms": included,
                    "missing_platforms": [
                        platform
                        for platform in PLATFORM_ORDER
                        if platform not in included
                    ],
                    "complete": len(included) == len(PLATFORM_ORDER),
                    "entries": entries,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        manifest, ensure_ascii=False, indent=2, sort_keys=True
                    ).encode("utf-8"),
                )
            package.seek(0, 2)
            content_length = package.tell()
            package.seek(0)
            return ProductVideoBatchDownload(
                filename=f"product-{product_id}-batch-{batch.id}-videos.zip",
                content_length=content_length,
                stream=package,
            )
        except Exception:
            package.close()
            raise
