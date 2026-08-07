[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA "SocialPilotAI")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-VerifiedProcess {
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
    }
    catch {
        throw "PID $($Record.pid) could not be verified and was not stopped."
    }
    if (
        -not $actualPath.Equals($expectedPath, [StringComparison]::OrdinalIgnoreCase) -or
        [Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -ge 2
    ) {
        throw "PID $($Record.pid) no longer matches the recorded SocialPilotAI process and was not stopped."
    }
    return $process
}

$runtimePath = [System.IO.Path]::GetFullPath($RuntimeRoot)
$pidPath = Join-Path $runtimePath "socialpilotai.pids.json"
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    Write-Host "SocialPilotAI is not running: no PID file was found."
    exit 0
}

$document = Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8 | ConvertFrom-Json
$targets = @(
    [pscustomobject]@{ name = "frontend"; record = $document.frontend },
    [pscustomobject]@{ name = "backend"; record = $document.backend }
)
$verified = @()
foreach ($target in $targets) {
    $process = Get-VerifiedProcess $target.record
    if ($null -ne $process) {
        $verified += [pscustomobject]@{ name = $target.name; process = $process }
    }
}

foreach ($target in $verified) {
    Stop-Process -Id $target.process.Id -ErrorAction Stop
}
foreach ($target in $verified) {
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
    Write-Host "Stopped $($target.name) PID $($target.process.Id)."
}

Remove-Item -LiteralPath $pidPath -Force
Write-Host "SocialPilotAI is stopped. Persistent database, artifacts, and logs were preserved."
