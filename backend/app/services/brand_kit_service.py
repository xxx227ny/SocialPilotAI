from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models import BrandKit, BrandKitVersion
from app.models.product import utc_now
from app.repositories.brand_kit import BrandKitRepository
from app.repositories.product import ProductRepository
from app.schemas.brand_kit import (
    BrandKitCreate,
    BrandKitVersionCreateRead,
    BrandKitVersionInput,
    BrandKitVersionRead,
    ProductBrandKitBinding,
)
from app.schemas.product import ProductRead

_LIST_FIELDS = (
    "preferred_terms",
    "forbidden_terms",
    "target_regions",
    "audience_guidelines",
    "visual_guidelines",
    "required_disclosures",
    "claims_constraints",
)
MAX_VERSION_NUMBER_RETRIES = 2


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _normalized_list(values: Iterable[str]) -> list[str]:
    unique: dict[str, str] = {}
    for value in values:
        normalized = _text(value)
        if normalized:
            unique.setdefault(normalized.casefold(), normalized)
    return [unique[key] for key in sorted(unique)]


def _normalized_content(data: BrandKitVersionInput) -> dict[str, object]:
    content: dict[str, object] = {
        "brand_name": _text(data.brand_name),
        "positioning": _text(data.positioning),
        "default_language": _text(data.default_language),
        "brand_tone": _text(data.brand_tone),
    }
    for field in _LIST_FIELDS:
        content[field] = _normalized_list(getattr(data, field))
    if any(not content[field] for field in (
        "brand_name",
        "positioning",
        "default_language",
        "brand_tone",
    )):
        raise AppError("BrandKit version text fields cannot be empty", 422)
    preferred = {item.casefold() for item in content["preferred_terms"]}  # type: ignore[union-attr]
    forbidden = {item.casefold() for item in content["forbidden_terms"]}  # type: ignore[union-attr]
    if preferred & forbidden:
        raise AppError("Preferred and forbidden terms cannot overlap", 422)
    return content


def _digest(content: dict[str, object]) -> str:
    canonical = dict(content)
    for field in _LIST_FIELDS:
        canonical[field] = [
            item.casefold() for item in content[field]  # type: ignore[union-attr]
        ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class BrandKitService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = BrandKitRepository(session)
        self.products = ProductRepository(session)

    def create(self, data: BrandKitCreate) -> BrandKit:
        name = _text(data.name)
        if not name:
            raise AppError("BrandKit name cannot be empty", 422)
        content = _normalized_content(data.version)
        kit = BrandKit(name=name)
        try:
            self.repository.add_kit(kit)
            self.repository.add_version(
                BrandKitVersion(
                    brand_kit_id=kit.id,
                    version_number=1,
                    digest=_digest(content),
                    **content,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.get(kit.id)

    def get(self, brand_kit_id: int) -> BrandKit:
        kit = self.repository.get(brand_kit_id)
        if kit is None:
            raise AppError("BrandKit not found", 404)
        return kit

    def list(self) -> list[BrandKit]:
        return self.repository.list()

    def get_version(self, brand_kit_id: int, version_id: int) -> BrandKitVersion:
        self.get(brand_kit_id)
        version = self.repository.get_version(version_id)
        if version is None:
            raise AppError("BrandKit version not found", 404)
        if version.brand_kit_id != brand_kit_id:
            raise AppError(
                "BrandKit version does not belong to the exact BrandKit", 409
            )
        return version

    def list_versions(self, brand_kit_id: int) -> list[BrandKitVersion]:
        self.get(brand_kit_id)
        return self.repository.list_versions(brand_kit_id)

    def create_version(
        self, brand_kit_id: int, data: BrandKitVersionInput
    ) -> BrandKitVersionCreateRead:
        self.get(brand_kit_id)
        content = _normalized_content(data)
        digest = _digest(content)
        for attempt in range(MAX_VERSION_NUMBER_RETRIES + 1):
            existing = self.repository.get_version_by_digest(brand_kit_id, digest)
            if existing is not None:
                return self._version_result(existing, reused=True)
            version_number = self.repository.next_version_number(brand_kit_id)
            # Release the read transaction before competing for SQLite's write lock.
            # Database constraints, rather than process-local locks, select the winner.
            self.session.rollback()
            version = BrandKitVersion(
                brand_kit_id=brand_kit_id,
                version_number=version_number,
                digest=digest,
                **content,
            )
            try:
                self.repository.add_version(version)
                self.repository.touch(brand_kit_id, utc_now())
                self.session.commit()
            except IntegrityError as error:
                self.session.rollback()
                existing = self.repository.get_version_by_digest(brand_kit_id, digest)
                if existing is not None:
                    return self._version_result(existing, reused=True)
                competing = self.repository.get_version_by_number(
                    brand_kit_id, version_number
                )
                if competing is None or competing.digest == digest:
                    self.session.rollback()
                    raise
                self.session.rollback()
                if attempt == MAX_VERSION_NUMBER_RETRIES:
                    raise AppError(
                        "BrandKit version number remained contested; retry explicitly",
                        409,
                    ) from error
                continue
            self.session.refresh(version)
            return self._version_result(version, reused=False)
        raise RuntimeError("Unreachable BrandKit version retry state")

    def bind_product(
        self, product_id: int, data: ProductBrandKitBinding
    ) -> ProductRead:
        product = self.products.get(product_id)
        if product is None:
            raise AppError("Product not found", 404)
        version = self.get_version(data.brand_kit_id, data.brand_kit_version_id)
        product.brand_kit_version_id = version.id
        self.session.commit()
        return ProductRead.model_validate(self.products.get(product_id))

    def unbind_product(self, product_id: int) -> ProductRead:
        product = self.products.get(product_id)
        if product is None:
            raise AppError("Product not found", 404)
        product.brand_kit_version_id = None
        self.session.commit()
        return ProductRead.model_validate(self.products.get(product_id))

    @staticmethod
    def _version_result(
        version: BrandKitVersion, *, reused: bool
    ) -> BrandKitVersionCreateRead:
        return BrandKitVersionCreateRead(
            version=BrandKitVersionRead.model_validate(version), reused=reused
        )
