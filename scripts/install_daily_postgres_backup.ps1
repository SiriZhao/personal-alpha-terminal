param(
    [string]$TaskName = "Personal Alpha Terminal PostgreSQL Backup",
    [string]$At = "02:00",
    [string]$ProjectDirectory = (Split-Path -Parent $PSScriptRoot),
    [string]$PatExecutable = "pat"
)

$ErrorActionPreference = "Stop"

$resolvedProject = (Resolve-Path -LiteralPath $ProjectDirectory).Path
$resolvedExecutable = (Get-Command $PatExecutable -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $resolvedProject ".env"))) {
    throw "Production .env not found in $resolvedProject"
}

$action = New-ScheduledTaskAction `
    -Execute $resolvedExecutable `
    -Argument "db-backup" `
    -WorkingDirectory $resolvedProject
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
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
    -Description "Daily verified PostgreSQL backup for Personal Alpha Terminal" `
    -Force | Out-Null

Write-Output "Registered '$TaskName' at $At using $resolvedExecutable"
