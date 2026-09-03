import sqlite3
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLEANUP_PATH = REPOSITORY_ROOT / "deploy" / "staging" / "cleanup_account_records.py"


def _load_module():
    spec = spec_from_file_location("staging_account_cleanup", CLEANUP_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_matches_only_accounts_created_by_staging_smoke() -> None:
    module = _load_module()

    assert module.is_managed_smoke_email(
        "smoke-a-20260903010101abcdef@invalid.example"
    )
    assert module.is_managed_smoke_email(
        "SMOKE-B-20260903010101ABCDEF@invalid.example"
    )
    assert module.is_managed_smoke_email(
        "media-owner-20260903010101abcdef@invalid.example"
    )
    assert module.is_managed_smoke_email(
        "MEDIA-OTHER-20260903010101ABCDEF@invalid.example"
    )
    assert not module.is_managed_smoke_email("owner@example.com")
    assert not module.is_managed_smoke_email("smoke-a-manual@invalid.example")
    assert not module.is_managed_smoke_email(
        "media-smoke-20260903010101abcdef@invalid.example"
    )


def test_cleanup_requires_absolute_sqlite_database() -> None:
    module = _load_module()

    assert module.sqlite_path_from_url("sqlite:////var/lib/app.db").is_absolute()
    with pytest.raises(ValueError, match="absolute"):
        module.sqlite_path_from_url("sqlite:///relative.db")
    with pytest.raises(ValueError, match="SQLite"):
        module.sqlite_path_from_url("postgresql://db.example/app")


def test_cleanup_uses_staging_runtime_backup_directory() -> None:
    module = _load_module()

    assert Path("/var/lib/socialpilot-staging/backups") == module.DEFAULT_BACKUP_DIR


def test_cleanup_artifact_paths_cannot_escape_storage_root(tmp_path: Path) -> None:
    module = _load_module()
    root = tmp_path / "artifacts"
    root.mkdir()

    assert root / "task" / "clip.mp4" == module.safe_artifact_path(
        root, "task/clip.mp4"
    )
    with pytest.raises(ValueError, match="relative"):
        module.safe_artifact_path(root, str((tmp_path / "outside.mp4").resolve()))
    with pytest.raises(ValueError, match="escapes"):
        module.safe_artifact_path(root, "../outside.mp4")


def test_candidate_selection_applies_exact_pattern_and_minimum_age() -> None:
    module = _load_module()
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, created_at TEXT)"
    )
    now = datetime.now(UTC)
    connection.executemany(
        "INSERT INTO users (email, created_at) VALUES (?, ?)",
        (
            (
                "smoke-a-20260903010101abcdef@invalid.example",
                (now - timedelta(hours=1)).isoformat(),
            ),
            (
                "smoke-b-20260903010101abcdef@invalid.example",
                now.isoformat(),
            ),
            ("owner@example.com", (now - timedelta(days=1)).isoformat()),
        ),
    )

    selected = module.candidate_smoke_users(
        connection,
        older_than=now - timedelta(minutes=10),
    )

    assert [email for _user_id, email in selected] == [
        "smoke-a-20260903010101abcdef@invalid.example"
    ]


def test_candidate_artifact_records_use_physical_metadata_column() -> None:
    module = _load_module()
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE products (id INTEGER PRIMARY KEY, workspace_id INTEGER);
        CREATE TABLE video_projects (id INTEGER PRIMARY KEY, product_id INTEGER);
        CREATE TABLE video_render_tasks (
          id INTEGER PRIMARY KEY, video_project_id INTEGER
        );
        CREATE TABLE video_render_artifacts (
          id INTEGER PRIMARY KEY,
          video_render_task_id INTEGER,
          storage_path TEXT,
          metadata TEXT
        );
        INSERT INTO products VALUES (1, 10), (2, 20);
        INSERT INTO video_projects VALUES (1, 1), (2, 2);
        INSERT INTO video_render_tasks VALUES (1, 1), (2, 2);
        INSERT INTO video_render_artifacts VALUES
          (1, 1, 'task-1/clip.mp4', '{"sha256":"safe"}'),
          (2, 2, 'task-2/clip.mp4', '{}');
        """
    )

    assert module.candidate_artifact_records(connection, workspace_ids=[10]) == [
        ("task-1/clip.mp4", '{"sha256":"safe"}')
    ]
