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

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("socialpilot-standalone-smoke-" + [Guid]::NewGuid().ToString("N"))
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

    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
    $pidPath = Join-Path $runtimeRoot "socialpilotai.pids.json"
    $databasePath = Join-Path $runtimeRoot "data\socialpilot.db"
    Assert-True (Test-Path -LiteralPath $pidPath -PathType Leaf) "PID file was not created"
    Assert-True (Test-Path -LiteralPath $databasePath -PathType Leaf) "Database was not initialized"
    Assert-True (Test-Path -LiteralPath (Join-Path $runtimeRoot "artifacts") -PathType Container) "Artifact directory was not created"

    $products = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/products" -TimeoutSec 5
    $productCount = if ($null -eq $products) { 0 } else { @($products).Count }
    Assert-True ($productCount -eq 0) "Standalone startup loaded development seed data"
    $readiness = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/system/readiness" -TimeoutSec 5
    Assert-True ($readiness.provider_calls -eq 0) "Startup readiness resolved a Provider"
    Assert-True ($readiness.database_writes -eq 0) "Readiness wrote to the database"

    $healthyBefore = Read-PidDocument $pidPath
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
    $healthyAfter = Read-PidDocument $pidPath
    Assert-True ($healthyAfter.backend.pid -eq $healthyBefore.backend.pid) "Healthy second start replaced the backend"
    Assert-True ($healthyAfter.frontend.pid -eq $healthyBefore.frontend.pid) "Healthy second start replaced the frontend"

    $payload = @{
        name = "Standalone Persistence Check"
        category = "Test"
        description = "A local persistence record created without any Provider."
        selling_points = @("Persistent local record")
        target_markets = @("US")
    } | ConvertTo-Json
    $created = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/products" -ContentType "application/json" -Body $payload -TimeoutSec 5
    Assert-True ($created.name -eq "Standalone Persistence Check") "Persistence marker was not created"

    $backendOnlyBefore = Read-PidDocument $pidPath
    Stop-Process -Id ([int]$backendOnlyBefore.frontend.pid) -Force -ErrorAction Stop
    Wait-Process -Id ([int]$backendOnlyBefore.frontend.pid) -Timeout 5 -ErrorAction SilentlyContinue
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
    Assert-ProcessExited ([int]$backendOnlyBefore.backend.pid) "Backend residue was not stopped before restart"
    $afterBackendResidue = Read-PidDocument $pidPath
    Assert-True ($afterBackendResidue.backend.pid -ne $backendOnlyBefore.backend.pid) "Backend residue was reused"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Backend-residue recovery stopped an unrelated process"

    $frontendOnlyBefore = Read-PidDocument $pidPath
    Stop-Process -Id ([int]$frontendOnlyBefore.backend.pid) -Force -ErrorAction Stop
    Wait-Process -Id ([int]$frontendOnlyBefore.backend.pid) -Timeout 5 -ErrorAction SilentlyContinue
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
    Assert-ProcessExited ([int]$frontendOnlyBefore.frontend.pid) "Frontend residue was not stopped before restart"
    $afterFrontendResidue = Read-PidDocument $pidPath
    Assert-True ($afterFrontendResidue.frontend.pid -ne $frontendOnlyBefore.frontend.pid) "Frontend residue was reused"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Frontend-residue recovery stopped an unrelated process"

    & $stopScript -RuntimeRoot $runtimeRoot
    $dummyBackend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 180") -WindowStyle Hidden -PassThru
    $dummyFrontend = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 180") -WindowStyle Hidden -PassThru
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
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
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
    & $startScript -RuntimeRoot $runtimeRoot -NoBrowser -StartupTimeoutSeconds 60
    $afterExpiredPid = Read-PidDocument $pidPath
    Assert-True ($afterExpiredPid.backend.pid -ne 2147483001) "Expired backend PID was retained"
    Assert-True ($afterExpiredPid.frontend.pid -ne 2147483002) "Expired frontend PID was retained"
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Expired-PID recovery stopped an unrelated process"

    $productsAfterRestart = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/products" -TimeoutSec 5
    $productCountAfterRestart = if ($null -eq $productsAfterRestart) { 0 } else { @($productsAfterRestart).Count }
    Assert-True ($productCountAfterRestart -eq 1) "Second startup did not preserve the database"
    Assert-True ($productsAfterRestart[0].name -eq "Standalone Persistence Check") "Second startup replaced persisted data"

    $logs = Get-Content -Path (Join-Path $runtimeRoot "logs\backend-*.stdout.log") -ErrorAction Stop
    $providerOperations = @($logs | Select-String -Pattern "/execute", "render-execution", "live-render", "social-accounts/youtube/connect", "/publish")
    Assert-True ($providerOperations.Count -eq 0) "Startup issued a Provider operation request"

    & $stopScript -RuntimeRoot $runtimeRoot
    Assert-True ($null -ne (Get-Process -Id $unrelated.Id -ErrorAction SilentlyContinue)) "Second stop terminated an unrelated process"
    Write-Host "Standalone runtime smoke passed: initialization, persistence, no seed, zero Provider operations, exact PID stop."
}
finally {
    if (Test-Path -LiteralPath (Join-Path $runtimeRoot "socialpilotai.pids.json")) {
        & $stopScript -RuntimeRoot $runtimeRoot -ErrorAction SilentlyContinue
    }
    if ($null -ne $unrelated) {
        Stop-Process -Id $unrelated.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($sleeper in $recordedSleepers) {
        Stop-Process -Id $sleeper.Id -Force -ErrorAction SilentlyContinue
    }
    $expectedParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd("\")
    if (Test-Path -LiteralPath $runtimeRoot) {
        $resolved = (Resolve-Path -LiteralPath $runtimeRoot).Path
        if ([System.IO.Directory]::GetParent($resolved).FullName.TrimEnd("\") -eq $expectedParent) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
