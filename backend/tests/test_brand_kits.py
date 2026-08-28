from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.services.database_migration_service as migration_service
from app.api.dependencies import (
    get_text_generation_provider,
    get_visual_generation_provider,
    get_youtube_provider,
)
from app.core.exceptions import AppError
from app.main import app
from app.models import BrandKit, BrandKitVersion
from app.repositories.brand_kit import BrandKitRepository
from app.schemas.brand_kit import BrandKitCreate, BrandKitVersionInput
from app.services.brand_kit_service import (
    MAX_VERSION_NUMBER_RETRIES,
    BrandKitService,
)
from app.services.database_migration_service import HEAD_REVISION, sha256_file


def version_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "brand_name": " North Star ",
        "positioning": " Practical growth for small teams ",
        "default_language": " English ",
        "brand_tone": " Clear and optimistic ",
        "preferred_terms": ["Trusted", " simple ", "TRUSTED"],
        "forbidden_terms": ["guaranteed"],
        "target_regions": ["US", " Canada ", "US"],
        "audience_guidelines": ["Respect small-business constraints"],
        "visual_guidelines": ["Use accessible contrast"],
        "required_disclosures": ["Disclose synthetic media"],
        "claims_constraints": ["No unsupported performance claims"],
    }
    payload.update(overrides)
    return payload


def create_kit(client: TestClient, *, name: str = "North Star") -> dict[str, object]:
    response = client.post(
        "/api/v1/brand-kits", json={"name": name, "version": version_payload()}
    )
    assert response.status_code == 201
    return response.json()


def create_product(client: TestClient, product_payload: dict[str, object]) -> int:
    response = client.post("/api/v1/products", json=product_payload)
    assert response.status_code == 201
    return int(response.json()["id"])


def test_create_brand_kit_atomically_creates_normalized_version_one(
    client: TestClient,
) -> None:
    created = create_kit(client)

    assert created["name"] == "North Star"
    assert len(created["versions"]) == 1
    version = created["versions"][0]
    assert version["version_number"] == 1
    assert len(version["digest"]) == 64
    assert version["preferred_terms"] == ["simple", "Trusted"]
    assert version["target_regions"] == ["Canada", "US"]


def test_identical_normalized_content_reuses_version_and_change_creates_two(
    client: TestClient,
) -> None:
    kit = create_kit(client)
    kit_id = kit["id"]
    same = version_payload(
        preferred_terms=[" SIMPLE ", "trusted"], target_regions=["Canada", "US"]
    )

    reused = client.post(f"/api/v1/brand-kits/{kit_id}/versions", json=same)
    changed = client.post(
        f"/api/v1/brand-kits/{kit_id}/versions",
        json=version_payload(positioning="A genuinely new positioning"),
    )

    assert reused.status_code == 200
    assert reused.json()["reused"] is True
    assert reused.json()["version"]["id"] == kit["versions"][0]["id"]
    assert changed.status_code == 200
    assert changed.json()["reused"] is False
    assert changed.json()["version"]["version_number"] == 2


def test_term_conflicts_are_rejected_without_partial_kit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/brand-kits",
        json={
            "name": "Unsafe",
            "version": version_payload(
                preferred_terms=["Guaranteed"], forbidden_terms=[" guaranteed "]
            ),
        },
    )

    assert response.status_code == 422
    assert client.get("/api/v1/brand-kits").json() == []


def test_version_is_immutable_and_undeletable(db_session: Session) -> None:
    service = BrandKitService(db_session)
    kit = service.create(BrandKitCreate(name="Immutable", version=version_payload()))
    version = kit.versions[0]
    version.positioning = "Mutation"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    version = db_session.get(BrandKitVersion, version.id)
    assert version is not None
    db_session.delete(version)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_product_explicit_binding_unbinding_and_cross_kit_rejection(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_id = create_product(client, product_payload)
    first = create_kit(client, name="First")
    second = create_kit(client, name="Second")
    version_id = first["versions"][0]["id"]

    missing = client.put(
        f"/api/v1/products/{product_id}/brand-kit-version",
        json={"brand_kit_id": first["id"], "brand_kit_version_id": 99999},
    )
    crossed = client.put(
        f"/api/v1/products/{product_id}/brand-kit-version",
        json={
            "brand_kit_id": second["id"],
            "brand_kit_version_id": version_id,
        },
    )
    bound = client.put(
        f"/api/v1/products/{product_id}/brand-kit-version",
        json={"brand_kit_id": first["id"], "brand_kit_version_id": version_id},
    )
    unbound = client.delete(f"/api/v1/products/{product_id}/brand-kit-version")

    assert missing.status_code == 404
    assert crossed.status_code == 409
    assert bound.status_code == 200
    assert bound.json()["brand_kit_version_id"] == version_id
    assert unbound.status_code == 200
    assert unbound.json()["brand_kit_version_id"] is None


def test_unused_brand_kit_version_and_entire_kit_can_be_deleted(
    client: TestClient,
) -> None:
    kit = create_kit(client, name="Disposable")
    kit_id = int(kit["id"])
    first_version_id = int(kit["versions"][0]["id"])
    second = client.post(
        f"/api/v1/brand-kits/{kit_id}/versions",
        json=version_payload(positioning="Disposable second version"),
    )
    assert second.status_code == 200
    second_version_id = int(second.json()["version"]["id"])

    deleted_version = client.delete(
        f"/api/v1/brand-kits/{kit_id}/versions/{second_version_id}"
    )
    assert deleted_version.status_code == 204
    assert (
        client.get(
            f"/api/v1/brand-kits/{kit_id}/versions/{second_version_id}"
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/brand-kits/{kit_id}").json()["versions"][0]["id"]
        == first_version_id
    )

    deleted_kit = client.delete(f"/api/v1/brand-kits/{kit_id}")
    assert deleted_kit.status_code == 204
    assert client.get(f"/api/v1/brand-kits/{kit_id}").status_code == 404


def test_last_or_referenced_brand_kit_version_cannot_be_deleted(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    kit = create_kit(client, name="Protected")
    kit_id = int(kit["id"])
    first_version_id = int(kit["versions"][0]["id"])

    last_version = client.delete(
        f"/api/v1/brand-kits/{kit_id}/versions/{first_version_id}"
    )
    assert last_version.status_code == 409
    assert "至少一个" in last_version.json()["error"]["message"]

    second = client.post(
        f"/api/v1/brand-kits/{kit_id}/versions",
        json=version_payload(positioning="Protected second version"),
    ).json()["version"]
    product_id = create_product(client, product_payload)
    bound = client.put(
        f"/api/v1/products/{product_id}/brand-kit-version",
        json={
            "brand_kit_id": kit_id,
            "brand_kit_version_id": int(second["id"]),
        },
    )
    assert bound.status_code == 200

    referenced_version = client.delete(
        f"/api/v1/brand-kits/{kit_id}/versions/{int(second['id'])}"
    )
    referenced_kit = client.delete(f"/api/v1/brand-kits/{kit_id}")
    assert referenced_version.status_code == 409
    assert "已被" in referenced_version.json()["error"]["message"]
    assert referenced_kit.status_code == 409
    assert "已被" in referenced_kit.json()["error"]["message"]


def _concurrent_factory(tmp_path: Path) -> tuple[object, sessionmaker, int]:
    database = tmp_path / "brand-kit-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database.as_posix()}", connect_args={"check_same_thread": False}
    )
    from app.db.base import Base

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        kit_id = (
            BrandKitService(session)
            .create(BrandKitCreate(name="Concurrent", version=version_payload()))
            .id
        )
    return engine, factory, kit_id


def _synchronize_first_version_number_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)
    thread_state = threading.local()
    original = BrandKitRepository.next_version_number

    def synchronized(repository: BrandKitRepository, brand_kit_id: int) -> int:
        number = original(repository, brand_kit_id)
        if not getattr(thread_state, "synchronized", False):
            thread_state.synchronized = True
            barrier.wait(timeout=5)
        return number

    monkeypatch.setattr(BrandKitRepository, "next_version_number", synchronized)


def test_same_digest_concurrency_creates_one_candidate_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, kit_id = _concurrent_factory(tmp_path)
    _synchronize_first_version_number_read(monkeypatch)

    changed = BrandKitVersionInput.model_validate(
        version_payload(positioning="Concurrent version two")
    )

    def create() -> tuple[int, str]:
        with factory() as session:
            result = BrandKitService(session).create_version(kit_id, changed)
            return result.version.id, result.version.digest

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create(), range(2)))

    with factory() as session:
        candidates = list(
            session.scalars(
                select(BrandKitVersion).where(
                    BrandKitVersion.brand_kit_id == kit_id,
                    BrandKitVersion.version_number > 1,
                )
            ).all()
        )
    engine.dispose()

    assert results[0] == results[1]
    assert len(candidates) == 1


def test_different_digest_concurrency_gets_contiguous_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, factory, kit_id = _concurrent_factory(tmp_path)
    _synchronize_first_version_number_read(monkeypatch)
    inputs = [
        BrandKitVersionInput.model_validate(
            version_payload(positioning=f"Concurrent distinct version {suffix}")
        )
        for suffix in ("A", "B")
    ]

    def create(data: BrandKitVersionInput) -> tuple[int, int, str]:
        with factory() as session:
            result = BrandKitService(session).create_version(kit_id, data)
            return (
                result.version.id,
                result.version.version_number,
                result.version.digest,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, inputs))

    with factory() as session:
        versions = list(
            session.scalars(
                select(BrandKitVersion)
                .where(BrandKitVersion.brand_kit_id == kit_id)
                .order_by(BrandKitVersion.version_number)
            ).all()
        )
    engine.dispose()

    assert len({result[0] for result in results}) == 2
    assert len({result[2] for result in results}) == 2
    assert [version.version_number for version in versions] == [1, 2, 3]


def test_version_number_retry_has_explicit_limit(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_id = (
        BrandKitService(db_session)
        .create(BrandKitCreate(name="Retry Bound", version=version_payload()))
        .id
    )
    service = BrandKitService(db_session)
    attempts = 0

    def contested(_: BrandKitVersion) -> None:
        nonlocal attempts
        attempts += 1
        raise IntegrityError("forced", {}, Exception("version collision"))

    monkeypatch.setattr(service.repository, "add_version", contested)
    monkeypatch.setattr(service.repository, "get_version_by_digest", lambda *_: None)
    monkeypatch.setattr(service.repository, "next_version_number", lambda *_: 2)
    monkeypatch.setattr(
        service.repository,
        "get_version_by_number",
        lambda *_: BrandKitVersion(
            brand_kit_id=kit_id, version_number=2, digest="different"
        ),
    )

    with pytest.raises(AppError, match="remained contested"):
        service.create_version(
            kit_id,
            BrandKitVersionInput.model_validate(
                version_payload(positioning="Bounded retries")
            ),
        )

    assert attempts == MAX_VERSION_NUMBER_RETRIES + 1


def test_non_version_integrity_error_is_not_retried(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    kit_id = (
        BrandKitService(db_session)
        .create(BrandKitCreate(name="Other Integrity", version=version_payload()))
        .id
    )
    service = BrandKitService(db_session)
    attempts = 0

    def invalid(_: BrandKitVersion) -> None:
        nonlocal attempts
        attempts += 1
        raise IntegrityError("forced", {}, Exception("other constraint"))

    monkeypatch.setattr(service.repository, "add_version", invalid)
    monkeypatch.setattr(service.repository, "get_version_by_digest", lambda *_: None)
    monkeypatch.setattr(service.repository, "next_version_number", lambda *_: 2)
    monkeypatch.setattr(service.repository, "get_version_by_number", lambda *_: None)

    with pytest.raises(IntegrityError):
        service.create_version(
            kit_id,
            BrandKitVersionInput.model_validate(
                version_payload(positioning="Other integrity")
            ),
        )

    assert attempts == 1


def test_0002_upgrade_preserves_existing_product_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "x2.db"
    backups = tmp_path / "backups"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", migration_service.X2_REVISION
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO products
            (id, name, category, description, selling_points, target_markets,
             created_at, updated_at)
            VALUES (41, 'Existing', 'Test', 'Preserved', '[\"Stable\"]',
                    '[\"US\"]', '2026-08-09', '2026-08-09')
            """
        )
        connection.commit()
    finally:
        connection.close()

    result = migration_service.upgrade_sqlite_database(database, backups)
    first_hash = sha256_file(database)
    second = migration_service.upgrade_sqlite_database(database, backups)

    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT id, name, brand_kit_version_id FROM products WHERE id = 41"
        ).fetchone()
    finally:
        connection.close()

    assert result.previous_revision == migration_service.X2_REVISION
    assert result.current_revision == HEAD_REVISION
    assert row == (41, "Existing", None)
    assert second.current_revision == HEAD_REVISION
    assert sha256_file(database) == first_hash


def test_unversioned_0002_is_recognized_and_safely_upgraded(tmp_path: Path) -> None:
    database = tmp_path / "unversioned-x2.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", migration_service.X2_REVISION
    )
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE alembic_version")
        connection.commit()
    finally:
        connection.close()

    status = migration_service.get_database_migration_status(database)
    result = migration_service.upgrade_sqlite_database(
        database, tmp_path / "unversioned-backups"
    )

    assert status.state == "x2_runtime"
    assert status.upgrade_required is True
    assert result.schema_state == "x2_runtime"
    assert result.current_revision == HEAD_REVISION


def test_0003_enforces_positive_version_number(tmp_path: Path) -> None:
    database = tmp_path / "positive-version.db"
    migration_service._run_alembic(database, "upgrade", HEAD_REVISION)  # noqa: SLF001
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    checks = inspect(engine).get_check_constraints("brand_kit_versions")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        kit = BrandKit(name="Constraint")
        session.add(kit)
        session.commit()
        session.add(
            BrandKitVersion(
                brand_kit_id=kit.id,
                version_number=0,
                digest="0" * 64,
                **version_payload(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()

    assert any(
        check["name"] == "ck_brand_kit_version_number_positive"
        and "version_number >= 1" in str(check["sqltext"])
        for check in checks
    )


def test_0003_downgrade_and_reupgrade_only_uses_test_database(tmp_path: Path) -> None:
    database = tmp_path / "downgrade.db"
    migration_service._run_alembic(database, "upgrade", HEAD_REVISION)  # noqa: SLF001
    migration_service._run_alembic(  # noqa: SLF001
        database, "downgrade", migration_service.X2_REVISION
    )
    assert (
        migration_service._current_revision(database)  # noqa: SLF001
        == migration_service.X2_REVISION
    )
    migration_service._run_alembic(database, "upgrade", HEAD_REVISION)  # noqa: SLF001
    assert migration_service._current_revision(database) == HEAD_REVISION  # noqa: SLF001


def test_brand_kit_endpoints_make_no_external_requests(
    client: TestClient,
) -> None:
    calls = 0

    def forbidden(*_: object, **__: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("external request forbidden")

    app.dependency_overrides[get_text_generation_provider] = forbidden
    app.dependency_overrides[get_visual_generation_provider] = forbidden
    app.dependency_overrides[get_youtube_provider] = forbidden
    create_kit(client)
    assert client.get("/api/v1/brand-kits").status_code == 200
    assert calls == 0
