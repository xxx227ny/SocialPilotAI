[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Read-PidDocument {
    param([string]$Path)
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-ProcessExited {
    param([int]$Id, [string]$Message)
    Assert-True ($null -eq (Get-Process -Id $Id -ErrorAction SilentlyContinue)) $Message
}

function Initialize-PreX2Database {
    param([string]$DatabasePath, [string]$BackendRoot)

    $pythonPath = Join-Path $BackendRoot ".venv\Scripts\python.exe"
    New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($DatabasePath)) -Force | Out-Null
    $setupCode = @'
import sqlite3
import sys
from pathlib import Path

from app.services.database_migration_service import PRE_X2_REVISION, _run_alembic

database = Path(sys.argv[1]).resolve()
_run_alembic(database, "upgrade", PRE_X2_REVISION)
connection = sqlite3.connect(database)
connection.execute(
    "INSERT INTO products (id, name, category, description, selling_points, target_markets, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    (1, "Pre-X2 Migration Marker", "Test", "Preserve this row", "[\"Preserved\"]", "[\"US\"]", "2026-08-09 00:00:00", "2026-08-09 00:00:00"),
)
connection.commit()
connection.close()
'@
    Push-Location $BackendRoot
    try {
        $setupCode | & $pythonPath - $DatabasePath
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to initialize temporary pre-X2 smoke database"
        }
    }
    finally {
        Pop-Location
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repositoryRoot "backend"
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("socialpilot-standalone-smoke-" + [Guid]::NewGuid().ToString("N"))
$legacyRuntimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("socialpilot-standalone-legacy-" + [Guid]::NewGuid().ToString("N"))
$failedRuntimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("socialpilot-standalone-failure-" + [Guid]::NewGuid().ToString("N"))
$lockedRuntimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("socialpilot-standalone-locked-" + [Guid]::NewGuid().ToString("N"))
$startScript = Join-Path $PSScriptRoot "start-socialpilotai.ps1"
$stopScript = Join-Path $PSScriptRoot "stop-socialpilotai.ps1"
$unrelated = $null
$recordedSleepers = @()

try {
    $unrelated = Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile",
        "-Command",
        "Start-Sleep -Seconds 180"
    ) -WindowStyle Hidden -PassThru

    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $pidPath = Join-Path $runtimeRoot "socialpilotai.pids.json"
    $databasePath = Join-Path $runtimeRoot "data\socialpilot.db"
    Assert-True (Test-Path -LiteralPath $pidPath -PathType Leaf) "PID file was not created"
    Assert-True (Test-Path -LiteralPath $databasePath -PathType Leaf) "Database was not initialized"
    Assert-True (Test-Path -LiteralPath (Join-Path $runtimeRoot "artifacts") -PathType Container) "Artifact directory was not created"
    $firstProcesses = Read-PidDocument $pidPath
    Assert-True ($null -ne (Get-Process -Id ([int]$firstProcesses.backend.pid) -ErrorAction SilentlyContinue)) "Backend did not start"
    Assert-True ($null -ne (Get-Process -Id ([int]$firstProcesses.frontend.pid) -ErrorAction SilentlyContinue)) "Frontend did not start"
    Assert-True ($null -ne (Get-Process -Id ([int]$firstProcesses.worker.pid) -ErrorAction SilentlyContinue)) "Execution Worker did not start"

    $products = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/products" -TimeoutSec 5
    $productCount = if ($null -eq $products) { 0 } else { @($products).Count }
    Assert-True ($productCount -eq 0) "Standalone startup loaded development seed data"
    $readiness = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/system/readiness" -TimeoutSec 5
    Assert-True ($readiness.provider_calls -eq 0) "Startup readiness resolved a Provider"
    Assert-True ($readiness.database_writes -eq 0) "Readiness wrote to the database"
    Assert-True ($readiness.database.revision_status -eq "head") "Fresh startup did not reach Alembic head"
    Assert-True ($readiness.database.revision -eq "0004_execution_queue") "Fresh startup reported the wrong revision"
    Assert-True ($readiness.execution_worker.ready) "Execution Worker readiness was not healthy"
    Assert-True ($readiness.execution_worker.status -eq "healthy") "Execution Worker status was not healthy"
    $emptyJobsBefore = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/execution-jobs" -TimeoutSec 5
    Start-Sleep -Seconds 3
    $emptyJobsAfter = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/execution-jobs" -TimeoutSec 5
    Assert-True (@($emptyJobsBefore).Count -eq 0 -and @($emptyJobsAfter).Count -eq 0) "Idle startup wrote ExecutionJob business data"
    $initialBackupPath = Join-Path $runtimeRoot "backups\database-migrations"
    Assert-True (@(Get-ChildItem -LiteralPath $initialBackupPath -File -ErrorAction SilentlyContinue).Count -eq 0) "Fresh startup created an unnecessary backup"

    $healthyBefore = Read-PidDocument $pidPath
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $healthyAfter = Read-PidDocument $pidPath
    Assert-True ($healthyAfter.backend.pid -eq $healthyBefore.backend.pid) "Healthy second start replaced the backend"
    Assert-True ($healthyAfter.frontend.pid -eq $healthyBefore.frontend.pid) "Healthy second start replaced the frontend"
    Assert-True ($healthyAfter.worker.pid -eq $healthyBefore.worker.pid) "Healthy second start replaced the Worker"

    $workerMissingBefore = Read-PidDocument $pidPath
    Stop-Process -Id ([int]$workerMissingBefore.worker.pid) -Force -ErrorAction Stop
    Wait-Process -Id ([int]$workerMissingBefore.worker.pid) -Timeout 5 -ErrorAction SilentlyContinue
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $workerMissingAfter = Read-PidDocument $pidPath
    Assert-True ($workerMissingAfter.backend.pid -eq $workerMissingBefore.backend.pid) "Worker recovery replaced healthy Backend"
    Assert-True ($workerMissingAfter.frontend.pid -eq $workerMissingBefore.frontend.pid) "Worker recovery replaced healthy Frontend"
    Assert-True ($workerMissingAfter.worker.pid -ne $workerMissingBefore.worker.pid) "Missing Worker was not recovered"

    $workerUnhealthyBefore = Read-PidDocument $pidPath
    $workerStatusPath = Join-Path $runtimeRoot "execution-worker.status.json"
    $staleWorkerStatus = Get-Content -LiteralPath $workerStatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $staleWorkerStatus.updated_at_utc = (Get-Date).ToUniversalTime().AddMinutes(-5).ToString("o")
    $staleWorkerStatus | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $workerStatusPath -Encoding UTF8
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $workerUnhealthyAfter = Read-PidDocument $pidPath
    Assert-ProcessExited ([int]$workerUnhealthyBefore.worker.pid) "Unhealthy Worker was not stopped"
    Assert-True ($workerUnhealthyAfter.backend.pid -eq $workerUnhealthyBefore.backend.pid) "Unhealthy Worker recovery replaced Backend"
    Assert-True ($workerUnhealthyAfter.frontend.pid -eq $workerUnhealthyBefore.frontend.pid) "Unhealthy Worker recovery replaced Frontend"
    Assert-True ($workerUnhealthyAfter.worker.pid -ne $workerUnhealthyBefore.worker.pid) "Unhealthy Worker was not replaced"

    $payload = @{
        name = "Standalone Persistence Check"
        category = "Test"
        description = "A local persistence record created without any Provider."
        selling_points = @("Persistent local record")
        target_markets = @("US")
    } | ConvertTo-Json
    $created = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/products" -ContentType "application/json" -Body $payload -TimeoutSec 5
    Assert-True ($created.name -eq "Standalone Persistence Check") "Persistence marker was not created"

    $beforeFirstStop = Read-PidDocument $pidPath
    & $stopScript -RuntimeRoot $runtimeRoot
    Assert-ProcessExited ([int]$beforeFirstStop.backend.pid) "Stop left Backend running"
    Assert-ProcessExited ([int]$beforeFirstStop.frontend.pid) "Stop left Frontend running"
    Assert-ProcessExited ([int]$beforeFirstStop.worker.pid) "Stop left Worker running"
    $headHashBefore = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash
    $headBackupsBefore = @(Get-ChildItem -LiteralPath $initialBackupPath -File -ErrorAction SilentlyContinue).Count
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $headBackupsAfter = @(Get-ChildItem -LiteralPath $initialBackupPath -File -ErrorAction SilentlyContinue).Count
    & $stopScript -RuntimeRoot $runtimeRoot
    $headHashAfter = (Get-FileHash -LiteralPath $databasePath -Algorithm SHA256).Hash
    Assert-True ($headHashAfter -eq $headHashBefore) "Head restart wrote to the database"
    Assert-True ($headBackupsAfter -eq $headBackupsBefore) "Head restart created another migration backup"
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60

    $backendOnlyBefore = Read-PidDocument $pidPath
    Stop-Process -Id ([int]$backendOnlyBefore.frontend.pid) -Force -ErrorAction Stop
    Wait-Process -Id ([int]$backendOnlyBefore.frontend.pid) -Timeout 5 -ErrorAction SilentlyContinue
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    Assert-ProcessExited ([int]$backendOnlyBefore.backend.pid) "Backend residue was not stopped before restart"
    Assert-ProcessExited ([int]$backendOnlyBefore.worker.pid) "Backend residue recovery did not stop Worker"
    $afterBackendResidue = Read-PidDocument $pidPath
    Assert-True ($afterBackendResidue.backend.pid -ne $backendOnlyBefore.backend.pid) "Backend residue was reused"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Backend-residue recovery stopped an unrelated process"

    $frontendOnlyBefore = Read-PidDocument $pidPath
    Stop-Process -Id ([int]$frontendOnlyBefore.backend.pid) -Force -ErrorAction Stop
    Wait-Process -Id ([int]$frontendOnlyBefore.backend.pid) -Timeout 5 -ErrorAction SilentlyContinue
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    Assert-ProcessExited ([int]$frontendOnlyBefore.frontend.pid) "Frontend residue was not stopped before restart"
    Assert-ProcessExited ([int]$frontendOnlyBefore.worker.pid) "Frontend residue recovery did not stop Worker"
    $afterFrontendResidue = Read-PidDocument $pidPath
    Assert-True ($afterFrontendResidue.frontend.pid -ne $frontendOnlyBefore.frontend.pid) "Frontend residue was reused"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Frontend-residue recovery stopped an unrelated process"

    & $stopScript -RuntimeRoot $runtimeRoot
    $dummyBackend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 180") -WindowStyle Hidden -PassThru
    $dummyFrontend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 180") -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 250
    $dummyBackend = Get-Process -Id $dummyBackend.Id -ErrorAction Stop
    $dummyFrontend = Get-Process -Id $dummyFrontend.Id -ErrorAction Stop
    $recordedSleepers = @($dummyBackend, $dummyFrontend)
    $unhealthyDocument = [ordered]@{
        backend = [ordered]@{
            pid = $dummyBackend.Id
            executable = $dummyBackend.Path
            started_at_utc = $dummyBackend.StartTime.ToUniversalTime().ToString("o")
        }
        frontend = [ordered]@{
            pid = $dummyFrontend.Id
            executable = $dummyFrontend.Path
            started_at_utc = $dummyFrontend.StartTime.ToUniversalTime().ToString("o")
        }
    }
    $unhealthyDocument | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $pidPath -Encoding UTF8
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    Assert-ProcessExited $dummyBackend.Id "Unhealthy recorded backend was not stopped"
    Assert-ProcessExited $dummyFrontend.Id "Unhealthy recorded frontend was not stopped"
    $recordedSleepers = @()
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Unhealthy-pair recovery stopped an unrelated process"

    & $stopScript -RuntimeRoot $runtimeRoot
    $expiredDocument = [ordered]@{
        backend = [ordered]@{
            pid = 2147483001
            executable = $repositoryRoot
            started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        }
        frontend = [ordered]@{
            pid = 2147483002
            executable = $repositoryRoot
            started_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        }
    }
    $expiredDocument | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $pidPath -Encoding UTF8
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $afterExpiredPid = Read-PidDocument $pidPath
    Assert-True ($afterExpiredPid.backend.pid -ne 2147483001) "Expired backend PID was retained"
    Assert-True ($afterExpiredPid.frontend.pid -ne 2147483002) "Expired frontend PID was retained"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Expired-PID recovery stopped an unrelated process"

    $productsAfterRestart = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/products" -TimeoutSec 5
    $productCountAfterRestart = if ($null -eq $productsAfterRestart) { 0 } else { @($productsAfterRestart).Count }
    Assert-True ($productCountAfterRestart -eq 1) "Second startup did not preserve the database"
    Assert-True ($productsAfterRestart[0].name -eq "Standalone Persistence Check") "Second startup replaced persisted data"

    $logs = Get-Content -Path (Join-Path $runtimeRoot "logs\*.stdout.log") -ErrorAction Stop
    $providerOperations = @($logs | Select-String -Pattern "/execute", "render-execution", "live-render", "social-accounts/youtube/connect", "/publish")
    Assert-True ($providerOperations.Count -eq 0) "Startup issued a Provider operation request"

    & $stopScript -RuntimeRoot $runtimeRoot
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Second stop terminated an unrelated process"

    $legacyDatabase = Join-Path $legacyRuntimeRoot "data\socialpilot.db"
    Initialize-PreX2Database -DatabasePath $legacyDatabase -BackendRoot $backendRoot
    $legacyHashBefore = (Get-FileHash -LiteralPath $legacyDatabase -Algorithm SHA256).Hash
    & $startScript -RuntimeRoot $legacyRuntimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    $legacyProducts = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/products" -TimeoutSec 5
    Assert-True (@($legacyProducts).Count -eq 1) "Pre-X2 migration lost Product data"
    Assert-True ($legacyProducts[0].id -eq 1) "Pre-X2 migration changed Product identity"
    $legacyReadiness = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/system/readiness" -TimeoutSec 5
    Assert-True ($legacyReadiness.database.revision_status -eq "head") "Pre-X2 migration did not reach head"
    $legacyBackups = Join-Path $legacyRuntimeRoot "backups\database-migrations"
    Assert-True (@(Get-ChildItem -LiteralPath $legacyBackups -Filter "*.db" -File).Count -eq 1) "Pre-X2 migration did not create exactly one backup"
    Assert-True (@(Get-ChildItem -LiteralPath $legacyBackups -Filter "*.manifest.json" -File).Count -eq 1) "Pre-X2 migration did not create exactly one manifest"
    Assert-True ((Get-FileHash -LiteralPath (Get-ChildItem -LiteralPath $legacyBackups -Filter "*.db" -File).FullName -Algorithm SHA256).Hash -eq $legacyHashBefore) "Pre-X2 backup is not byte exact"
    & $stopScript -RuntimeRoot $legacyRuntimeRoot

    $failedDatabase = Join-Path $failedRuntimeRoot "data\socialpilot.db"
    Initialize-PreX2Database -DatabasePath $failedDatabase -BackendRoot $backendRoot
    $blockedBackupParent = Join-Path $failedRuntimeRoot "backups"
    New-Item -ItemType Directory -Path $blockedBackupParent -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $blockedBackupParent "database-migrations") -Value "intentional smoke obstruction" -Encoding UTF8
    $migrationFailed = $false
    try {
        & $startScript -RuntimeRoot $failedRuntimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    }
    catch {
        $migrationFailed = $true
    }
    Assert-True $migrationFailed "Injected migration failure did not stop startup"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $failedRuntimeRoot "socialpilotai.pids.json"))) "Migration failure started a service"

    $lockedDatabase = Join-Path $lockedRuntimeRoot "data\socialpilot.db"
    Initialize-PreX2Database -DatabasePath $lockedDatabase -BackendRoot $backendRoot
    $unknownLock = "$lockedDatabase.migration.lock"
    Set-Content -LiteralPath $unknownLock -Value '{"token":"unknown-smoke-owner"}' -Encoding UTF8
    $lockRejected = $false
    try {
        & $startScript -RuntimeRoot $lockedRuntimeRoot -NoBrowser -DisableDotenv -StartupTimeoutSeconds 60
    }
    catch {
        $lockRejected = $true
    }
    Assert-True $lockRejected "Unknown migration lock did not stop startup"
    Assert-True (Test-Path -LiteralPath $unknownLock -PathType Leaf) "Unknown migration lock was deleted"
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $lockedRuntimeRoot "socialpilotai.pids.json"))) "Lock conflict started a service"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Migration safety checks stopped an unrelated process"

    Write-Host "Standalone runtime smoke passed: fresh migration, pre-X2 preservation, head idempotency, safe failures, exact PID isolation, zero Provider operations."
}
finally {
    foreach ($temporaryRuntime in @($runtimeRoot, $legacyRuntimeRoot, $failedRuntimeRoot, $lockedRuntimeRoot)) {
        if (Test-Path -LiteralPath (Join-Path $temporaryRuntime "socialpilotai.pids.json")) {
            & $stopScript -RuntimeRoot $temporaryRuntime -ErrorAction SilentlyContinue
        }
    }
    if ($null -ne $unrelated) {
        Stop-Process -Id $unrelated.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($sleeper in $recordedSleepers) {
        Stop-Process -Id $sleeper.Id -Force -ErrorAction SilentlyContinue
    }
    $expectedParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\")
    foreach ($temporaryRuntime in @($runtimeRoot, $legacyRuntimeRoot, $failedRuntimeRoot, $lockedRuntimeRoot)) {
        if (Test-Path -LiteralPath $temporaryRuntime) {
            $resolved = (Resolve-Path -LiteralPath $temporaryRuntime).Path
            if ([System.IO.Directory]::GetParent($resolved).FullName.TrimEnd("\") -eq $expectedParent) {
                Remove-Item -LiteralPath $resolved -Recurse -Force
            }
        }
    }
}
