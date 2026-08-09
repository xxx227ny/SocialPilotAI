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
    param(
        [Parameter(Mandatory = $true)][array]$Targets,
        [string]$WorkerStopFile
    )

    foreach ($target in $Targets) {
        if ($target.name -eq "worker" -and $WorkerStopFile) {
            Set-Content -LiteralPath $WorkerStopFile -Value "stop" -Encoding ASCII
        }
        else {
            Stop-Process -Id $target.process.Id -ErrorAction Stop
        }
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

function Get-OptionalRecord {
    param($Document, [Parameter(Mandatory = $true)][string]$Name)
    $property = $Document.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Test-WorkerHealthy {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$StatusFile,
        [Parameter(Mandatory = $true)][string]$InstanceId
    )
    if (-not (Test-Path -LiteralPath $StatusFile -PathType Leaf)) { return $false }
    try {
        $status = Get-Content -LiteralPath $StatusFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $updated = [DateTime]::Parse(
            [string]$status.updated_at_utc,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
        $age = ((Get-Date).ToUniversalTime() - $updated).TotalSeconds
        return (
            $status.state -eq "healthy" -and
            [string]$status.instance_id -eq $InstanceId -and
            $age -ge -5 -and $age -le 15
        )
    }
    catch { return $false }
}

function Wait-WorkerReady {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$StatusFile,
        [Parameter(Mandatory = $true)][string]$InstanceId,
        [Parameter(Mandatory = $true)][DateTime]$Deadline
    )
    do {
        if ($Process.HasExited) { throw "Execution Worker exited during startup." }
        if (Test-WorkerHealthy -Process $Process -StatusFile $StatusFile -InstanceId $InstanceId) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $Deadline)
    throw "Timed out waiting for the Execution Worker heartbeat."
}

function Test-HttpHealthy {
    param([Parameter(Mandatory = $true)][string]$Uri)

    foreach ($attempt in 1..3) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        }
        catch {
            if ($attempt -lt 3) { Start-Sleep -Milliseconds 250 }
        }
    }
    return $false
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
$workerStatusPath = Join-Path $runtimePath "execution-worker.status.json"
$workerStopPath = Join-Path $runtimePath "execution-worker.stop"
$databasePath = Join-Path $dataPath "socialpilot.db"
$migrationBackupPath = Join-Path $runtimePath "backups\database-migrations"

New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
New-Item -ItemType Directory -Path $artifactPath -Force | Out-Null
New-Item -ItemType Directory -Path $logPath -Force | Out-Null

$recoverWorkerOnly = $false
$preservedBackendRecord = $null
$preservedFrontendRecord = $null
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
            [pscustomobject]@{ name = "backend"; value = (Get-OptionalRecord $existing "backend") },
            [pscustomobject]@{ name = "frontend"; value = (Get-OptionalRecord $existing "frontend") },
            [pscustomobject]@{ name = "worker"; value = (Get-OptionalRecord $existing "worker") }
        )) {
            if ($null -eq $record.value) { continue }
            $process = Get-VerifiedRecordedProcess $record.value
            if ($null -ne $process) {
                $verified += [pscustomobject]@{ name = $record.name; process = $process }
            }
        }

        $verifiedBackend = @($verified | Where-Object name -eq "backend")
        $verifiedFrontend = @($verified | Where-Object name -eq "frontend")
        $verifiedWorker = @($verified | Where-Object name -eq "worker")
        $backendHealthy = $verifiedBackend.Count -eq 1 -and (Test-HttpHealthy "http://127.0.0.1:8000/api/v1/health")
        $frontendHealthy = $verifiedFrontend.Count -eq 1 -and (Test-HttpHealthy "http://127.0.0.1:5173/products")
        $workerRecord = Get-OptionalRecord $existing "worker"
        $workerInstanceProperty = if ($null -ne $workerRecord) { $workerRecord.PSObject.Properties["instance_id"] } else { $null }
        $workerInstance = if ($null -ne $workerInstanceProperty) { [string]$workerInstanceProperty.Value } else { "" }
        $workerHealthy = $verifiedWorker.Count -eq 1 -and $workerInstance -and (Test-WorkerHealthy -Process $verifiedWorker[0].process -StatusFile $workerStatusPath -InstanceId $workerInstance)
        $pidVersion = if ($null -ne $existing.PSObject.Properties["version"]) { [int]$existing.version } else { 1 }
        Write-Host "Recorded health: Backend=$backendHealthy Frontend=$frontendHealthy Worker=$workerHealthy."

        if ($backendHealthy -and $frontendHealthy -and $workerHealthy -and $pidVersion -eq 2) {
                Write-Host "SocialPilotAI is already running."
                Write-Host "Product Center: http://127.0.0.1:5173/products"
                if (-not $NoBrowser) {
                    Open-ProductCenter
                }
                exit 0
        }
        elseif ($backendHealthy -and $frontendHealthy -and $pidVersion -eq 2) {
            Write-Host "Execution Worker is missing or unhealthy. Recovering only the recorded Worker."
            if ($verifiedWorker.Count -eq 1) {
                Stop-VerifiedRecordedProcesses -Targets $verifiedWorker -WorkerStopFile $workerStopPath
            }
            $recoverWorkerOnly = $true
            $preservedBackendRecord = $existing.backend
            $preservedFrontendRecord = $existing.frontend
        }
        else {
            if ($verified.Count -gt 0) {
                Write-Host "Recorded services are partial or unhealthy. Restarting the verified SocialPilotAI processes."
                Stop-VerifiedRecordedProcesses -Targets $verified -WorkerStopFile $workerStopPath
            }
            else {
                Write-Host "Removing an expired SocialPilotAI PID file."
            }
        }
    }
    Remove-Item -LiteralPath $pidPath -Force
}

if (-not $recoverWorkerOnly) {
    Assert-PortAvailable 8000
    Assert-PortAvailable 5173
}

$migrationStatus = Get-DatabaseMigrationStatus -Python $pythonPath -Backend $backendRoot -Database $databasePath
if ($migrationStatus.state -eq "head" -and $migrationStatus.ready) {
    Write-Host "Database migration status: verified Alembic head."
}
elseif ($migrationStatus.upgrade_required) {
    if ($recoverWorkerOnly) {
        $preserved = @(
            [pscustomobject]@{ name = "backend"; process = (Get-VerifiedRecordedProcess $preservedBackendRecord) },
            [pscustomobject]@{ name = "frontend"; process = (Get-VerifiedRecordedProcess $preservedFrontendRecord) }
        ) | Where-Object { $null -ne $_.process }
        Stop-VerifiedRecordedProcesses -Targets $preserved -WorkerStopFile $workerStopPath
        $recoverWorkerOnly = $false
        Assert-PortAvailable 8000
        Assert-PortAvailable 5173
    }
    Write-Host "Database migration is required. Creating a verified backup when applicable."
    Invoke-SafeDatabaseUpgrade -Python $pythonPath -Backend $backendRoot -Database $databasePath -BackupDirectory $migrationBackupPath
    $migrationStatus = Get-DatabaseMigrationStatus -Python $pythonPath -Backend $backendRoot -Database $databasePath
    if ($migrationStatus.state -ne "head" -or -not $migrationStatus.ready) {
        throw "Database did not reach the verified Alembic head. No services were started."
    }
    Write-Host "Database migration completed at the verified Alembic head."
}
elseif ($migrationStatus.state -eq "locked") {
    if ($recoverWorkerOnly) {
        $preserved = @(
            [pscustomobject]@{ name = "backend"; process = (Get-VerifiedRecordedProcess $preservedBackendRecord) },
            [pscustomobject]@{ name = "frontend"; process = (Get-VerifiedRecordedProcess $preservedFrontendRecord) }
        ) | Where-Object { $null -ne $_.process }
        Stop-VerifiedRecordedProcesses -Targets $preserved -WorkerStopFile $workerStopPath
    }
    throw "Database migration is locked by another operation. No services were started; the unknown lock was preserved."
}
else {
    if ($recoverWorkerOnly) {
        $preserved = @(
            [pscustomobject]@{ name = "backend"; process = (Get-VerifiedRecordedProcess $preservedBackendRecord) },
            [pscustomobject]@{ name = "frontend"; process = (Get-VerifiedRecordedProcess $preservedFrontendRecord) }
        ) | Where-Object { $null -ne $_.process }
        Stop-VerifiedRecordedProcesses -Targets $preserved -WorkerStopFile $workerStopPath
    }
    throw "Database schema is not compatible with this SocialPilotAI version. No services were started; existing data was preserved."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backendOut = Join-Path $logPath "backend-$timestamp.stdout.log"
$backendErr = Join-Path $logPath "backend-$timestamp.stderr.log"
$frontendOut = Join-Path $logPath "frontend-$timestamp.stdout.log"
$frontendErr = Join-Path $logPath "frontend-$timestamp.stderr.log"
$workerOut = Join-Path $logPath "worker-$timestamp.stdout.log"
$workerErr = Join-Path $logPath "worker-$timestamp.stderr.log"
$sqlitePath = $databasePath.Replace("\", "/")

# The standalone process loads backend/.env internally. Explicit process values
# select the persistent runtime and keep startup free of development seed data.
$env:SOCIALPILOT_DISABLE_DOTENV = if ($DisableDotenv) { "1" } else { "0" }
$env:APP_ENVIRONMENT = "standalone"
$env:DATABASE_URL = "sqlite:///$sqlitePath"
$env:VIDEO_ARTIFACT_STORAGE_ROOT = $artifactPath
$env:EXECUTION_WORKER_STATUS_FILE = $workerStatusPath
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
$worker = $null
try {
    Remove-Item -LiteralPath $workerStopPath -Force -ErrorAction SilentlyContinue
    $workerInstance = [Guid]::NewGuid().ToString("N")
    $workerParameters = @{
        FilePath = $pythonPath
        ArgumentList = @(
            "-m", "app.cli.execution_worker",
            "--database", $databasePath,
            "--status-file", $workerStatusPath,
            "--stop-file", $workerStopPath,
            "--instance-id", $workerInstance,
            "--poll-seconds", "2"
        )
        WorkingDirectory = $backendRoot
        RedirectStandardOutput = $workerOut
        RedirectStandardError = $workerErr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $worker = Start-Process @workerParameters
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    Wait-WorkerReady -Process $worker -StatusFile $workerStatusPath -InstanceId $workerInstance -Deadline $deadline

    if (-not $recoverWorkerOnly) {
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
    }

    $backendRecord = if ($recoverWorkerOnly) { $preservedBackendRecord } else { [ordered]@{
        pid = $backend.Id
        executable = $pythonPath
        started_at_utc = $backend.StartTime.ToUniversalTime().ToString("o")
        stdout_log = $backendOut
        stderr_log = $backendErr
    } }
    $frontendRecord = if ($recoverWorkerOnly) { $preservedFrontendRecord } else { [ordered]@{
        pid = $frontend.Id
        executable = $nodePath
        started_at_utc = $frontend.StartTime.ToUniversalTime().ToString("o")
        stdout_log = $frontendOut
        stderr_log = $frontendErr
    } }

    $pidDocument = [ordered]@{
        version = 2
        repository_root = $repositoryRoot
        runtime_root = $runtimePath
        database = $databasePath
        artifacts = $artifactPath
        backend = $backendRecord
        frontend = $frontendRecord
        worker = [ordered]@{
            pid = $worker.Id
            executable = $pythonPath
            started_at_utc = $worker.StartTime.ToUniversalTime().ToString("o")
            stdout_log = $workerOut
            stderr_log = $workerErr
            status_file = $workerStatusPath
            stop_file = $workerStopPath
            instance_id = $workerInstance
        }
    }
    $pidTemp = "$pidPath.tmp"
    $pidDocument | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $pidTemp -Encoding UTF8
    Move-Item -LiteralPath $pidTemp -Destination $pidPath -Force

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
    Write-Host "Execution Worker ready: $($readiness.execution_worker.ready)"
    if (-not $NoBrowser) {
        Open-ProductCenter
    }
}
catch {
    foreach ($process in @($frontend, $backend, $worker)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if ($recoverWorkerOnly) {
        $preserved = @(
            [pscustomobject]@{ name = "backend"; process = (Get-VerifiedRecordedProcess $preservedBackendRecord) },
            [pscustomobject]@{ name = "frontend"; process = (Get-VerifiedRecordedProcess $preservedFrontendRecord) }
        ) | Where-Object { $null -ne $_.process }
        Stop-VerifiedRecordedProcesses -Targets $preserved -WorkerStopFile $workerStopPath
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    throw
}
