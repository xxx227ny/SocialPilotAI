from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import GrowthAutomationControl
from app.services.database_migration_service import (
    HEAD_REVISION,
    get_database_migration_status,
)
from app.services.growth_automation_service import GrowthAutomationService


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one due growth-monitoring pass without a resident loop"
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--once", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database = args.database.resolve()
    status = get_database_migration_status(database)
    if not status.ready or status.revision != HEAD_REVISION:
        print(json.dumps({"status": "DATABASE_NOT_READY", "processed": 0}))
        return 2
    engine = create_engine(
        f"sqlite:///{database.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    counts: dict[str, int] = {}
    processed = 0
    try:
        with factory() as session:
            product_ids = list(
                session.scalars(
                    select(GrowthAutomationControl.product_id)
                    .where(GrowthAutomationControl.monitoring_enabled.is_(True))
                    .order_by(GrowthAutomationControl.product_id.asc())
                ).all()
            )
        for product_id in product_ids:
            with factory() as session:
                result = GrowthAutomationService(session).run_cycle(product_id)
                if result.cycle is None:
                    continue
                processed += 1
                counts[result.cycle.status] = counts.get(result.cycle.status, 0) + 1
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "processed": processed,
                "cycle_status_counts": counts,
                "provider_calls": 0,
                "external_mutations": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
