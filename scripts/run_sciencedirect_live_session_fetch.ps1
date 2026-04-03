<#
.SYNOPSIS
Run the ScienceDirect live-session fetcher.

.DESCRIPTION
PowerShell wrapper around `sciencedirect_live_session_fetch.py` for serial official-PDF downloads
through an already authorized Edge remote-debugging session.

.PARAMETER InputCsv
Input CSV with ScienceDirect paper rows.

.PARAMETER OutDir
Output directory for raw run artifacts.

.PARAMETER PythonExe
Python executable to use.

.PARAMETER ScriptPath
Optional override for the Python entrypoint.

.PARAMETER DebugPort
Edge remote-debugging port.

.PARAMETER PrepareLogin
Open the three supported source pages and wait for manual login before starting the batch.

.PARAMETER LaunchEdgeIfMissing
Launch a dedicated Edge live session if none is listening on the requested debug port.

.PARAMETER WaitForUserLogin
Pause for the user to confirm the source logins are complete before downloads start.

.PARAMETER PrepareLoginsScriptPath
Optional override for the pre-login helper script.

.PARAMETER PageWaitSeconds
Seconds to wait after opening each tab.

.PARAMETER InterItemSleepSeconds
Seconds to sleep between rows.

.PARAMETER ViewerWsTimeoutSeconds
Seconds to keep waiting for the in-browser PDF viewer.

.PARAMETER Limit
Process only the first N rows.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$InputCsv,

    [Parameter(Mandatory = $true)]
    [string]$OutDir,

    [string]$PythonExe = "python",

    [string]$ScriptPath = "",

    [int]$DebugPort = 9222,

    [bool]$PrepareLogin = $true,

    [bool]$LaunchEdgeIfMissing = $true,

    [bool]$WaitForUserLogin = $true,

    [string]$PrepareLoginsScriptPath = "",

    [int]$PageWaitSeconds = 8,

    [int]$InterItemSleepSeconds = 5,

    [int]$ViewerWsTimeoutSeconds = 420,

    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $PSScriptRoot "sciencedirect_live_session_fetch.py"
}

if ([string]::IsNullOrWhiteSpace($PrepareLoginsScriptPath)) {
    $PrepareLoginsScriptPath = Join-Path $PSScriptRoot "prepare_live_session_logins.ps1"
}

if (-not (Test-Path -LiteralPath $InputCsv)) {
    throw "Input CSV not found: $InputCsv"
}

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

if ($PrepareLogin) {
    if (-not (Test-Path -LiteralPath $PrepareLoginsScriptPath)) {
        throw "Pre-login script not found: $PrepareLoginsScriptPath"
    }

    & $PrepareLoginsScriptPath `
        -DebugPort $DebugPort `
        -LaunchIfMissing $LaunchEdgeIfMissing `
        -WaitForUser $WaitForUserLogin
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$args = @(
    $ScriptPath,
    "--input-csv", $InputCsv,
    "--out-dir", $OutDir,
    "--debug-port", $DebugPort,
    "--page-wait-seconds", $PageWaitSeconds,
    "--inter-item-sleep-seconds", $InterItemSleepSeconds,
    "--viewer-ws-timeout-seconds", $ViewerWsTimeoutSeconds
)

if ($Limit -gt 0) {
    $args += @("--limit", $Limit)
}

& $PythonExe @args

Write-Host "Done. Output directory: $OutDir"
