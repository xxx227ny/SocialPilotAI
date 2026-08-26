from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_start_launcher_uses_persistent_runtime_and_consistent_gates() -> None:
    script = read("scripts/start-socialpilotai.ps1")
    assert "$env:LOCALAPPDATA" in script
    assert '"SocialPilotAI"' in script
    assert 'APP_ENVIRONMENT = "standalone"' in script
    assert 'DATABASE_URL = "sqlite:///$sqlitePath"' in script
    assert '"artifacts"' in script
    assert '"logs"' in script
    assert '"socialpilotai.pids.json"' in script
    assert '"execution-worker.status.json"' in script
    assert '"execution-worker.stop"' in script
    assert '"-m", "app.cli.execution_worker"' in script
    assert "EXECUTION_WORKER_STATUS_FILE" in script
    for backend, frontend in (
        ("ENABLE_STRATEGY_EXECUTION", "VITE_ENABLE_STRATEGY_EXECUTION"),
        ("ENABLE_COPY_EXECUTION", "VITE_ENABLE_COPY_EXECUTION"),
        (
            "ENABLE_VIDEO_PROJECT_EXECUTION",
            "VITE_ENABLE_VIDEO_PROJECT_EXECUTION",
        ),
        (
            "ENABLE_VIDEO_RENDER_EXECUTION",
            "VITE_ENABLE_VIDEO_RENDER_EXECUTION",
        ),
        (
            "ENABLE_SOCIAL_ACCOUNT_BINDING",
            "VITE_ENABLE_SOCIAL_ACCOUNT_BINDING",
        ),
        ("ENABLE_YOUTUBE_PUBLISHING", "VITE_ENABLE_YOUTUBE_PUBLISHING"),
    ):
        assert f'$env:{backend} = "true"' in script
        assert f'$env:{frontend} = "true"' in script
    assert '$env:ENABLE_LIVE_WANX_DEMO = "false"' in script
    assert "seed_development_data" not in script
    for secret_name in (
        "QWEN_API_KEY",
        "WANX_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEMO_AUTH_PASSWORD_HASH",
        "DEMO_AUTH_SESSION_SECRET",
    ):
        assert secret_name not in script
    assert "C:\\Users\\" not in script


def test_stop_launcher_verifies_exact_pid_path_and_start_time() -> None:
    script = read("scripts/stop-socialpilotai.ps1")
    assert "Get-Process -Id" in script
    assert "Record.executable" in script
    assert "Record.started_at_utc" in script
    assert "Stop-Process -Id $target.process.Id" in script
    assert 'name = "worker"' in script
    assert 'Set-Content -LiteralPath ([string]$stopFileProperty.Value)' in script
    assert "Get-NetTCPConnection" not in script
    assert "Get-Process -Name" not in script
    assert "taskkill" not in script.casefold()
    assert "C:\\Users\\" not in script


def test_start_launcher_recovers_each_recorded_process_state_safely() -> None:
    script = read("scripts/start-socialpilotai.ps1")
    assert "Get-VerifiedRecordedProcess" in script
    assert "Record.executable" in script
    assert "Record.started_at_utc" in script
    assert "$backendHealthy -and $frontendHealthy -and $workerHealthy" in script
    assert "Recovering only the recorded Worker" in script
    assert "Recorded services are partial or unhealthy" in script
    assert "Removing an expired SocialPilotAI PID file" in script
    assert "Stop-VerifiedRecordedProcesses -Targets $verified" in script
    assert "Get-Process -Name" not in script
    assert "taskkill" not in script.casefold()


def test_healthy_second_start_keeps_services_and_can_open_product_center() -> None:
    script = read("scripts/start-socialpilotai.ps1")
    healthy = script.index(
        "if ($backendHealthy -and $frontendHealthy -and $workerHealthy"
    )
    already_running = script.index('Write-Host "SocialPilotAI is already running."')
    browser_guard = script.index("if (-not $NoBrowser)", already_running)
    browser_open = script.index("Open-ProductCenter", browser_guard)
    early_exit = script.index("exit 0", browser_open)
    restart = script.index("Recovering only the recorded Worker", early_exit)
    assert (
        healthy
        < already_running
        < browser_guard
        < browser_open
        < early_exit
        < restart
    )


def test_launcher_migrates_before_starting_services_and_preserves_failures(
) -> None:
    script = read("scripts/start-socialpilotai.ps1")
    status = script.index("Get-DatabaseMigrationStatus -Python")
    upgrade = script.index("Invoke-SafeDatabaseUpgrade -Python")
    verified_head = script.index(
        'Write-Host "Database migration completed at the verified Alembic head."'
    )
    backend_start = script.index("$backend = Start-Process")
    frontend_start = script.index("$frontend = Start-Process")
    worker_start = script.index("$worker = Start-Process")
    assert (
        status
        < upgrade
        < verified_head
        < worker_start
        < backend_start
        < frontend_start
    )
    assert '"backups\\database-migrations"' in script
    assert "unknown lock was preserved" in script
    assert "No services were started" in script
    assert "Normalize-ProcessPathEnvironment" in script
    assert "Get-Process -Name" not in script


def test_production_lifespan_does_not_create_schema_with_metadata() -> None:
    main = read("backend/app/main.py")
    initialization = read("backend/app/db/init_db.py")
    production = main + initialization
    assert "create_all" not in production
    assert "init_db()" not in production
    assert "seed_development_data()" in main


def test_cmd_wrappers_only_delegate_to_repository_scripts() -> None:
    start = read("start-socialpilotai.cmd")
    stop = read("stop-socialpilotai.cmd")
    assert "%~dp0scripts\\start-socialpilotai.ps1" in start
    assert "%~dp0scripts\\stop-socialpilotai.ps1" in stop
    assert "git " not in (start + stop).casefold()
    for wrapper in (start, stop):
        assert 'set "exitCode=%ERRORLEVEL%"' in wrapper
        assert 'if not "%exitCode%"=="0"' in wrapper
        assert "pause" in wrapper.casefold()
        assert "Review the error above" in wrapper
        assert "secret values" in wrapper
