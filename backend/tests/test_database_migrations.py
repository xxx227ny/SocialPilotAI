from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
import app.services.database_migration_service as migration_service
from app.db.base import Base
from app.models import (
    CopyMatrix,
    MarketingBrief,
    MarketingStrategy,
    Product,
    PublishTask,
    SocialAccount,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.services.database_migration_service import (
    HEAD_REVISION,
    BackupVerificationError,
    DatabaseBusyError,
    IncompatibleSchemaError,
    MigrationExecutionError,
    MigrationLockError,
    migration_lock_path,
    restore_backup,
    sha256_file,
    upgrade_sqlite_database,
)

PRE_X2_TABLES = [
    table
    for table in Base.metadata.sorted_tables
    if table.name != "presentation_snapshots"
]
BUSINESS_TABLES = [
    "products",
    "marketing_briefs",
    "marketing_strategies",
    "copy_matrices",
    "video_projects",
    "video_render_tasks",
    "video_render_artifacts",
    "social_accounts",
    "publish_tasks",
]


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def create_legacy_runtime(path: Path) -> None:
    engine = create_engine(sqlite_url(path))
    Base.metadata.create_all(engine, tables=PRE_X2_TABLES)
    with Session(engine) as session:
        product = Product(
            name="Migration Evidence Product",
            category="Test",
            description="Preserve this exact content",
            selling_points=["Stable"],
            target_markets=["US"],
        )
        session.add(product)
        session.flush()
        brief = MarketingBrief(
            product_id=product.id,
            audience="Migration audience",
            language="English",
            platforms=["TikTok"],
            tone="Clear",
            objective="Awareness",
        )
        strategy = MarketingStrategy(
            product_id=product.id,
            positioning="Migration-safe positioning",
            audience_insights=["Stable insight"],
            angles=["Stable angle"],
            risks=["Stable risk"],
            evidence=["Stable evidence"],
        )
        session.add_all([brief, strategy])
        session.flush()
        copy = CopyMatrix(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copies=[
                {
                    "platform": platform,
                    "hook": f"{platform} hook",
                    "caption": "Stable caption",
                    "hashtags": ["Stable"],
                    "cta": "Learn more",
                }
                for platform in ("TikTok", "Instagram", "Facebook")
            ],
        )
        session.add(copy)
        session.flush()
        video = VideoProject(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copy_matrix_id=copy.id,
            platform="TikTok",
            title="Stable video",
            concept="Stable concept",
            duration_seconds=15,
            aspect_ratio="9:16",
            scenes=[{"sequence": 1, "duration_seconds": 15}],
            cta="Learn more",
            status="planned",
        )
        session.add(video)
        session.flush()
        render = VideoRenderTask(
            video_project_id=video.id,
            scene_sequence=1,
            status="SUCCEEDED",
            provider_name="fake",
            provider_task_id="fake-task",
            render_prompt="Stable prompt",
            duration_seconds=15,
            aspect_ratio="9:16",
            resolution="720p",
            idempotency_key="migration-render-1",
        )
        session.add(render)
        session.flush()
        artifact = VideoRenderArtifact(
            video_render_task_id=render.id,
            storage_path="artifacts/stable.mp4",
            artifact_metadata={"sha256": "A" * 64, "size_bytes": 1234},
        )
        session.add(artifact)
        session.flush()
        account = SocialAccount(
            product_id=product.id,
            platform="youtube",
            provider_account_id="migration-channel",
            display_name="Migration Channel",
            scopes=["upload"],
            access_token_ciphertext="encrypted-test-value",
            refresh_token_ciphertext="encrypted-test-value",
            token_expires_at=datetime.now(UTC),
            connection_status="CONNECTED",
            encryption_key_id="test-key",
        )
        session.add(account)
        session.flush()
        session.add(
            PublishTask(
                product_id=product.id,
                social_account_id=account.id,
                artifact_id=artifact.id,
                platform="youtube",
                idempotency_key="migration-publish-1",
                request_digest="B" * 64,
                preflight_digest="C" * 64,
                title="Stable private delivery",
                description="Stable description",
                tags=["Stable"],
                privacy_status="private",
                made_for_kids=False,
                synthetic_media=True,
                notify_subscribers=False,
                status="SUCCEEDED",
                provider_video_id="migration-video",
                uncertain=False,
            )
        )
        session.commit()
    engine.dispose()


def business_snapshot(path: Path) -> str:
    engine = create_engine(sqlite_url(path))
    payload: dict[str, list[dict[str, object]]] = {}
    with engine.connect() as connection:
        for table_name in BUSINESS_TABLES:
            table = Base.metadata.tables[table_name]
            rows = connection.execute(select(table).order_by(table.c.id)).mappings()
            payload[table_name] = [dict(row) for row in rows]
    engine.dispose()
    return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=True)


def current_revision(path: Path) -> str | None:
    connection = sqlite3.connect(path)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if exists is None:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return None if row is None else str(row[0])
    finally:
        connection.close()


def test_empty_database_upgrades_to_complete_head_schema(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    result = upgrade_sqlite_database(database, tmp_path / "backups")

    engine = create_engine(sqlite_url(database))
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert result.schema_state == "empty"
    assert result.previous_revision == "unversioned"
    assert result.current_revision == HEAD_REVISION
    assert result.backup_manifest_path is None
    assert set(Base.metadata.tables).issubset(tables)
    assert "alembic_version" in tables


def test_head_revision_matches_all_current_model_schema(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.db"
    modeled = tmp_path / "modeled.db"
    upgrade_sqlite_database(migrated, tmp_path / "backups")
    engine = create_engine(sqlite_url(modeled))
    Base.metadata.create_all(engine)
    engine.dispose()

    assert migration_service.schema_fingerprint(migrated) == (
        migration_service.schema_fingerprint(modeled)
    )


def test_unversioned_runtime_is_backed_up_stamped_and_preserves_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.db"
    create_legacy_runtime(database)
    before = business_snapshot(database)
    before_hash = sha256_file(database)

    result = upgrade_sqlite_database(database, tmp_path / "backups")

    assert result.schema_state == "pre_x2_runtime"
    assert result.previous_revision == "unversioned"
    assert result.current_revision == HEAD_REVISION
    assert result.backup_manifest_path is not None
    assert business_snapshot(database) == before
    assert current_revision(database) == HEAD_REVISION
    engine = create_engine(sqlite_url(database))
    snapshot_columns = {
        column["name"]
        for column in inspect(engine).get_columns("presentation_snapshots")
    }
    engine.dispose()
    assert {"digest", "snapshot_payload", "artifact_snapshot_path"}.issubset(
        snapshot_columns
    )

    manifest = json.loads(result.backup_manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_revision"] == "unversioned"
    assert manifest["source_sha256"] == before_hash
    assert manifest["backup_sha256"] == before_hash
    assert manifest["source_size_bytes"] == manifest["backup_size_bytes"]


def test_repeated_upgrade_at_head_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "head.db"
    upgrade_sqlite_database(database, tmp_path / "backups")
    before_hash = sha256_file(database)
    before_schema = migration_service.schema_fingerprint(database)

    result = upgrade_sqlite_database(database, tmp_path / "backups")

    assert result.previous_revision == HEAD_REVISION
    assert result.current_revision == HEAD_REVISION
    assert result.schema_state == "versioned"
    assert result.backup_manifest_path is not None
    assert sha256_file(database) == before_hash
    assert migration_service.schema_fingerprint(database) == before_schema


def test_unversioned_current_schema_is_safely_stamped_at_head(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unversioned-head.db"
    engine = create_engine(sqlite_url(database))
    Base.metadata.create_all(engine)
    engine.dispose()

    result = upgrade_sqlite_database(database, tmp_path / "backups")

    assert result.schema_state == "unversioned_head"
    assert result.previous_revision == "unversioned"
    assert current_revision(database) == HEAD_REVISION


def test_incompatible_schema_is_rejected_without_changing_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "incompatible.db"
    create_legacy_runtime(database)
    connection = sqlite3.connect(database)
    connection.execute("ALTER TABLE products ADD COLUMN rogue_column TEXT")
    connection.commit()
    connection.close()
    before_hash = sha256_file(database)

    with pytest.raises(IncompatibleSchemaError):
        upgrade_sqlite_database(database, tmp_path / "backups")

    assert sha256_file(database) == before_hash
    assert current_revision(database) is None
    assert list((tmp_path / "backups").glob("*.manifest.json"))


def test_failed_migration_restores_byte_exact_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "failure.db"
    create_legacy_runtime(database)
    before_hash = sha256_file(database)
    before_data = business_snapshot(database)
    real_run_alembic = migration_service._run_alembic

    def failing_run(path: Path, action: str, revision: str) -> None:
        if path == database.resolve() and action == "upgrade":
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE migration_damage (id INTEGER)")
            connection.commit()
            connection.close()
            raise RuntimeError("injected migration failure")
        real_run_alembic(path, action, revision)

    monkeypatch.setattr(migration_service, "_run_alembic", failing_run)

    with pytest.raises(MigrationExecutionError) as captured:
        upgrade_sqlite_database(database, tmp_path / "backups")

    assert captured.value.restored is True
    assert captured.value.manifest_path is not None
    assert sha256_file(database) == before_hash
    assert business_snapshot(database) == before_data
    assert current_revision(database) is None
    connection = sqlite3.connect(database)
    damage = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_damage'"
    ).fetchone()
    connection.close()
    assert damage is None


def test_explicit_restore_verifies_manifest_and_recovers_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "restore.db"
    create_legacy_runtime(database)
    result = upgrade_sqlite_database(database, tmp_path / "backups")
    assert result.backup_manifest_path is not None
    manifest = json.loads(result.backup_manifest_path.read_text(encoding="utf-8"))

    database.write_bytes(b"not a database")
    restored = restore_backup(result.backup_manifest_path)

    assert restored == database.resolve()
    assert sha256_file(database) == manifest["source_sha256"]
    assert current_revision(database) is None


def test_two_concurrent_upgrades_allow_only_one_to_enter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "concurrent.db"
    entered = threading.Event()
    release = threading.Event()
    real_upgrade = migration_service._upgrade_sqlite_database_unlocked
    calls = 0

    def blocked_upgrade(database_path: Path, backup_directory: Path):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return real_upgrade(database_path, backup_directory)

    monkeypatch.setattr(
        migration_service, "_upgrade_sqlite_database_unlocked", blocked_upgrade
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            upgrade_sqlite_database, database, tmp_path / "backups"
        )
        assert entered.wait(timeout=5)
        with pytest.raises(MigrationLockError):
            upgrade_sqlite_database(database, tmp_path / "other-backups")
        release.set()
        result = first.result(timeout=10)

    assert calls == 1
    assert result.current_revision == HEAD_REVISION
    assert not migration_lock_path(database).exists()


def test_upgrade_and_restore_are_mutually_exclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "upgrade-restore.db"
    create_legacy_runtime(database)
    manifest = migration_service.create_backup(
        database, tmp_path / "restore-source", revision="unversioned"
    )
    entered = threading.Event()
    release = threading.Event()
    real_upgrade = migration_service._upgrade_sqlite_database_unlocked

    def blocked_upgrade(database_path: Path, backup_directory: Path):
        entered.set()
        assert release.wait(timeout=5)
        return real_upgrade(database_path, backup_directory)

    monkeypatch.setattr(
        migration_service, "_upgrade_sqlite_database_unlocked", blocked_upgrade
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            upgrade_sqlite_database, database, tmp_path / "upgrade-backups"
        )
        assert entered.wait(timeout=5)
        with pytest.raises(MigrationLockError):
            restore_backup(manifest, destination=database)
        release.set()
        first.result(timeout=10)

    assert not migration_lock_path(database).exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_restore_rejects_active_sidecar_without_changing_target(
    tmp_path: Path,
    suffix: str,
) -> None:
    database = tmp_path / "sidecar.db"
    create_legacy_runtime(database)
    manifest = migration_service.create_backup(
        database, tmp_path / "backups", revision="unversioned"
    )
    before_hash = sha256_file(database)
    sidecar = Path(f"{database}{suffix}")
    sidecar.write_bytes(b"active-sidecar-evidence")

    with pytest.raises(DatabaseBusyError):
        restore_backup(manifest, destination=database)

    assert sha256_file(database) == before_hash
    assert sidecar.read_bytes() == b"active-sidecar-evidence"
    assert not migration_lock_path(database).exists()


def test_source_change_during_backup_rejects_migration_and_cleans_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "changing.db"
    create_legacy_runtime(database)
    backup_directory = tmp_path / "backups"
    original_copy = migration_service.shutil.copy2

    def changing_copy(source: Path, destination: Path):
        result = original_copy(source, destination)
        if Path(source).resolve() == database.resolve():
            with database.open("ab") as stream:
                stream.write(b"source-changed-during-backup")
        return result

    monkeypatch.setattr(migration_service.shutil, "copy2", changing_copy)

    with pytest.raises(BackupVerificationError):
        upgrade_sqlite_database(database, backup_directory)

    assert current_revision(database) is None
    assert list(backup_directory.glob("*")) == []
    assert not migration_lock_path(database).exists()


def test_failed_operation_releases_lock_for_next_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "released-after-failure.db"
    real_upgrade = migration_service._upgrade_sqlite_database_unlocked

    def injected_failure(database_path: Path, backup_directory: Path):
        raise RuntimeError("injected pre-migration failure")

    monkeypatch.setattr(
        migration_service, "_upgrade_sqlite_database_unlocked", injected_failure
    )
    with pytest.raises(RuntimeError, match="injected pre-migration failure"):
        upgrade_sqlite_database(database, tmp_path / "backups")

    assert not migration_lock_path(database).exists()
    monkeypatch.setattr(
        migration_service, "_upgrade_sqlite_database_unlocked", real_upgrade
    )
    assert (
        upgrade_sqlite_database(database, tmp_path / "backups").current_revision
        == HEAD_REVISION
    )
    assert not migration_lock_path(database).exists()
