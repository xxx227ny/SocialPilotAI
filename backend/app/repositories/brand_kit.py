from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import BrandKit, BrandKitVersion


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
