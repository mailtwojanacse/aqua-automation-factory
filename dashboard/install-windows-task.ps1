<#
.SYNOPSIS
    Registers the Aqua Automation Factory dashboard as a Windows Scheduled
    Task so it starts automatically and restarts itself if it crashes -
    the Windows equivalent of aqua-dashboard.service (systemd) on Linux.

.DESCRIPTION
    Unlike the systemd unit file, this script needs no manual path editing
    - it detects its own location ($PSScriptRoot) and points the task at
    run-dashboard.bat next to it, so it works unmodified wherever this
    repo is cloned.

    Runs the task under YOUR OWN Windows account at logon (not as SYSTEM
    at boot) - deliberately, not an oversight: `gh auth login` and any
    per-user environment variables (e.g. ANTHROPIC_API_KEY set on your
    account) live in your user profile / Windows Credential Manager. A
    SYSTEM-level task would not see any of that, and every real (non-
    dry-run) agent action that shells out to `gh` would fail as if never
    authenticated. The tradeoff: the dashboard only runs while you're
    logged into this Windows session - acceptable for a VM you RDP into
    during work hours. If you need it running before anyone logs in, that
    needs a "run whether user is logged on or not" (S4U) task instead,
    which needs testing on this actual machine to get the credential
    context right - ask before assuming that variant works as-is.

.PARAMETER Uninstall
    Remove the scheduled task instead of installing it.

.PARAMETER UserId
    Windows account to run the task as. Defaults to whoever runs this
    script - override only if you specifically need a different account.

.EXAMPLE
    .\install-windows-task.ps1
    .\install-windows-task.ps1 -Uninstall

.NOTES
    UNTESTED ON A REAL WINDOWS MACHINE - written and reviewed, but there is
    no Windows environment available here to actually run Register-
    ScheduledTask against. Review before relying on it; if a cmdlet
    errors, that's the thing to fix, not a sign to abandon the approach.

    If the dashboard starts but a run fails to find `git`/`gh`/`allure`
    that work fine in an interactive PowerShell window, log off and back
    on (or reboot) first - a Scheduled Task reads PATH at its own launch
    time, so a binary installed earlier in the same session may not be
    visible to it yet.
#>
param(
    [switch]$Uninstall,
    [string]$UserId = "$env:USERNAME"
)

$ErrorActionPreference = "Stop"
$TaskName = "AquaAutomationFactoryDashboard"
$DashboardDir = $PSScriptRoot
$BatchPath = Join-Path $DashboardDir "run-dashboard.bat"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "No scheduled task named '$TaskName' found - nothing to remove."
    }
    exit 0
}

if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Error "No 'python' or 'py' found on PATH. Install Python first (see RUNBOOK.md), then re-open PowerShell."
    exit 1
}

# The dashboard is a stdlib-only server (see dashboard/README.md) - no venv
# needed for it specifically, just a working Python interpreter on PATH.

$Action = New-ScheduledTaskAction -Execute $BatchPath -WorkingDirectory $DashboardDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId

$Settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Settings $Settings -Principal $Principal `
    -Description "Aqua Automation Factory - live pipeline dashboard (http://localhost:8787/)" | Out-Null

Write-Host "Installed scheduled task '$TaskName' (runs at logon for '$UserId', restarts on failure)."
Write-Host "Starting it now..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
Write-Host ""
Write-Host "Check status : Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "View logs    : Get-Content '$DashboardDir\run.log' -Tail 50 -Wait"
Write-Host "Dashboard    : http://localhost:8787/"
