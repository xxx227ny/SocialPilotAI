import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.database_migration_service import HEAD_REVISION, _run_alembic


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_state(
    path: Path,
    expected: str,
    timeout: float = 8,
    process: subprocess.Popen[str] | None = None,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("state") == expected:
                return payload
        if process is not None and process.poll() is not None:
            raise AssertionError(
                f"Worker exited with code {process.returncode} before reporting "
                f"{expected}"
            )
        time.sleep(0.05)
    raise AssertionError(f"Worker did not report {expected}")


def assert_worker_output_is_credential_safe(
    output: str,
    *,
    sensitive_values: tuple[str, ...],
    database_path: Path,
) -> None:
    normalized = output.casefold()
    for sensitive in sensitive_values:
        assert sensitive.casefold() not in normalized
    assert str(database_path).casefold() not in normalized
    assert "database_url" not in normalized
    assert "socialpilot_disable_dotenv" not in normalized
    for pattern in (
        r"authorization\s*:\s*bearer\s+\S+",
        r"(?:access|refresh)[_-]?token\s*[:=]\s*[^\s,;}]+",
        r"client[_-]?secret\s*[:=]\s*[^\s,;}]+",
        r"authorization[_-]?code\s*[:=]\s*[^\s,;}]+",
        r"cookie\s*[:=]\s*[^\s,;}]+",
        r"payload\s*[:=]\s*[^\s,;}]+",
    ):
        assert re.search(pattern, output, flags=re.IGNORECASE) is None


@pytest.mark.parametrize(
    "leaked_output",
    [
        "fake-worker-access-token",
        "fake-worker-refresh-token",
        "fake-worker-client-secret",
        "fake-worker-authorization-code",
        "Authorization: Bearer suspicious-value",
        "access_token=suspicious-value",
        "refresh-token: suspicious-value",
        "client_secret=suspicious-value",
        "authorization_code=suspicious-value",
    ],
)
def test_worker_output_safety_check_detects_credentials(
    leaked_output: str, tmp_path: Path
) -> None:
    with pytest.raises(AssertionError):
        assert_worker_output_is_credential_safe(
            leaked_output,
            sensitive_values=(
                "fake-worker-access-token",
                "fake-worker-refresh-token",
                "fake-worker-client-secret",
                "fake-worker-authorization-code",
            ),
            database_path=tmp_path / "worker.db",
        )


def test_worker_output_safety_check_allows_tiktok_migration_identifier(
    tmp_path: Path,
) -> None:
    assert_worker_output_is_credential_safe(
        "Running upgrade to 0007_tiktok_refresh_token_expiry",
        sensitive_values=(
            "fake-worker-access-token",
            "fake-worker-refresh-token",
            "fake-worker-client-secret",
            "fake-worker-authorization-code",
        ),
        database_path=tmp_path / "worker.db",
    )


def test_worker_cli_idles_updates_status_and_stops_without_database_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "worker.db"
    status = tmp_path / "worker.status.json"
    stop = tmp_path / "worker.stop"
    _run_alembic(database, "upgrade", HEAD_REVISION)
    before_hash = file_hash(database)
    environment = os.environ.copy()
    environment["SOCIALPILOT_DISABLE_DOTENV"] = "1"
    sensitive_values = (
        "fake-worker-access-token",
        "fake-worker-refresh-token",
        "fake-worker-client-secret",
        "fake-worker-authorization-code",
    )
    environment["TIKTOK_ACCESS_TOKEN"] = sensitive_values[0]
    environment["TIKTOK_REFRESH_TOKEN"] = sensitive_values[1]
    environment["TIKTOK_CLIENT_SECRET"] = sensitive_values[2]
    environment["TIKTOK_AUTHORIZATION_CODE"] = sensitive_values[3]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.cli.execution_worker",
            "--database",
            str(database),
            "--status-file",
            str(status),
            "--stop-file",
            str(stop),
            "--instance-id",
            "test-worker-instance-0001",
            "--poll-seconds",
            "0.25",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        first = wait_for_state(status, "healthy", timeout=30, process=process)
        time.sleep(0.4)
        second = wait_for_state(status, "healthy")
        assert second["updated_at_utc"] >= first["updated_at_utc"]
        stop.write_text("stop", encoding="ascii")
        stdout, stderr = process.communicate(timeout=8)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
    stopped = wait_for_state(status, "stopped")
    assert isinstance(stopped["pid"], int) and stopped["pid"] > 0
    assert not stop.exists()
    assert file_hash(database) == before_hash
    output = f"{stdout}\n{stderr}"
    assert "0007_tiktok_refresh_token_expiry" in output
    assert_worker_output_is_credential_safe(
        output,
        sensitive_values=sensitive_values,
        database_path=database,
    )


def test_worker_cli_refuses_database_before_head(tmp_path: Path) -> None:
    database = tmp_path / "unversioned.db"
    database.touch()
    status = tmp_path / "status.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli.execution_worker",
            "--database",
            str(database),
            "--status-file",
            str(status),
            "--stop-file",
            str(tmp_path / "stop"),
            "--instance-id",
            "test-worker-instance-0002",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert not status.exists()
