from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BatchVideoVariant,
    BrandKit,
    BrandKitVersion,
    Product,
    VideoScriptVersion,
)


class BrandKitRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_kit(self, brand_kit: BrandKit) -> None:
        self.session.add(brand_kit)
        self.session.flush()

    def add_version(self, version: BrandKitVersion) -> None:
        self.session.add(version)
        self.session.flush()

    def get(self, brand_kit_id: int) -> BrandKit | None:
        return self.session.scalar(
            select(BrandKit)
            .options(selectinload(BrandKit.versions))
            .where(BrandKit.id == brand_kit_id)
        )

    def list(self) -> list[BrandKit]:
        return list(
            self.session.scalars(
                select(BrandKit)
                .options(selectinload(BrandKit.versions))
                .order_by(BrandKit.id)
            ).all()
        )

    def get_version(self, version_id: int) -> BrandKitVersion | None:
        return self.session.get(BrandKitVersion, version_id)

    def get_version_by_digest(
        self, brand_kit_id: int, digest: str
    ) -> BrandKitVersion | None:
        return self.session.scalar(
            select(BrandKitVersion).where(
                BrandKitVersion.brand_kit_id == brand_kit_id,
                BrandKitVersion.digest == digest,
            )
        )

    def get_version_by_number(
        self, brand_kit_id: int, version_number: int
    ) -> BrandKitVersion | None:
        return self.session.scalar(
            select(BrandKitVersion).where(
                BrandKitVersion.brand_kit_id == brand_kit_id,
                BrandKitVersion.version_number == version_number,
            )
        )

    def list_versions(self, brand_kit_id: int) -> list[BrandKitVersion]:
        return list(
            self.session.scalars(
                select(BrandKitVersion)
                .where(BrandKitVersion.brand_kit_id == brand_kit_id)
                .order_by(BrandKitVersion.version_number)
            ).all()
        )

    def next_version_number(self, brand_kit_id: int) -> int:
        latest = self.session.scalar(
            select(func.max(BrandKitVersion.version_number)).where(
                BrandKitVersion.brand_kit_id == brand_kit_id
            )
        )
        return int(latest or 0) + 1

    def touch(self, brand_kit_id: int, updated_at: object) -> None:
        self.session.execute(
            update(BrandKit)
            .where(BrandKit.id == brand_kit_id)
            .values(updated_at=updated_at)
        )

    def version_reference_counts(self, version_id: int) -> dict[str, int]:
        return {
            "products": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.brand_kit_version_id == version_id)
                )
                or 0
            ),
            "batch_variants": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(BatchVideoVariant)
                    .where(BatchVideoVariant.brand_kit_version_id == version_id)
                )
                or 0
            ),
            "script_versions": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(VideoScriptVersion)
                    .where(VideoScriptVersion.brand_kit_version_id == version_id)
                )
                or 0
            ),
        }

    def delete_version_record(self, version_id: int) -> None:
        # BrandKitVersion remains immutable through the ORM. This explicit Core
        # delete is only called after the service proves the version is unused.
        self.session.execute(
            delete(BrandKitVersion)
            .where(BrandKitVersion.id == version_id)
            .execution_options(synchronize_session=False)
        )

    def delete_versions_for_kit(self, brand_kit_id: int) -> None:
        self.session.execute(
            delete(BrandKitVersion)
            .where(BrandKitVersion.brand_kit_id == brand_kit_id)
            .execution_options(synchronize_session=False)
        )

    def delete_kit_record(self, brand_kit_id: int) -> None:
        self.session.execute(
            delete(BrandKit)
            .where(BrandKit.id == brand_kit_id)
            .execution_options(synchronize_session=False)
        )
