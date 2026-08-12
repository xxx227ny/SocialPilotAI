from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError

from alembic import command

PRE_X2_REVISION = "0001_pre_x2_runtime"
X2_REVISION = "0002_x2_presentation_snapshots"
BRAND_KIT_REVISION = "0003_brand_kit_versions"
EXECUTION_QUEUE_REVISION = "0004_execution_queue"
HEAD_REVISION = "0007_tiktok_refresh_token_expiry"
UNVERSIONED = "unversioned"
MANIFEST_VERSION = 1
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class MigrationSafetyError(RuntimeError):
    """Base error for migrations that cannot proceed safely."""


class IncompatibleSchemaError(MigrationSafetyError):
    """Raised when an unversioned or versioned schema has unknown drift."""


class DatabaseBusyError(MigrationSafetyError):
    """Raised when an offline byte-exact SQLite backup cannot be guaranteed."""


class MigrationLockError(MigrationSafetyError):
    """Raised when another migration or restore owns the database lock."""


class BackupVerificationError(MigrationSafetyError):
    """Raised when backup or restore verification fails."""


class MigrationExecutionError(MigrationSafetyError):
    def __init__(self, message: str, *, restored: bool, manifest_path: Path | None):
        super().__init__(message)
        self.restored = restored
        self.manifest_path = manifest_path


@dataclass(frozen=True)
class BackupManifest:
    manifest_version: int
    created_at: str
    source_path: str
    source_size_bytes: int
    source_sha256: str
    source_revision: str
    backup_path: str
    backup_size_bytes: int
    backup_sha256: str


@dataclass(frozen=True)
class MigrationResult:
    previous_revision: str
    current_revision: str
    schema_state: str
    backup_manifest_path: Path | None
    restored_after_failure: bool = False


@dataclass(frozen=True)
class DatabaseMigrationStatus:
    state: str
    revision: str | None
    head_revision: str
    ready: bool
    upgrade_required: bool
    message: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def _alembic_config(connection: Connection) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    return config


def _run_alembic(path: Path, action: str, revision: str) -> None:
    engine = create_engine(_database_url(path))
    try:
        with engine.begin() as connection:
            config = _alembic_config(connection)
            if action == "upgrade":
                command.upgrade(config, revision)
            elif action == "downgrade":
                command.downgrade(config, revision)
            elif action == "stamp":
                command.stamp(config, revision)
            else:
                raise ValueError(f"Unsupported Alembic action: {action}")
    finally:
        engine.dispose()


def _current_revision(path: Path) -> str | None:
    engine = create_engine(_database_url(path))
    try:
        with engine.connect() as connection:
            if "alembic_version" not in inspect(connection).get_table_names():
                return None
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _normalized_sql(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.casefold().split())


def _schema_payload(connection: Connection) -> dict[str, Any]:
    inspector = inspect(connection)
    tables = sorted(
        table
        for table in inspector.get_table_names()
        if table != "alembic_version" and not table.startswith("sqlite_")
    )
    payload: dict[str, Any] = {}
    for table in tables:
        columns = []
        for column in inspector.get_columns(table):
            columns.append(
                {
                    "name": column["name"],
                    "type": str(column["type"]).casefold(),
                    "nullable": bool(column["nullable"]),
                    "default": _normalized_sql(column.get("default")),
                    "primary_key": int(column.get("primary_key", 0)),
                }
            )
        indexes = sorted(
            (
                {
                    "name": index.get("name"),
                    "columns": list(index.get("column_names") or []),
                    "unique": bool(index.get("unique", False)),
                }
                for index in inspector.get_indexes(table)
            ),
            key=lambda item: (str(item["name"]), item["columns"]),
        )
        unique_constraints = sorted(
            (
                {
                    "name": constraint.get("name"),
                    "columns": sorted(constraint.get("column_names") or []),
                }
                for constraint in inspector.get_unique_constraints(table)
            ),
            key=lambda item: (str(item["name"]), item["columns"]),
        )
        foreign_keys = sorted(
            (
                {
                    "columns": list(foreign_key.get("constrained_columns") or []),
                    "referred_table": foreign_key.get("referred_table"),
                    "referred_columns": list(foreign_key.get("referred_columns") or []),
                    "ondelete": (foreign_key.get("options") or {}).get("ondelete"),
                }
                for foreign_key in inspector.get_foreign_keys(table)
            ),
            key=lambda item: (
                item["columns"],
                str(item["referred_table"]),
                item["referred_columns"],
            ),
        )
        checks = sorted(
            (
                {
                    "name": check.get("name"),
                    "sql": _normalized_sql(check.get("sqltext")),
                }
                for check in inspector.get_check_constraints(table)
            ),
            key=lambda item: (str(item["name"]), str(item["sql"])),
        )
        payload[table] = {
            "columns": columns,
            "primary_key": list(
                inspector.get_pk_constraint(table).get("constrained_columns") or []
            ),
            "indexes": indexes,
            "unique_constraints": unique_constraints,
            "foreign_keys": foreign_keys,
            "checks": checks,
        }
    return payload


def schema_fingerprint(path: Path) -> str:
    engine = create_engine(_database_url(path))
    try:
        with engine.connect() as connection:
            payload = _schema_payload(connection)
    finally:
        engine.dispose()
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


@lru_cache(maxsize=5)
def expected_schema_fingerprint(revision: str) -> str:
    if revision not in {
        PRE_X2_REVISION,
        X2_REVISION,
        BRAND_KIT_REVISION,
        EXECUTION_QUEUE_REVISION,
        HEAD_REVISION,
    }:
        raise ValueError(f"Unknown expected revision: {revision}")
    with tempfile.TemporaryDirectory(prefix="socialpilot-schema-fingerprint-") as raw:
        reference = Path(raw) / "reference.db"
        _run_alembic(reference, "upgrade", revision)
        return schema_fingerprint(reference)


def _assert_integrity(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if result is None or result[0] != "ok":
        raise BackupVerificationError("SQLite integrity_check failed")


def migration_lock_path(database_path: Path) -> Path:
    database = database_path.resolve()
    return database.with_name(f"{database.name}.migration.lock")


def _lock_identity_matches(file_descriptor: int, lock_path: Path) -> bool:
    try:
        descriptor_stat = os.fstat(file_descriptor)
        path_stat = lock_path.stat()
    except OSError:
        return False
    return (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
        path_stat.st_dev,
        path_stat.st_ino,
    )


def _read_lock_token(file_descriptor: int) -> str | None:
    try:
        os.lseek(file_descriptor, 0, os.SEEK_SET)
        payload = json.loads(os.read(file_descriptor, 64 * 1024).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    token = payload.get("token")
    return token if isinstance(token, str) else None


def _release_owned_lock(file_descriptor: int, lock_path: Path, token: str) -> bool:
    verified = (
        _lock_identity_matches(file_descriptor, lock_path)
        and _read_lock_token(file_descriptor) == token
    )
    try:
        os.close(file_descriptor)
    except OSError:
        verified = False
    if not verified:
        return False

    try:
        with lock_path.open("r", encoding="utf-8") as stream:
            current_payload = json.load(stream)
        if current_payload.get("token") != token:
            return False
        lock_path.unlink()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


@contextmanager
def database_migration_lock(database_path: Path) -> Iterator[Path]:
    database = database_path.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    lock_path = migration_lock_path(database)
    token = uuid4().hex
    try:
        file_descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_RDWR,
            0o600,
        )
    except FileExistsError as error:
        raise MigrationLockError(
            "Database migration lock already exists; refusing concurrent operation"
        ) from error

    payload = json.dumps(
        {
            "acquired_at": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "token": token,
        },
        sort_keys=True,
    ).encode("utf-8")
    try:
        os.write(file_descriptor, payload)
        os.fsync(file_descriptor)
    except Exception:
        _release_owned_lock(file_descriptor, lock_path, token)
        raise

    operation_error: BaseException | None = None
    try:
        yield lock_path
    except BaseException as error:
        operation_error = error
        raise
    finally:
        released = _release_owned_lock(file_descriptor, lock_path, token)
        if not released and operation_error is None:
            raise MigrationLockError(
                "Migration lock ownership could not be verified; lock retained"
            )


def _sqlite_sidecars(path: Path) -> list[Path]:
    return [Path(f"{path}{suffix}") for suffix in ("-journal", "-wal", "-shm")]


def _assert_offline_sqlite(path: Path) -> None:
    for sidecar in _sqlite_sidecars(path):
        if sidecar.exists():
            raise DatabaseBusyError(
                "SQLite journal/WAL/SHM sidecar detected; database must be offline"
            )
    if not path.exists():
        return

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=0, isolation_level=None)
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("ROLLBACK")
    except sqlite3.DatabaseError as error:
        message = str(error).casefold()
        if "locked" in message or "busy" in message:
            raise DatabaseBusyError(
                "SQLite database has an active connection; database must be offline"
            ) from error
        # A corrupt target may still be safely replaced by explicit restore. Integrity
        # validation remains mandatory for migration and for the restored backup.
    finally:
        if connection is not None:
            connection.close()

    for sidecar in _sqlite_sidecars(path):
        if sidecar.exists():
            raise DatabaseBusyError(
                "SQLite sidecar appeared during offline check; refusing operation"
            )


def create_backup(
    database_path: Path,
    backup_directory: Path,
    *,
    revision: str,
) -> Path:
    source = database_path.resolve(strict=True)
    _assert_offline_sqlite(source)
    _assert_integrity(source)
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_directory / f"{source.stem}-{timestamp}.db"
    manifest_path = backup.with_suffix(".manifest.json")
    if backup.exists() or manifest_path.exists():
        raise BackupVerificationError("Backup target already exists")
    source_size_before = source.stat().st_size
    source_hash_before = sha256_file(source)
    try:
        shutil.copy2(source, backup)
        backup_hash = sha256_file(backup)
        source_hash_after = sha256_file(source)
        source_size_after = source.stat().st_size
    except Exception:
        backup.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise
    if (
        source_hash_after != source_hash_before
        or backup_hash != source_hash_before
        or source_size_after != source_size_before
        or backup.stat().st_size != source_size_before
    ):
        backup.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise BackupVerificationError("Byte-exact SQLite backup verification failed")
    manifest = BackupManifest(
        manifest_version=MANIFEST_VERSION,
        created_at=datetime.now(UTC).isoformat(),
        source_path=str(source),
        source_size_bytes=source_size_before,
        source_sha256=source_hash_before,
        source_revision=revision,
        backup_path=str(backup.resolve()),
        backup_size_bytes=backup.stat().st_size,
        backup_sha256=backup_hash,
    )
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest_path)
    return manifest_path


def _load_manifest(manifest_path: Path) -> BackupManifest:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = BackupManifest(**data)
    if manifest.manifest_version != MANIFEST_VERSION:
        raise BackupVerificationError("Unsupported backup manifest version")
    return manifest


def _restore_backup_unlocked(
    manifest_path: Path,
    *,
    destination: Path | None = None,
) -> Path:
    manifest = _load_manifest(manifest_path.resolve(strict=True))
    backup = Path(manifest.backup_path).resolve(strict=True)
    if sha256_file(backup) != manifest.backup_sha256:
        raise BackupVerificationError("Backup SHA-256 does not match manifest")
    target = (
        destination.resolve()
        if destination is not None
        else Path(manifest.source_path).resolve()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_offline_sqlite(target)
    temporary_target = target.with_name(f".{target.name}.restore.tmp")
    try:
        shutil.copy2(backup, temporary_target)
        if sha256_file(temporary_target) != manifest.backup_sha256:
            raise BackupVerificationError(
                "Restored temporary file failed SHA-256 check"
            )
        _assert_offline_sqlite(target)
        os.replace(temporary_target, target)
    except Exception:
        temporary_target.unlink(missing_ok=True)
        raise
    _assert_integrity(target)
    return target


def restore_backup(
    manifest_path: Path,
    *,
    destination: Path | None = None,
) -> Path:
    resolved_manifest = manifest_path.resolve(strict=True)
    manifest = _load_manifest(resolved_manifest)
    target = (
        destination.resolve()
        if destination is not None
        else Path(manifest.source_path).resolve()
    )
    with database_migration_lock(target):
        return _restore_backup_unlocked(resolved_manifest, destination=target)


def _classify_unversioned_schema(path: Path) -> str:
    fingerprint = schema_fingerprint(path)
    if fingerprint == expected_schema_fingerprint(PRE_X2_REVISION):
        return "pre_x2_runtime"
    if fingerprint == expected_schema_fingerprint(X2_REVISION):
        return "x2_runtime"
    if fingerprint == expected_schema_fingerprint(BRAND_KIT_REVISION):
        return "brand_kit_runtime"
    if fingerprint == expected_schema_fingerprint(EXECUTION_QUEUE_REVISION):
        return "execution_queue_runtime"
    if fingerprint == expected_schema_fingerprint(HEAD_REVISION):
        return "unversioned_head"
    raise IncompatibleSchemaError(
        "Unversioned schema does not match a known SocialPilot migration state"
    )


def _user_table_count(path: Path) -> int:
    engine = create_engine(_database_url(path))
    try:
        with engine.connect() as connection:
            return len(
                [
                    table
                    for table in inspect(connection).get_table_names()
                    if table != "alembic_version" and not table.startswith("sqlite_")
                ]
            )
    finally:
        engine.dispose()


def get_database_migration_status(database_path: Path) -> DatabaseMigrationStatus:
    """Classify a SQLite database without creating locks, backups, or DB writes."""
    database = database_path.resolve()
    if migration_lock_path(database).exists():
        return DatabaseMigrationStatus(
            state="locked",
            revision=None,
            head_revision=HEAD_REVISION,
            ready=False,
            upgrade_required=False,
            message="Another database migration or restore is in progress.",
        )
    if not database.exists():
        return DatabaseMigrationStatus(
            state="missing",
            revision=None,
            head_revision=HEAD_REVISION,
            ready=False,
            upgrade_required=True,
            message="Database does not exist and requires initialization.",
        )
    if database.stat().st_size == 0:
        return DatabaseMigrationStatus(
            state="empty",
            revision=None,
            head_revision=HEAD_REVISION,
            ready=False,
            upgrade_required=True,
            message="Database is empty and requires initialization.",
        )

    try:
        if _user_table_count(database) == 0:
            return DatabaseMigrationStatus(
                state="empty",
                revision=None,
                head_revision=HEAD_REVISION,
                ready=False,
                upgrade_required=True,
                message=(
                    "Database has no application tables and requires initialization."
                ),
            )
        revision = _current_revision(database)
        if revision is None:
            schema_state = _classify_unversioned_schema(database)
            return DatabaseMigrationStatus(
                state=schema_state,
                revision=None,
                head_revision=HEAD_REVISION,
                ready=False,
                upgrade_required=True,
                message="Known unversioned database requires a safe migration.",
            )
        if revision not in {
            PRE_X2_REVISION,
            X2_REVISION,
            BRAND_KIT_REVISION,
            EXECUTION_QUEUE_REVISION,
            HEAD_REVISION,
        }:
            raise IncompatibleSchemaError("Unsupported Alembic revision")
        if schema_fingerprint(database) != expected_schema_fingerprint(revision):
            raise IncompatibleSchemaError(
                "Database schema does not match its Alembic revision"
            )
        if revision == HEAD_REVISION:
            return DatabaseMigrationStatus(
                state="head",
                revision=revision,
                head_revision=HEAD_REVISION,
                ready=True,
                upgrade_required=False,
                message="Database is at the verified Alembic head revision.",
            )
        state_by_revision = {
            PRE_X2_REVISION: "pre_x2_runtime",
            X2_REVISION: "x2_runtime",
            BRAND_KIT_REVISION: "brand_kit_runtime",
            EXECUTION_QUEUE_REVISION: "execution_queue_runtime",
        }
        return DatabaseMigrationStatus(
            state=state_by_revision[revision],
            revision=revision,
            head_revision=HEAD_REVISION,
            ready=False,
            upgrade_required=True,
            message="Known prior database revision requires a safe migration.",
        )
    except (MigrationSafetyError, OSError, sqlite3.DatabaseError, SQLAlchemyError):
        return DatabaseMigrationStatus(
            state="incompatible",
            revision=None,
            head_revision=HEAD_REVISION,
            ready=False,
            upgrade_required=False,
            message="Database schema is incompatible with the known migration chain.",
        )


def _upgrade_sqlite_database_unlocked(
    database_path: Path,
    backup_directory: Path,
) -> MigrationResult:
    database = database_path.resolve()
    existed = database.exists() and database.stat().st_size > 0
    manifest_path: Path | None = None
    previous_revision = UNVERSIONED
    if existed:
        _assert_offline_sqlite(database)
        previous_revision = _current_revision(database) or UNVERSIONED
        manifest_path = create_backup(
            database, backup_directory.resolve(), revision=previous_revision
        )
    else:
        database.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not existed or _user_table_count(database) == 0:
            schema_state = "empty"
            _run_alembic(database, "upgrade", HEAD_REVISION)
        else:
            revision = _current_revision(database)
            if revision is None:
                schema_state = _classify_unversioned_schema(database)
                stamp_revision = {
                    "pre_x2_runtime": PRE_X2_REVISION,
                    "x2_runtime": X2_REVISION,
                    "brand_kit_runtime": BRAND_KIT_REVISION,
                    "execution_queue_runtime": EXECUTION_QUEUE_REVISION,
                    "unversioned_head": HEAD_REVISION,
                }[schema_state]
                _run_alembic(database, "stamp", stamp_revision)
                if stamp_revision != HEAD_REVISION:
                    _run_alembic(database, "upgrade", HEAD_REVISION)
            else:
                if revision not in {
                    PRE_X2_REVISION,
                    X2_REVISION,
                    BRAND_KIT_REVISION,
                    EXECUTION_QUEUE_REVISION,
                    HEAD_REVISION,
                }:
                    raise IncompatibleSchemaError(
                        f"Database has unsupported Alembic revision: {revision}"
                    )
                if schema_fingerprint(database) != expected_schema_fingerprint(
                    revision
                ):
                    raise IncompatibleSchemaError(
                        "Versioned database schema does not match its Alembic revision"
                    )
                schema_state = "versioned"
                _run_alembic(database, "upgrade", HEAD_REVISION)

        current_revision = _current_revision(database)
        if current_revision != HEAD_REVISION:
            raise MigrationSafetyError(
                "Database did not reach the expected head revision"
            )
        if schema_fingerprint(database) != expected_schema_fingerprint(HEAD_REVISION):
            raise MigrationSafetyError(
                "Migrated database schema fingerprint is invalid"
            )
        return MigrationResult(
            previous_revision=previous_revision,
            current_revision=current_revision,
            schema_state=schema_state,
            backup_manifest_path=manifest_path,
        )
    except IncompatibleSchemaError:
        if existed and manifest_path is not None:
            manifest = _load_manifest(manifest_path)
            if sha256_file(database) != manifest.source_sha256:
                _restore_backup_unlocked(manifest_path, destination=database)
        raise
    except Exception as error:
        restored = False
        if manifest_path is not None:
            _restore_backup_unlocked(manifest_path, destination=database)
            restored = True
        elif not existed:
            database.unlink(missing_ok=True)
            Path(f"{database}-journal").unlink(missing_ok=True)
        raise MigrationExecutionError(
            "Migration failed; original database was restored"
            if restored
            else "Migration failed; partial empty database was removed",
            restored=restored,
            manifest_path=manifest_path,
        ) from error


def upgrade_sqlite_database(
    database_path: Path,
    backup_directory: Path,
) -> MigrationResult:
    database = database_path.resolve()
    with database_migration_lock(database):
        return _upgrade_sqlite_database_unlocked(database, backup_directory.resolve())
