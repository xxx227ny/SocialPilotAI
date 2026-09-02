from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.execution.runtime_registry import build_execution_handler_registry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.services.database_migration_service import (
    HEAD_REVISION,
    get_database_migration_status,
)
from app.services.provider_credential_service import ProviderCredentialService


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _write_status(path: Path, state: str, instance_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "state": state,
        "pid": os.getpid(),
        "instance_id": instance_id,
        "updated_at_utc": _utc_now(),
    }
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(0.02)


def _database_is_at_head(database: Path) -> bool:
    status = get_database_migration_status(database)
    return bool(status.ready and status.revision == HEAD_REVISION)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local execution worker")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--lease-seconds", type=int, default=30)
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    if not 0.25 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.25 and 60")
    if not 16 <= len(args.instance_id) <= 128:
        parser.error("--instance-id must be between 16 and 128 characters")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    database = args.database.resolve()
    status_file = args.status_file.resolve()
    stop_file = args.stop_file.resolve()
    if not _database_is_at_head(database):
        print("Execution worker refused to start: database is not at Alembic head.")
        return 2

    sqlite_path = database.as_posix()
    engine = create_engine(
        f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False}
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    worker_identity = hashlib.sha256(
        f"standalone-worker:{os.getpid()}:{_utc_now()}".encode()
    ).hexdigest()
    worker = ExecutionWorker(
        session_factory=session_factory,
        registry=build_execution_handler_registry(
            session_factory=session_factory,
            settings=settings,
        ),
        worker_id=worker_identity,
        lease_seconds=args.lease_seconds,
        heartbeat_interval_seconds=args.heartbeat_seconds,
        workspace_credential_resolver=(
            lambda workspace_id: (
                _workspace_credential(session_factory, settings, workspace_id)
                if settings.enable_user_auth
                else None
            )
        ),
    )
    shutdown = Event()

    def request_stop(*_: object) -> None:
        shutdown.set()
        worker.stop()

    for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        candidate = getattr(signal, signal_name, None)
        if candidate is not None:
            signal.signal(candidate, request_stop)

    def watch_stop_file() -> None:
        while not shutdown.wait(0.25):
            if stop_file.is_file():
                request_stop()
                return

    stop_watcher = Thread(
        target=watch_stop_file,
        name="execution-worker-stop-watcher",
        daemon=False,
    )
    try:
        stop_file.unlink(missing_ok=True)
        _write_status(status_file, "healthy", args.instance_id)
        stop_watcher.start()
        while not shutdown.is_set():
            result = worker.run_once()
            _write_status(status_file, "healthy", args.instance_id)
            if result.status == WorkerRunStatus.STOPPED:
                break
            if result.status == WorkerRunStatus.NO_JOB:
                shutdown.wait(args.poll_seconds)
    finally:
        request_stop()
        if stop_watcher.is_alive():
            stop_watcher.join(timeout=2)
        _write_status(status_file, "stopped", args.instance_id)
        stop_file.unlink(missing_ok=True)
        engine.dispose()
    return 0


def _workspace_credential(
    session_factory,
    app_settings,
    workspace_id: int | None,
) -> str | None:
    if not app_settings.enable_user_auth or workspace_id is None:
        return None
    with session_factory() as session:
        return ProviderCredentialService(
            session, app_settings
        ).read_verified_dashscope_key(workspace_id)


if __name__ == "__main__":
    sys.exit(main())
