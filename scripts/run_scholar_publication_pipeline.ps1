<#
.SYNOPSIS
Run the scholar publication pipeline wrapper.

.DESCRIPTION
Thin PowerShell wrapper around `scholar_publication_pipeline.py`. Pass a subcommand such as
`init-run`, `import-records`, `build-queues`, `ingest-results`, or `extract-reference-text`
followed by its normal Python arguments.

.PARAMETER PythonExe
Python executable to use.

.PARAMETER ScriptPath
Optional override for the Python entrypoint.

.PARAMETER RemainingArgs
Subcommand and arguments forwarded to the Python entrypoint.
#>
param(
    [string]$PythonExe = "python",

    [string]$ScriptPath = "",

    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
    $ScriptPath = Join-Path $PSScriptRoot "scholar_publication_pipeline.py"
}

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

& $PythonExe $ScriptPath @RemainingArgs
