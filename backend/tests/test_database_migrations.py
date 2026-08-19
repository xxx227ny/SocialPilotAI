from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401
import app.services.database_migration_service as migration_service
from app.db.base import Base
from app.services.database_migration_service import (
    HEAD_REVISION,
    BackupVerificationError,
    DatabaseBusyError,
    IncompatibleSchemaError,
    MigrationExecutionError,
    MigrationLockError,
    get_database_migration_status,
    migration_lock_path,
    restore_backup,
    schema_fingerprint,
    sha256_file,
    upgrade_sqlite_database,
)

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
    migration_service._run_alembic(  # noqa: SLF001
        path, "upgrade", migration_service.PRE_X2_REVISION
    )
    now = datetime.now(UTC).isoformat()
    copies = json.dumps(
        [
            {
                "platform": platform,
                "hook": f"{platform} hook",
                "caption": "Stable caption",
                "hashtags": ["Stable"],
                "cta": "Learn more",
            }
            for platform in ("TikTok", "Instagram", "Facebook")
        ]
    )
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            f"""
            DROP TABLE alembic_version;
            INSERT INTO products VALUES
              (1,'Migration Evidence Product','Test','Preserve this exact content',
               '["Stable"]','["US"]','{now}','{now}');
            INSERT INTO marketing_briefs VALUES
              (1,1,'Migration audience','English','["TikTok"]','Clear',
               'Awareness','{now}');
            INSERT INTO marketing_strategies VALUES
              (1,1,'Migration-safe positioning','["Stable insight"]',
               '["Stable angle"]','["Stable risk"]','["Stable evidence"]','{now}');
            INSERT INTO copy_matrices VALUES (1,1,1,'{copies}','{now}');
            INSERT INTO video_projects VALUES
              (1,1,1,1,'TikTok','Stable video','Stable concept',15,'9:16',
               '[{{"sequence":1,"duration_seconds":15}}]','Learn more','planned',
               '{now}','{now}');
            INSERT INTO video_render_tasks VALUES
              (1,1,1,'SUCCEEDED','fake','fake-task','Stable prompt',15,'9:16',
               '720p','migration-render-1',NULL,NULL,'{now}','{now}');
            INSERT INTO video_render_artifacts VALUES
              (1,1,NULL,'artifacts/stable.mp4',
               '{{"sha256":"{"A" * 64}","size_bytes":1234}}',NULL,'{now}','{now}');
            INSERT INTO social_accounts VALUES
              (1,1,'youtube','migration-channel','Migration Channel','["upload"]',
               'encrypted-test-value','encrypted-test-value','{now}','CONNECTED',
               'test-key','{now}','{now}',NULL);
            INSERT INTO publish_tasks VALUES
              (1,1,1,1,'youtube','migration-publish-1','{"B" * 64}','{"C" * 64}',
               'Stable private delivery','Stable description','["Stable"]','private',
               0,1,0,'SUCCEEDED','migration-video',NULL,NULL,0,'{now}','{now}',
               NULL,NULL);
            """
        )
        connection.commit()
    finally:
        connection.close()


def business_snapshot(path: Path) -> str:
    payload: dict[str, list[dict[str, object]]] = {}
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        for table_name in BUSINESS_TABLES:
            rows = connection.execute(f'SELECT * FROM "{table_name}" ORDER BY id')
            payload[table_name] = []
            for row in rows:
                record = dict(row)
                record.pop("brand_kit_version_id", None)
                record.pop("provider_container_id", None)
                record.pop("share_to_feed", None)
                record.pop("refresh_token_expires_at", None)
                record.pop("provider_publish_id", None)
                record.pop("disable_comment", None)
                record.pop("disable_duet", None)
                record.pop("disable_stitch", None)
                record.pop("brand_content_toggle", None)
                record.pop("brand_organic_toggle", None)
                payload[table_name].append(record)
    finally:
        connection.close()
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


def test_stage3e_0010_database_upgrades_to_0013_and_preserves_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stage3c-from-0010.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0010_video_composition_enhancements"
    )
    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO products "
            "(id,name,category,description,selling_points,target_markets,"
            "created_at,updated_at,brand_kit_version_id) "
            "VALUES (?,?,?,?,?,?,?,?,NULL)",
            (1, "Stage3C preserved", "Test", "Exact", '["Stable"]', "[]", now, now),
        )
        connection.commit()
    finally:
        connection.close()

    result = upgrade_sqlite_database(database, tmp_path / "backups")
    connection = sqlite3.connect(database)
    try:
        product = connection.execute(
            "SELECT name, selling_points FROM products WHERE id=1"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert result.previous_revision == "0010_video_composition_enhancements"
    assert result.current_revision == HEAD_REVISION
    assert product == ("Stage3C preserved", '["Stable"]')
    assert {"batch_video_jobs", "batch_video_variants"}.issubset(tables)
    assert current_revision(database) == HEAD_REVISION


def test_stage3c_temporary_downgrade_returns_to_0010(tmp_path: Path) -> None:
    database = tmp_path / "stage3c-downgrade.db"
    migration_service._run_alembic(database, "upgrade", "0011_batch_video_jobs")  # noqa: SLF001
    migration_service._run_alembic(  # noqa: SLF001
        database, "downgrade", "0010_video_composition_enhancements"
    )
    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert "batch_video_jobs" not in tables
    assert "batch_video_variants" not in tables
    assert current_revision(database) == "0010_video_composition_enhancements"


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
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT provider_container_id, share_to_feed FROM publish_tasks WHERE id=1"
        ).fetchone() == (None, 0)
    finally:
        connection.close()
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


def test_tiktok_refresh_expiry_upgrade_downgrade_and_reupgrade(
    tmp_path: Path,
) -> None:
    database = tmp_path / "tiktok-expiry.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0006_instagram_publish_container_identity"
    )
    before = business_snapshot(database)
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", HEAD_REVISION
    )
    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(social_accounts)")
        }
    finally:
        connection.close()
    assert "refresh_token_expires_at" in columns
    assert business_snapshot(database) == before

    migration_service._run_alembic(  # noqa: SLF001
        database, "downgrade", "0006_instagram_publish_container_identity"
    )
    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(social_accounts)")
        }
    finally:
        connection.close()
    assert "refresh_token_expires_at" not in columns
    assert business_snapshot(database) == before

    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", HEAD_REVISION
    )
    assert current_revision(database) == HEAD_REVISION


def test_video_composition_upgrade_preserves_0008_business_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "from-0008.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0008_tiktok_direct_post"
    )
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO products "
            "(id,name,category,description,selling_points,target_markets,"
            "created_at,updated_at,brand_kit_version_id) "
            "VALUES (1,'P','C','D','[\"Portable\"]','[\"US\"]',?,?,NULL)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO marketing_strategies VALUES "
            "(1,1,'Position','[\"Insight\"]','[\"Angle\"]',"
            "'[\"Risk\"]','[\"Evidence\"]',?)",
            (now,),
        )
        copies = json.dumps(
            [
                {"platform": platform, "caption": "Copy"}
                for platform in ("TikTok", "Instagram", "Facebook")
            ]
        )
        connection.execute(
            "INSERT INTO copy_matrices VALUES (1,1,1,?,?)", (copies, now)
        )
        scenes = json.dumps(
            [
                {
                    "sequence": 1,
                    "duration_seconds": 15,
                    "shot_type": "hero",
                    "visual_description": "Product",
                    "action": "Show",
                    "narration": "Placeholder",
                }
            ]
        )
        connection.execute(
            "INSERT INTO video_projects VALUES "
            "(1,1,1,1,'TikTok','Video','Concept',15,'9:16',?,"
            "'CTA','planned',?,?)",
            (scenes, now, now),
        )
        connection.execute(
            "INSERT INTO video_render_tasks VALUES "
            "(1,1,1,'SUCCEEDED','fake','task','prompt',15,'9:16',"
            "'720P','render-key',NULL,NULL,?,?)",
            (now, now),
        )
        sha = "a" * 64
        metadata = json.dumps(
            {"content_type": "video/mp4", "size_bytes": 5, "sha256": sha}
        )
        connection.execute(
            "INSERT INTO video_render_artifacts VALUES "
            "(1,1,NULL,'render-task-1.mp4',?,NULL,?,?)",
            (metadata, now, now),
        )
        connection.commit()
    before = business_snapshot(database)
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0009_video_compositions"
    )
    assert current_revision(database) == "0009_video_compositions"
    assert business_snapshot(database) == before
    with sqlite3.connect(database) as connection:
        for table in (
            "video_compositions",
            "video_composition_shots",
            "video_composition_artifacts",
        ):
            assert (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            )
    migration_service._run_alembic(  # noqa: SLF001
        database, "downgrade", "0008_tiktok_direct_post"
    )
    assert business_snapshot(database) == before
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0009_video_compositions"
    )
    assert business_snapshot(database) == before
    assert business_snapshot(database) == before


def test_video_enhancement_upgrade_preserves_0009_composition_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "from-0009.db"
    migration_service._run_alembic(  # noqa: SLF001
        database, "upgrade", "0009_video_compositions"
    )
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO products "
            "(id,name,category,description,selling_points,target_markets,"
            "created_at,updated_at,brand_kit_version_id) "
            "VALUES (1,'P','C','D','[\"Stable\"]','[\"US\"]',?,?,NULL)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO marketing_strategies VALUES "
            "(1,1,'Position','[\"Insight\"]','[\"Angle\"]',"
            "'[\"Risk\"]','[\"Evidence\"]',?)",
            (now,),
        )
        connection.execute("INSERT INTO copy_matrices VALUES (1,1,1,'[]',?)", (now,))
        connection.execute(
            "INSERT INTO video_projects VALUES "
            "(1,1,1,1,'TikTok','Video','Concept',15,'9:16','[]',"
            "'CTA','planned',?,?)",
            (now, now),
        )
        connection.execute(
            "INSERT INTO video_compositions VALUES "
            "(1,1,1,?,?,?,1,15000,'9:16',1080,1920,30,1,'SUCCEEDED',"
            "NULL,?,?,?)",
            ("a" * 64, "b" * 64, "composition-key", now, now, now),
        )
        connection.execute(
            "INSERT INTO video_composition_artifacts VALUES "
            "(1,1,'composition.mp4','video/mp4',100,?,15000,1080,1920,30,1,"
            "'h264','yuv420p','aac',48000,'mp4',?,?)",
            ("c" * 64, "b" * 64, now),
        )
        connection.commit()
        before = {
            "composition": connection.execute(
                "SELECT * FROM video_compositions"
            ).fetchall(),
            "artifact": connection.execute(
                "SELECT * FROM video_composition_artifacts"
            ).fetchall(),
        }
    migration_result = upgrade_sqlite_database(database, tmp_path / "backups")
    assert migration_result.previous_revision == "0009_video_compositions"
    assert current_revision(database) == HEAD_REVISION
    with sqlite3.connect(database) as connection:
        composition_rows = connection.execute(
            "SELECT * FROM video_compositions"
        ).fetchall()
        assert composition_rows == before["composition"]
        assert (
            connection.execute("SELECT * FROM video_composition_artifacts").fetchall()
            == before["artifact"]
        )
        for table in (
            "video_composition_audio_artifacts",
            "video_composition_enhancements",
            "video_composition_subtitle_artifacts",
            "video_composition_enhancement_artifacts",
        ):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert count == 0
    migration_service._run_alembic(  # noqa: SLF001
        database, "downgrade", "0009_video_compositions"
    )
    assert current_revision(database) == "0009_video_compositions"
    with sqlite3.connect(database) as connection:
        composition_rows = connection.execute(
            "SELECT * FROM video_compositions"
        ).fetchall()
        assert composition_rows == before["composition"]
    migration_service._run_alembic(database, "upgrade", HEAD_REVISION)  # noqa: SLF001
    assert current_revision(database) == HEAD_REVISION


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
        first = executor.submit(upgrade_sqlite_database, database, tmp_path / "backups")
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


def test_read_only_status_classifies_supported_database_states(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    assert get_database_migration_status(missing).state == "missing"
    assert not missing.exists()

    empty = tmp_path / "empty.db"
    empty.touch()
    empty_hash = sha256_file(empty)
    assert get_database_migration_status(empty).state == "empty"
    assert sha256_file(empty) == empty_hash

    legacy = tmp_path / "legacy.db"
    create_legacy_runtime(legacy)
    legacy_hash = sha256_file(legacy)
    legacy_status = get_database_migration_status(legacy)
    assert legacy_status.state == "pre_x2_runtime"
    assert legacy_status.upgrade_required is True
    assert sha256_file(legacy) == legacy_hash

    unversioned_head = tmp_path / "unversioned-head.db"
    engine = create_engine(sqlite_url(unversioned_head))
    Base.metadata.create_all(engine)
    engine.dispose()
    assert get_database_migration_status(unversioned_head).state == "unversioned_head"


def test_stage3d_0011_upgrades_through_0013_with_existing_batch_unchanged(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stage3d-from-0011.db"
    migration_service._run_alembic(database, "upgrade", "0011_batch_video_jobs")  # noqa: SLF001
    connection = sqlite3.connect(database)
    before = connection.execute("SELECT COUNT(*) FROM batch_video_variants").fetchone()[
        0
    ]
    connection.close()
    result = upgrade_sqlite_database(database, tmp_path / "stage3d-backups")
    connection = sqlite3.connect(database)
    try:
        columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(batch_video_variants)")
        }
        after = connection.execute(
            "SELECT COUNT(*) FROM batch_video_variants"
        ).fetchone()[0]
    finally:
        connection.close()
    assert result.previous_revision == "0011_batch_video_jobs"
    assert result.current_revision == HEAD_REVISION
    assert before == after
    assert columns["script_version_sequence"][4] == "'0'"
    assert columns["active_script_version_id"][3] == 0


def test_stage3d_temporary_downgrade_removes_active_reference_before_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stage3d-downgrade.db"
    migration_service._run_alembic(database, "upgrade", "0012_video_script_versions")  # noqa: SLF001
    migration_service._run_alembic(database, "downgrade", "0011_batch_video_jobs")  # noqa: SLF001
    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(batch_video_variants)")
        }
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        connection.close()
    assert revision == "0011_batch_video_jobs"
    assert "video_script_versions" not in tables
    assert "video_storyboard_scene_versions" not in tables
    assert "active_script_version_id" not in columns
    assert "script_version_sequence" not in columns


def test_stage3e_0012_upgrade_and_temporary_downgrade_preserve_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stage3e-from-0012.db"
    migration_service._run_alembic(database, "upgrade", "0012_video_script_versions")  # noqa: SLF001
    before = schema_fingerprint(database)
    migration_service._run_alembic(database, "upgrade", HEAD_REVISION)  # noqa: SLF001
    connection = sqlite3.connect(database)
    try:
        version_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(video_script_versions)")
        }
        attempt_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(execution_attempts)")
        }
        batch_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(batch_video_jobs)")
        }
    finally:
        connection.close()
    assert current_revision(database) == HEAD_REVISION
    assert {
        "source_execution_job_id",
        "prompt_snapshot_json",
        "prompt_digest",
        "provider_name",
        "provider_model",
        "provider_response_digest",
    }.issubset(version_columns)
    assert "provider_submission_state" in attempt_columns
    assert {"qwen_script_call_quota", "qwen_script_calls_reserved"}.issubset(
        batch_columns
    )
    migration_service._run_alembic(database, "downgrade", "0012_video_script_versions")  # noqa: SLF001
    assert current_revision(database) == "0012_video_script_versions"
    assert schema_fingerprint(database) == before


def test_head_status_is_read_only_and_creates_no_backup(tmp_path: Path) -> None:
    database = tmp_path / "head-status.db"
    backups = tmp_path / "backups"
    upgrade_sqlite_database(database, backups)
    before_hash = sha256_file(database)
    before_backups = list(backups.glob("*")) if backups.exists() else []

    status = get_database_migration_status(database)

    assert status.state == "head"
    assert status.ready is True
    assert status.upgrade_required is False
    assert status.revision == HEAD_REVISION
    assert sha256_file(database) == before_hash
    assert (list(backups.glob("*")) if backups.exists() else []) == before_backups


def test_status_reports_incompatible_schema_and_preserves_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "status-incompatible.db"
    create_legacy_runtime(database)
    connection = sqlite3.connect(database)
    connection.execute("ALTER TABLE products ADD COLUMN unknown_status_column TEXT")
    connection.commit()
    connection.close()
    before_hash = sha256_file(database)

    status = get_database_migration_status(database)

    assert status.state == "incompatible"
    assert status.ready is False
    assert status.upgrade_required is False
    assert sha256_file(database) == before_hash


def test_status_reports_lock_conflict_without_deleting_unknown_lock(
    tmp_path: Path,
) -> None:
    database = tmp_path / "status-locked.db"
    create_legacy_runtime(database)
    lock = migration_lock_path(database)
    lock.write_text('{"token":"unknown-owner"}', encoding="utf-8")
    before_hash = sha256_file(database)

    status = get_database_migration_status(database)

    assert status.state == "locked"
    assert status.ready is False
    assert status.upgrade_required is False
    assert lock.read_text(encoding="utf-8") == '{"token":"unknown-owner"}'
    assert sha256_file(database) == before_hash
