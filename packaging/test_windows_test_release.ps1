param(
    [string]$Version = "1.0.0-test"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$ReleaseRoot = Join-Path $ProjectRoot "release"
$Executable = Join-Path $ReleaseRoot "Personal_Alpha_Terminal.exe"
$ValidationRoot = Join-Path $ProjectRoot "var\test-runtime\windows-test-release"
$UserRoot = Join-Path $ValidationRoot "isolated-localappdata"
$EvidencePath = Join-Path $ValidationRoot "windows-smoke.json"

function Reset-SafeDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $ResolvedProject = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $ResolvedTarget = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $ResolvedTarget.StartsWith("$ResolvedProject\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset a directory outside the project: $ResolvedTarget"
    }
    if (Test-Path -LiteralPath $ResolvedTarget) {
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ResolvedTarget -Force | Out-Null
}

function Wait-ForCondition {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [int]$TimeoutSeconds = 90
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-TestInstance {
    param([Parameter(Mandatory = $true)][string]$WorkingDirectory)
    $Stop = Start-Process -FilePath $Executable -ArgumentList "--stop" -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -Wait -PassThru
    if ($Stop.ExitCode -ne 0) {
        throw "Packaged stop command failed with exit code $($Stop.ExitCode)."
    }
}

function Invoke-SmokeRun {
    param([Parameter(Mandatory = $true)][string]$Label)
    $Process = $null
    $AppData = Join-Path $UserRoot "PersonalAlphaTerminal"
    $PidPath = Join-Path $AppData "personal-alpha-terminal.pid"
    try {
        $Process = Start-Process -FilePath $Executable -WorkingDirectory $ReleaseRoot -WindowStyle Hidden -PassThru
        if (-not (Wait-ForCondition { Test-Path -LiteralPath $PidPath })) {
            throw "$Label did not create instance metadata."
        }
        $Instance = Get-Content -LiteralPath $PidPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not ([string]$Instance.url).StartsWith("http://127.0.0.1:")) {
            throw "$Label exposed a non-loopback dashboard URL."
        }
        $HealthUrl = "$($Instance.url)/_stcore/health"
        if (-not (Wait-ForCondition {
            try {
                (Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200
            }
            catch { $false }
        })) {
            throw "$Label did not become healthy."
        }
        $Root = Invoke-WebRequest -Uri $Instance.url -UseBasicParsing -TimeoutSec 10
        if ($Root.StatusCode -ne 200 -or $Root.Content.Length -lt 1000) {
            throw "$Label dashboard did not return a complete HTTP 200 response."
        }
        $Startup = Get-Content -LiteralPath (Join-Path $AppData "startup-status.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($Startup.status -ne "ready" -or -not $Startup.bundled_runtime) {
            throw "$Label startup diagnostics are not ready for a bundled runtime."
        }
        Stop-TestInstance -WorkingDirectory $ReleaseRoot
        if (-not (Wait-ForCondition { -not (Test-Path -LiteralPath $PidPath) } -TimeoutSeconds 20)) {
            throw "$Label did not remove instance metadata during shutdown."
        }
        if (-not $Process.HasExited) { $Process.WaitForExit(20000) | Out-Null }
        if (-not $Process.HasExited) { throw "$Label process did not stop cleanly." }
        return [ordered]@{
            label = $Label
            url = $Instance.url
            health_status = 200
            root_status = $Root.StatusCode
            startup_status = $Startup.status
            database_backend = $Startup.database_backend
            migration_revision = $Startup.checks.database_migration
            bundled_runtime = $Startup.bundled_runtime
            clean_shutdown = $true
        }
    }
    finally {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Release executable is missing: $Executable"
}
if (-not (Test-Path -LiteralPath (Join-Path $ReleaseRoot "_internal\streamlit\static\index.html") -PathType Leaf)) {
    throw "Streamlit static assets are missing from the release."
}

Reset-SafeDirectory $ValidationRoot
$SavedEnvironment = @{
    LOCALAPPDATA = $env:LOCALAPPDATA
    PATH = $env:PATH
    PAT_NO_BROWSER = $env:PAT_NO_BROWSER
    PAT_SILENT = $env:PAT_SILENT
    PAT_LLM_PROVIDER = $env:PAT_LLM_PROVIDER
    PAT_DATABASE_URL = $env:PAT_DATABASE_URL
    PAT_LOG_DIR = $env:PAT_LOG_DIR
    PYTHONHOME = $env:PYTHONHOME
    PYTHONPATH = $env:PYTHONPATH
}
try {
    New-Item -ItemType Directory -Path $UserRoot -Force | Out-Null
    $env:LOCALAPPDATA = $UserRoot
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PAT_NO_BROWSER = "1"
    $env:PAT_SILENT = "1"
    $env:PAT_LLM_PROVIDER = "disabled"
    foreach ($Name in @("PAT_DATABASE_URL", "PAT_LOG_DIR", "PYTHONHOME", "PYTHONPATH", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY")) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }

    $FirstRun = Invoke-SmokeRun -Label "first-install-empty-db-no-ai"
    $AppData = Join-Path $UserRoot "PersonalAlphaTerminal"
    foreach ($RequiredFile in @(
        (Join-Path $AppData "config.env"),
        (Join-Path $AppData "data\personal_alpha.db"),
        (Join-Path $AppData "startup-status.json"),
        (Join-Path $AppData "boot.log")
    )) {
        if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
            throw "First run did not create required file: $RequiredFile"
        }
    }
    $Config = Get-Content -LiteralPath (Join-Path $AppData "config.env") -Raw -Encoding UTF8
    if ($Config -match "(?i)(OPENAI_API_KEY|DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|sk-[A-Za-z0-9])") {
        throw "Generated configuration contains a credential-like value."
    }
    $Restart = Invoke-SmokeRun -Label "restart-existing-db"

    $Manifest = Get-Content -LiteralPath (Join-Path $ReleaseRoot "release-manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$Manifest.version -ne $Version) {
        throw "Release manifest version mismatch: $($Manifest.version)"
    }
    $Evidence = [ordered]@{
        product = "Personal Alpha Terminal"
        version = $Version
        checked_at = [DateTimeOffset]::UtcNow.ToString("o")
        host_os = [Environment]::OSVersion.VersionString
        test_scope = "current Windows host with isolated user-data directory and no Python on child PATH"
        clean_vm_validated = $false
        external_python_required = $false
        first_run = $FirstRun
        restart = $Restart
        generated_files = @("config.env", "data/personal_alpha.db", "startup-status.json", "boot.log")
        ai_provider = "disabled"
        api_keys_in_generated_config = $false
    }
    $Evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    Write-Output "Windows test release smoke validation passed: $EvidencePath"
}
finally {
    foreach ($Key in $SavedEnvironment.Keys) {
        $Value = $SavedEnvironment[$Key]
        if ($null -eq $Value) { Remove-Item "Env:$Key" -ErrorAction SilentlyContinue }
        else { Set-Item "Env:$Key" $Value }
    }
}
