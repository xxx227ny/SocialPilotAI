"""Back up staging SQLite and remove expired tokens or managed smoke users."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/socialpilot-staging/runtime.json")
DEFAULT_BACKUP_DIR = Path("/var/lib/socialpilot-staging/backups")
SMOKE_EMAIL_PATTERN = re.compile(
    r"^smoke-[ab]-[0-9]{14}[0-9a-f]{6}@invalid\.example$"
)


def is_managed_smoke_email(email: str) -> bool:
    return SMOKE_EMAIL_PATTERN.fullmatch(email.strip().casefold()) is not None


def sqlite_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:////"):
        raise ValueError("Cleanup supports only an absolute local SQLite database")
    path = Path(database_url.removeprefix("sqlite://"))
    if not path.is_absolute():
        raise ValueError("Cleanup requires an absolute SQLite database path")
    return path


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def candidate_smoke_users(
    connection: sqlite3.Connection,
    *,
    older_than: datetime,
) -> list[tuple[int, str]]:
    candidates = []
    for user_id, email, created_at in connection.execute(
        "SELECT id, email, created_at FROM users ORDER BY id"
    ):
        if is_managed_smoke_email(email) and parse_datetime(created_at) <= older_than:
            candidates.append((int(user_id), str(email)))
    return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Safely purge invalid account tokens and optionally the exact smoke "
            "accounts created by deploy/staging/smoke_test.py. Dry-run is default."
        )
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--minimum-smoke-age-minutes", type=int, default=10)
    parser.add_argument("--include-smoke-users", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.minimum_smoke_age_minutes < 1:
        raise SystemExit("Minimum smoke-account age must be at least one minute")
    loaded = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit("Runtime configuration must be a JSON object")
    database_path = sqlite_path_from_url(str(loaded.get("DATABASE_URL", "")))
    if not database_path.is_file():
        raise SystemExit(f"Database does not exist: {database_path}")

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=args.minimum_smoke_age_minutes)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        invalid_tokens = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM account_action_tokens
                WHERE expires_at <= CURRENT_TIMESTAMP
                   OR consumed_at <= datetime('now', '-7 days')
                """
            ).fetchone()[0]
        )
        candidates = (
            candidate_smoke_users(connection, older_than=cutoff)
            if args.include_smoke_users
            else []
        )
        print(f"Invalid account tokens: {invalid_tokens}")
        print(f"Managed smoke users: {len(candidates)}")
        if not args.apply:
            print("Dry-run only; no data changed.")
            return

        args.backup_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        backup = args.backup_dir / f"socialpilot-pre-account-cleanup-{stamp}.db"
        backup_connection = sqlite3.connect(backup)
        try:
            connection.backup(backup_connection)
        finally:
            backup_connection.close()
        shutil.copymode(database_path, backup)

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            DELETE FROM account_action_tokens
            WHERE expires_at <= CURRENT_TIMESTAMP
               OR consumed_at <= datetime('now', '-7 days')
            """
        )
        if candidates:
            user_ids = [user_id for user_id, _email in candidates]
            placeholders = ",".join("?" for _ in user_ids)
            workspace_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT workspace_id FROM memberships "
                    f"WHERE user_id IN ({placeholders})",
                    user_ids,
                )
            ]
            if workspace_ids:
                workspace_placeholders = ",".join("?" for _ in workspace_ids)
                connection.execute(
                    f"DELETE FROM workspaces WHERE id IN ({workspace_placeholders})",
                    workspace_ids,
                )
            connection.execute(
                f"DELETE FROM users WHERE id IN ({placeholders})",
                user_ids,
            )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("Foreign-key check failed; cleanup rolled back")
        connection.commit()
        print(f"Cleanup complete. Rollback database: {backup}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
