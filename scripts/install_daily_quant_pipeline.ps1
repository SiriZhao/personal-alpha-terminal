param(
    [string]$TaskName = "Personal Alpha Terminal Daily Quant Pipeline",
    [string]$At = "08:00",
    [string]$ProjectDirectory = (Split-Path -Parent $PSScriptRoot),
    [string]$PatExecutable = "pat"
)

$ErrorActionPreference = "Stop"

$resolvedProject = (Resolve-Path -LiteralPath $ProjectDirectory).Path
$resolvedExecutable = (Get-Command $PatExecutable -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $resolvedProject ".env"))) {
    Write-Warning "No .env file was found; process environment and application defaults will apply."
}
$executableName = [System.IO.Path]::GetFileName($resolvedExecutable)
$arguments = if ($executableName -eq "PersonalAlphaTerminal.exe") {
    "--daily-pipeline"
}
else {
    "daily-pipeline --trigger scheduler"
}

$action = New-ScheduledTaskAction `
    -Execute $resolvedExecutable `
    -Argument $arguments `
    -WorkingDirectory $resolvedProject
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily local market update, validation, research, risk, and report pipeline" `
    -Force | Out-Null

Write-Output "Registered '$TaskName' at $At using $resolvedExecutable $arguments"
