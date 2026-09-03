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
