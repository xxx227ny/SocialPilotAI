from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import CopyMatrix, Product
from app.repositories.product import ProductRepository
from app.schemas.social import AutoPublishDraftRead
from app.services.social_publish_source import SocialPublishSourceService
from app.services.video_artifact_storage import VideoArtifactStorage


class AutoSocialPublishService:
    def __init__(
        self,
        session: Session,
        settings,
        storage: VideoArtifactStorage,
    ) -> None:
        self.session = session
        self.products = ProductRepository(session)
        self.sources = SocialPublishSourceService(session, settings, storage)

    def draft(self, product_id: int, platform: str) -> AutoPublishDraftRead:
        product = self.products.get(product_id)
        if product is None:
            raise AppError("Product not found", 404)
        source = self.sources.latest_final(product_id=product_id, platform=platform)
        item = source.production_item
        script = source.script_version
        final = source.final_artifact
        if item is None or script is None or final is None:
            raise AppError("Completed final video identity is unavailable", 409)
        title, description, tags, copy_source = self._copy(
            product, platform, script
        )
        return AutoPublishDraftRead(
            platform=platform,
            artifact_id=source.artifact.id,
            final_video_artifact_id=final.id,
            production_item_id=item.id,
            production_batch_id=item.production_batch_id,
            video_project_id=source.project.id,
            script_version_id=script.id,
            title=title,
            description=description,
            tags=tags,
            content_type="video/mp4",
            size_bytes=source.size_bytes,
            sha256=source.sha256,
            duration_seconds=final.duration_ms / 1000,
            copy_source=copy_source,
        )

    def _copy(self, product: Product, platform: str, script):
        if platform == "instagram":
            matrix = (
                self.session.get(CopyMatrix, script.copy_matrix_id)
                if script.copy_matrix_id is not None
                else None
            )
            platform_copy = next(
                (
                    value
                    for value in (matrix.copies if matrix is not None else [])
                    if str(value.get("platform", "")).casefold() == "instagram"
                ),
                None,
            )
            if platform_copy is not None:
                caption = str(platform_copy.get("caption", "")).strip()
                cta = str(platform_copy.get("cta", "")).strip()
                description = _join_unique(caption, cta)[:1900]
                tags = _fit_instagram_caption(
                    description,
                    _instagram_tags(platform_copy.get("hashtags", [])),
                )
                if description and tags:
                    return (
                        _clean_title(script.title),
                        description,
                        tags,
                        "copy_matrix",
                    )
            return (
                _clean_title(script.title),
                _join_unique(script.hook, script.cta)[:1900],
                _fit_instagram_caption(
                    _join_unique(script.hook, script.cta)[:1900],
                    _instagram_tags(
                        [product.name, product.category or "", *product.selling_points]
                    ),
                ),
                "script",
            )
        if platform == "youtube":
            description = _join_unique(
                script.hook, script.full_narration, script.cta
            )[:5000]
            return (
                _clean_title(script.title),
                description,
                _product_tags(product, include_shorts=True),
                "script",
            )
        raise AppError("Social publishing platform is not supported", 409)


def _clean_title(value: str) -> str:
    cleaned = " ".join(value.split()).strip()
    return (cleaned or "SocialPilot 成片")[:100]


def _join_unique(*values: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned.casefold() not in seen:
            parts.append(cleaned)
            seen.add(cleaned.casefold())
    return "\n\n".join(parts)


def _instagram_tags(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    tags: list[str] = []
    for value in values:
        tag = "".join(
            character
            for character in str(value).strip().lstrip("#")
            if character.isalnum() or character == "_"
        )[:100]
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
        if len(tags) == 20:
            break
    return tags


def _product_tags(product: Product, *, include_shorts: bool) -> list[str]:
    source: list[str] = [product.name]
    if product.category:
        source.append(product.category)
    source.extend(product.selling_points)
    if include_shorts:
        source.append("Shorts")
    tags: list[str] = []
    for value in source:
        tag = " ".join(str(value).split()).strip().lstrip("#")[:100]
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
        if len(tags) == 20:
            break
    while len(",".join(tags)) > 500:
        tags.pop()
    return tags


def _fit_instagram_caption(description: str, tags: list[str]) -> list[str]:
    fitted = list(tags)
    while fitted:
        hashtags = " ".join(f"#{tag}" for tag in fitted)
        caption = "\n\n".join(part for part in (description, hashtags) if part)
        if len(caption) <= 2200:
            break
        fitted.pop()
    return fitted
