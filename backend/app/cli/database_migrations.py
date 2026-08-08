from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.database_migration_service import (
    restore_backup,
    upgrade_sqlite_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely upgrade or restore a local SocialPilot SQLite database."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("--database", type=Path, required=True)
    upgrade.add_argument("--backup-dir", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--destination", type=Path)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.command == "upgrade":
        result = upgrade_sqlite_database(arguments.database, arguments.backup_dir)
        print(
            json.dumps(
                {
                    "previous_revision": result.previous_revision,
                    "current_revision": result.current_revision,
                    "schema_state": result.schema_state,
                    "backup_created": result.backup_manifest_path is not None,
                },
                sort_keys=True,
            )
        )
        return
    restore_backup(arguments.manifest, destination=arguments.destination)
    print(json.dumps({"restored": True}))


if __name__ == "__main__":
    main()
