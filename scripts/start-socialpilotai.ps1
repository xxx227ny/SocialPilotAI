[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA "SocialPilotAI"),
    [switch]$NoBrowser,
    [switch]$DisableDotenv,
    [ValidateRange(10, 300)]
    [int]$StartupTimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-VerifiedRecordedProcess {
    param([Parameter(Mandatory = $true)]$Record)

    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    try {
        $actualPath = [System.IO.Path]::GetFullPath($process.Path)
        $expectedPath = [System.IO.Path]::GetFullPath([string]$Record.executable)
        $actualStart = $process.StartTime.ToUniversalTime()
        $expectedStart = [DateTime]::Parse(
            [string]$Record.started_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        if (
            $actualPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase) -and
            [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -lt 2
        ) {
            return $process
        }
    }
    catch {
        return $null
    }
    return $null
}

function Stop-VerifiedRecordedProcesses {
    param([Parameter(Mandatory = $true)][array]$Targets)

    foreach ($target in $Targets) {
        Stop-Process -Id $target.process.Id -ErrorAction Stop
    }
    foreach ($target in $Targets) {
        try {
            Wait-Process -Id $target.process.Id -Timeout 10 -ErrorAction Stop
        }
        catch {
            $stillRunning = Get-Process -Id $target.process.Id -ErrorAction SilentlyContinue
            if ($null -ne $stillRunning) {
                Stop-Process -Id $target.process.Id -Force -ErrorAction Stop
                Wait-Process -Id $target.process.Id -Timeout 5 -ErrorAction SilentlyContinue
            }
        }
        Write-Host "Stopped stale $($target.name) PID $($target.process.Id)."
    }
}

function Test-HttpHealthy {
    param([Parameter(Mandatory = $true)][string]$Uri)

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Open-ProductCenter {
    Start-Process "http://127.0.0.1:5173/products"
}

function Normalize-ProcessPathEnvironment {
    $pathKeys = @(
        [Environment]::GetEnvironmentVariables().Keys |
            Where-Object { $_ -ieq "path" }
    )
    if ($pathKeys.Count -le 1) {
        return
    }
    $selectedPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $selectedPath, "Process")
}

function Assert-PortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($null -ne $listener) {
        throw "Port $Port is already in use. Stop that application or run stop-socialpilotai.cmd if it belongs to SocialPilotAI."
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][DateTime]$Deadline
    )

    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ((Get-Date) -lt $Deadline)
    throw "Timed out waiting for $Uri"
}

function Get-DatabaseMigrationStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Backend,
        [Parameter(Mandatory = $true)][string]$Database
    )

    Push-Location $Backend
    try {
        $statusOutput = & $Python -m app.cli.database_migrations status --database $Database
        if ($LASTEXITCODE -ne 0) {
            throw "Database safety status could not be determined. No services were started."
        }
    }
    finally {
        Pop-Location
    }
    try {
        return ($statusOutput -join "`n") | ConvertFrom-Json
    }
    catch {
        throw "Database safety status was invalid. No services were started."
    }
}

function Invoke-SafeDatabaseUpgrade {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Backend,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$BackupDirectory
    )

    Push-Location $Backend
    try {
        & $Python -m app.cli.database_migrations upgrade --database $Database --backup-dir $BackupDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "Database migration failed safely. No services were started; verified backups and manifests were preserved."
        }
    }
    finally {
        Pop-Location
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repositoryRoot "backend"
$frontendRoot = Join-Path $repositoryRoot "frontend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"
$viteScript = Join-Path $frontendRoot "node_modules\vite\bin\vite.js"
$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Backend runtime is missing. Run the README one-time installation steps first."
}
if ($null -eq $nodeCommand -or -not (Test-Path -LiteralPath $viteScript -PathType Leaf)) {
    throw "Frontend runtime is missing. Install Node.js and run npm install in the frontend directory first."
}
$nodePath = [System.IO.Path]::GetFullPath($nodeCommand.Source)
$quotedViteScript = '"' + $viteScript + '"'
Normalize-ProcessPathEnvironment

$runtimePath = [System.IO.Path]::GetFullPath($RuntimeRoot)
$dataPath = Join-Path $runtimePath "data"
$artifactPath = Join-Path $runtimePath "artifacts"
$logPath = Join-Path $runtimePath "logs"
$pidPath = Join-Path $runtimePath "socialpilotai.pids.json"
$databasePath = Join-Path $dataPath "socialpilot.db"
$migrationBackupPath = Join-Path $runtimePath "backups\database-migrations"

New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
New-Item -ItemType Directory -Path $artifactPath -Force | Out-Null
New-Item -ItemType Directory -Path $logPath -Force | Out-Null

if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $existing = $null
    try {
        $existing = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Write-Host "The existing PID file is invalid; no unverified process was stopped."
    }
    if ($null -ne $existing) {
        $verified = @()
        foreach ($record in @(
            [pscustomobject]@{ name = "backend"; value = $existing.backend },
            [pscustomobject]@{ name = "frontend"; value = $existing.frontend }
        )) {
            $process = Get-VerifiedRecordedProcess $record.value
            if ($null -ne $process) {
                $verified += [pscustomobject]@{ name = $record.name; process = $process }
            }
        }

        if ($verified.Count -eq 2) {
            $backendHealthy = Test-HttpHealthy "http://127.0.0.1:8000/api/v1/health"
            $frontendHealthy = Test-HttpHealthy "http://127.0.0.1:5173/products"
            if ($backendHealthy -and $frontendHealthy) {
                Write-Host "SocialPilotAI is already running."
                Write-Host "Product Center: http://127.0.0.1:5173/products"
                if (-not $NoBrowser) {
                    Open-ProductCenter
                }
                exit 0
            }
            Write-Host "Recorded services are not healthy. Restarting both services."
            Stop-VerifiedRecordedProcesses $verified
        }
        elseif ($verified.Count -eq 1) {
            Write-Host "A partial SocialPilotAI service was found. Restarting both services."
            Stop-VerifiedRecordedProcesses $verified
        }
        else {
            Write-Host "Removing an expired SocialPilotAI PID file."
        }
    }
    Remove-Item -LiteralPath $pidPath -Force
}

Assert-PortAvailable 8000
Assert-PortAvailable 5173

$migrationStatus = Get-DatabaseMigrationStatus -Python $pythonPath -Backend $backendRoot -Database $databasePath
if ($migrationStatus.state -eq "head" -and $migrationStatus.ready) {
    Write-Host "Database migration status: verified Alembic head."
}
elseif ($migrationStatus.upgrade_required) {
    Write-Host "Database migration is required. Creating a verified backup when applicable."
    Invoke-SafeDatabaseUpgrade -Python $pythonPath -Backend $backendRoot -Database $databasePath -BackupDirectory $migrationBackupPath
    $migrationStatus = Get-DatabaseMigrationStatus -Python $pythonPath -Backend $backendRoot -Database $databasePath
    if ($migrationStatus.state -ne "head" -or -not $migrationStatus.ready) {
        throw "Database did not reach the verified Alembic head. No services were started."
    }
    Write-Host "Database migration completed at the verified Alembic head."
}
elseif ($migrationStatus.state -eq "locked") {
    throw "Database migration is locked by another operation. No services were started; the unknown lock was preserved."
}
else {
    throw "Database schema is not compatible with this SocialPilotAI version. No services were started; existing data was preserved."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backendOut = Join-Path $logPath "backend-$timestamp.stdout.log"
$backendErr = Join-Path $logPath "backend-$timestamp.stderr.log"
$frontendOut = Join-Path $logPath "frontend-$timestamp.stdout.log"
$frontendErr = Join-Path $logPath "frontend-$timestamp.stderr.log"
$sqlitePath = $databasePath.Replace("\", "/")

# The standalone process loads backend/.env internally. Explicit process values
# select the persistent runtime and keep startup free of development seed data.
$env:SOCIALPILOT_DISABLE_DOTENV = if ($DisableDotenv) { "1" } else { "0" }
$env:APP_ENVIRONMENT = "standalone"
$env:DATABASE_URL = "sqlite:///$sqlitePath"
$env:VIDEO_ARTIFACT_STORAGE_ROOT = $artifactPath
$env:ENABLE_STRATEGY_EXECUTION = "true"
$env:ENABLE_COPY_EXECUTION = "true"
$env:ENABLE_V2_COPY_EXECUTION = "false"
$env:ENABLE_VIDEO_PROJECT_EXECUTION = "true"
$env:ENABLE_V2_VIDEO_PROJECT_EXECUTION = "false"
$env:ENABLE_VIDEO_RENDER_EXECUTION = "true"
$env:ENABLE_GROWTH_EXECUTION = "false"
$env:ENABLE_LIVE_WANX_DEMO = "false"
$env:ENABLE_SOCIAL_ACCOUNT_BINDING = "true"
$env:ENABLE_YOUTUBE_PUBLISHING = "true"

$backend = $null
$frontend = $null
try {
    $backendParameters = @{
        FilePath = $pythonPath
        ArgumentList = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
        WorkingDirectory = $backendRoot
        RedirectStandardOutput = $backendOut
        RedirectStandardError = $backendErr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $backend = Start-Process @backendParameters

    $env:VITE_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
    $env:VITE_ENABLE_STRATEGY_EXECUTION = "true"
    $env:VITE_ENABLE_COPY_EXECUTION = "true"
    $env:VITE_ENABLE_V2_COPY_EXECUTION = "false"
    $env:VITE_ENABLE_VIDEO_PROJECT_EXECUTION = "true"
    $env:VITE_ENABLE_V2_VIDEO_PROJECT_EXECUTION = "false"
    $env:VITE_ENABLE_VIDEO_RENDER_EXECUTION = "true"
    $env:VITE_ENABLE_GROWTH_EXECUTION = "false"
    $env:VITE_ENABLE_SOCIAL_ACCOUNT_BINDING = "true"
    $env:VITE_ENABLE_YOUTUBE_PUBLISHING = "true"

    $frontendParameters = @{
        FilePath = $nodePath
        ArgumentList = @($quotedViteScript, "--host", "127.0.0.1", "--port", "5173")
        WorkingDirectory = $frontendRoot
        RedirectStandardOutput = $frontendOut
        RedirectStandardError = $frontendErr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $frontend = Start-Process @frontendParameters

    $pidDocument = [ordered]@{
        version = 1
        repository_root = $repositoryRoot
        runtime_root = $runtimePath
        database = $databasePath
        artifacts = $artifactPath
        backend = [ordered]@{
            pid = $backend.Id
            executable = $pythonPath
            started_at_utc = $backend.StartTime.ToUniversalTime().ToString("o")
            stdout_log = $backendOut
            stderr_log = $backendErr
        }
        frontend = [ordered]@{
            pid = $frontend.Id
            executable = $nodePath
            started_at_utc = $frontend.StartTime.ToUniversalTime().ToString("o")
            stdout_log = $frontendOut
            stderr_log = $frontendErr
        }
    }
    $pidTemp = "$pidPath.tmp"
    $pidDocument | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pidTemp -Encoding UTF8
    Move-Item -LiteralPath $pidTemp -Destination $pidPath -Force

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    Wait-HttpReady "http://127.0.0.1:8000/api/v1/health" $deadline
    Wait-HttpReady "http://127.0.0.1:5173/products" $deadline

    $readiness = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/system/readiness" -TimeoutSec 5
    Write-Host "SocialPilotAI is ready."
    Write-Host "Product Center: http://127.0.0.1:5173/products"
    Write-Host "Runtime data: $runtimePath"
    Write-Host "Backend ready: $($readiness.backend.ready)"
    Write-Host "Qwen ready: $($readiness.qwen.ready)"
    Write-Host "Wanx ready: $($readiness.wanx.ready)"
    Write-Host "Google/YouTube ready: $($readiness.google_youtube.ready)"
    if (-not $NoBrowser) {
        Open-ProductCenter
    }
}
catch {
    foreach ($process in @($frontend, $backend)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    throw
}
