<#
.SYNOPSIS
Open the three supported source pages in the shared Edge live session and pause for manual login.

.DESCRIPTION
Ensures the Edge remote-debugging session exists, opens ScienceDirect, Wiley, and JSTOR in that
same session, and waits for the user to finish login or institution-access setup before downloads
begin.

.PARAMETER DebugPort
Edge remote-debugging port.

.PARAMETER EdgeBinary
Path to the Edge executable when a new live session must be launched.

.PARAMETER CloneUserDataDir
User-data directory for the dedicated Edge session when a new session must be launched.

.PARAMETER ProfileDirectory
Edge profile directory inside the user-data directory.

.PARAMETER LaunchIfMissing
Launch a dedicated Edge live session if no debugger is listening on the requested port.

.PARAMETER WaitForUser
Pause and wait for the user to confirm the logins are complete before returning control.

.PARAMETER StartupTimeoutSeconds
How long to wait for the Edge DevTools endpoint to come up after launching Edge.
#>
param(
    [int]$DebugPort = 9222,
    [string]$EdgeBinary = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    [string]$CloneUserDataDir = "",
    [string]$ProfileDirectory = "Default",
    [bool]$LaunchIfMissing = $true,
    [bool]$WaitForUser = $true,
    [int]$StartupTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$loginTargets = @(
    @{ Name = "ScienceDirect / Elsevier"; Url = "https://www.sciencedirect.com/" },
    @{ Name = "Wiley"; Url = "https://onlinelibrary.wiley.com/" },
    @{ Name = "JSTOR"; Url = "https://www.jstor.org/" }
)
$targetsToOpen = $loginTargets

function Test-DebugEndpoint {
    param(
        [int]$Port
    )

    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-DebugEndpoint {
    param(
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DebugEndpoint -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return $false
}

function Open-LiveSessionPage {
    param(
        [int]$Port,
        [string]$Url
    )

    $encodedUrl = [System.Uri]::EscapeDataString($Url)
    Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/new?$encodedUrl" -Method Put -TimeoutSec 20 | Out-Null
}

if (-not (Test-DebugEndpoint -Port $DebugPort)) {
    if (-not $LaunchIfMissing) {
        throw "No Edge live session is listening on port $DebugPort."
    }

    $launchScript = Join-Path $PSScriptRoot "launch_edge_live_session.ps1"
    if (-not (Test-Path -LiteralPath $launchScript)) {
        throw "Launch script not found: $launchScript"
    }

    & $launchScript `
        -EdgeBinary $EdgeBinary `
        -CloneUserDataDir $CloneUserDataDir `
        -ProfileDirectory $ProfileDirectory `
        -RemoteDebuggingPort $DebugPort `
        -Url $loginTargets[0].Url

    if (-not (Wait-DebugEndpoint -Port $DebugPort -TimeoutSeconds $StartupTimeoutSeconds)) {
        throw "Edge DevTools endpoint did not come up on port $DebugPort within $StartupTimeoutSeconds seconds."
    }

    if ($loginTargets.Count -gt 1) {
        $targetsToOpen = $loginTargets[1..($loginTargets.Count - 1)]
    } else {
        $targetsToOpen = @()
    }
} else {
    Write-Host "Reusing Edge live session on port $DebugPort."
}

foreach ($target in $targetsToOpen) {
    Open-LiveSessionPage -Port $DebugPort -Url $target.Url
    Write-Host ("Opened source page: {0} -> {1}" -f $target.Name, $target.Url)
    Start-Sleep -Milliseconds 400
}

Write-Host ""
Write-Host "Complete the login or access flow in the same Edge window for these sources:"
foreach ($target in $loginTargets) {
    Write-Host ("- {0}" -f $target.Name)
}
Write-Host "- Finish any institution or personal sign-in flow that the site requires."
Write-Host "- If a site still needs one extra click on a representative article PDF, do that before continuing."
Write-Host "- Keep the Edge window open while the download script runs."
Write-Host ""

if ($WaitForUser) {
    Read-Host "Press Enter after the source logins are complete" | Out-Null
} else {
    Write-Host "WaitForUser is false; continuing without an interactive pause."
}
