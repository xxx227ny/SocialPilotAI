[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$python = Join-Path $backendRoot ".venv\Scripts\python.exe"
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$temporaryParent = Join-Path $repoRoot "tmp"
$temporaryRoot = Join-Path $temporaryParent (
    "validation-" + [System.Guid]::NewGuid().ToString("N")
)

function Assert-ExitCode([string]$Label) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python environment is missing: backend/.venv"
}

[System.IO.Directory]::CreateDirectory($temporaryRoot) | Out-Null
try {
    Push-Location $backendRoot
    try {
        & $python -c "import pydantic_settings, pytest, ruff"
        Assert-ExitCode "Backend dependency precheck"

        & $python -m pytest -q --basetemp (Join-Path $temporaryRoot "pytest")
        Assert-ExitCode "Backend test suite"

        & $python -m ruff check --no-cache .
        Assert-ExitCode "Backend lint"

        $changed = @(
            git -C $repoRoot diff --name-only --diff-filter=ACMR HEAD -- backend
            git -C $repoRoot ls-files --others --exclude-standard -- backend
        ) | Where-Object {
            $_ -match '^backend/.+\.py$'
        } | Sort-Object -Unique
        Assert-ExitCode "Changed Python file discovery"
        if ($changed.Count -gt 0) {
            $backendRelative = @(
                $changed | ForEach-Object {
                    $_.Substring("backend/".Length).Replace("/", "\")
                }
            )
            & $python -m ruff format --check --no-cache @backendRelative
            Assert-ExitCode "Changed Python format check"
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $frontendRoot
    try {
        $package = Get-Content -Raw -Encoding UTF8 "package.json" | ConvertFrom-Json
        $seenCommands = [System.Collections.Generic.HashSet[string]]::new()
        $testScripts = @(
            $package.scripts.PSObject.Properties | Where-Object {
                $_.Name -like "test:*" -and
                $_.Name -notlike "*live*" -and
                $_.Name -notlike "*smoke*" -and
                $seenCommands.Add([string]$_.Value)
            } | ForEach-Object { $_.Name }
        ) | Sort-Object
        foreach ($testScript in $testScripts) {
            & $npm run $testScript
            Assert-ExitCode "Frontend $testScript"
        }
        & $npm run build
        Assert-ExitCode "Frontend production build"
    }
    finally {
        Pop-Location
    }

    git -C $repoRoot diff --check
    Assert-ExitCode "Git whitespace check"
    Write-Host "SocialPilotAI quality gate passed without Provider calls."
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        $resolvedTemporary = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $resolvedParent = [System.IO.Directory]::GetParent($resolvedTemporary).FullName
        $expectedParent = [System.IO.Path]::GetFullPath($temporaryParent)
        $leaf = [System.IO.Path]::GetFileName($resolvedTemporary)
        if (
            $resolvedParent -eq $expectedParent -and
            $leaf.StartsWith("validation-", [System.StringComparison]::Ordinal)
        ) {
            Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
        }
    }
}
