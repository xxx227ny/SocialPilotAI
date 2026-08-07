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
    assert "Provider" not in script.replace(
        '"http://127.0.0.1:8000/api/v1/system/readiness"', ""
    )
    assert "C:\\Users\\" not in script


def test_stop_launcher_verifies_exact_pid_path_and_start_time() -> None:
    script = read("scripts/stop-socialpilotai.ps1")
    assert "Get-Process -Id" in script
    assert "Record.executable" in script
    assert "Record.started_at_utc" in script
    assert "Stop-Process -Id $target.process.Id" in script
    assert "Get-NetTCPConnection" not in script
    assert "Get-Process -Name" not in script
    assert "taskkill" not in script.casefold()
    assert "C:\\Users\\" not in script


def test_start_launcher_recovers_each_recorded_process_state_safely() -> None:
    script = read("scripts/start-socialpilotai.ps1")
    assert "Get-VerifiedRecordedProcess" in script
    assert "Record.executable" in script
    assert "Record.started_at_utc" in script
    assert "if ($verified.Count -eq 2)" in script
    assert "$backendHealthy -and $frontendHealthy" in script
    assert "Recorded services are not healthy" in script
    assert "elseif ($verified.Count -eq 1)" in script
    assert "A partial SocialPilotAI service was found" in script
    assert "Removing an expired SocialPilotAI PID file" in script
    assert "Stop-VerifiedRecordedProcesses $verified" in script
    assert "Get-Process -Name" not in script
    assert "taskkill" not in script.casefold()


def test_healthy_second_start_keeps_services_and_can_open_product_center() -> None:
    script = read("scripts/start-socialpilotai.ps1")
    healthy = script.index("if ($backendHealthy -and $frontendHealthy)")
    already_running = script.index('Write-Host "SocialPilotAI is already running."')
    browser_guard = script.index("if (-not $NoBrowser)", already_running)
    browser_open = script.index("Open-ProductCenter", browser_guard)
    early_exit = script.index("exit 0", browser_open)
    restart = script.index("Stop-VerifiedRecordedProcesses $verified", early_exit)
    assert (
        healthy
        < already_running
        < browser_guard
        < browser_open
        < early_exit
        < restart
    )


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
