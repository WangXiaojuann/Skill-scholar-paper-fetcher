<#
.SYNOPSIS
Run the JSTOR live-session fetcher.

.DESCRIPTION
PowerShell wrapper around `jstor_live_session_fetch.py` for serial official-PDF downloads
through an already authorized Edge remote-debugging session.

.PARAMETER InputCsv
Input CSV with JSTOR citation rows.

.PARAMETER OutDir
Output directory for raw run artifacts.

.PARAMETER PythonExe
Python executable to use.

.PARAMETER ScriptPath
Optional override for the Python entrypoint.

.PARAMETER DebugPort
Edge remote-debugging port.

.PARAMETER PageWaitSeconds
Seconds to wait after opening each search tab.

.PARAMETER InterItemSleepSeconds
Seconds to sleep between rows.

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

    [int]$PageWaitSeconds = 10,

    [int]$InterItemSleepSeconds = 3,

    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $PSScriptRoot "jstor_live_session_fetch.py"
}

if (-not (Test-Path -LiteralPath $InputCsv)) {
    throw "Input CSV not found: $InputCsv"
}

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$args = @(
    $ScriptPath,
    "--input-csv", $InputCsv,
    "--out-dir", $OutDir,
    "--debug-port", $DebugPort,
    "--page-wait-seconds", $PageWaitSeconds,
    "--inter-item-sleep-seconds", $InterItemSleepSeconds
)

if ($Limit -gt 0) {
    $args += @("--limit", $Limit)
}

& $PythonExe @args

Write-Host "Done. Output directory: $OutDir"
