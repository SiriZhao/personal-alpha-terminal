param(
    [string]$Version = "0.9.0",
    [string]$ReleaseRoot = "",
    [switch]$PortableOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ReleaseRoot) {
    $ReleaseRoot = Join-Path $ProjectRoot "release-preview"
}
$ReleaseRoot = [IO.Path]::GetFullPath($ReleaseRoot)
$ValidationRoot = Join-Path $ProjectRoot ".tmp\windows-release-validation"
$EvidenceRoot = Join-Path $ReleaseRoot "reports\validation"
$ScreenshotRoot = Join-Path $EvidenceRoot "screenshots"
$LogEvidenceRoot = Join-Path $EvidenceRoot "logs"
$BrowserNode = if ($env:PAT_BROWSER_NODE) {
    $env:PAT_BROWSER_NODE
}
else {
    (Get-Command node -ErrorAction SilentlyContinue).Source
}
$BrowserNodeModules = $env:PAT_NODE_MODULES
$BrowserChromium = $env:PAT_CHROMIUM_EXECUTABLE
$BrowserCaptureScript = Join-Path $PSScriptRoot "capture_dashboard.cjs"
$BrowserCdpCaptureScript = Join-Path $PSScriptRoot "capture_dashboard_cdp.py"
$BrowserPython = if ($env:PAT_BUILD_PYTHON) {
    $env:PAT_BUILD_PYTHON
}
else {
    (Get-Command python -ErrorAction SilentlyContinue).Source
}

function Reset-ValidationDirectory {
    $ResolvedProject = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $ResolvedTarget = [IO.Path]::GetFullPath($ValidationRoot).TrimEnd('\')
    if (-not $ResolvedTarget.StartsWith("$ResolvedProject\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset validation directory outside the project."
    }
    if (Test-Path -LiteralPath $ResolvedTarget) {
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
    }
    New-Item -ItemType Directory -Path $ResolvedTarget -Force | Out-Null
}

function Wait-ForCondition {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [int]$TimeoutSeconds = 60
    )
    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (& $Condition) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Capture-DashboardScreenshot {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$ScreenshotPath,
        [Parameter(Mandatory = $true)][string]$ProfilePath
    )
    New-Item -ItemType Directory -Path $ProfilePath -Force | Out-Null
    $BrowserScreenshotPath = Join-Path $ProfilePath "dashboard.png"
    $BrowserMetadataPath = Join-Path $ProfilePath "dashboard.json"
    if (-not $BrowserNodeModules -or -not (Test-Path -LiteralPath $BrowserNodeModules)) {
        if (-not $BrowserChromium -or -not (Test-Path -LiteralPath $BrowserChromium)) {
            throw "Playwright or a trusted local Chromium executable is required for release screenshots."
        }
        if (-not $BrowserPython -or -not (Test-Path -LiteralPath $BrowserPython)) {
            throw "PAT_BUILD_PYTHON is required for Chromium CDP release validation."
        }
        $BrowserOutput = & $BrowserPython @(
            $BrowserCdpCaptureScript,
            "--chrome", $BrowserChromium,
            "--url", $Url,
            "--screenshot", $BrowserScreenshotPath,
            "--metadata", $BrowserMetadataPath,
            "--profile", $ProfilePath
        ) 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "Chromium CDP screenshot failed with exit code $LASTEXITCODE`: $BrowserOutput"
        }
    }
    else {
        if (-not $BrowserNode -or -not (Test-Path -LiteralPath $BrowserNode)) {
            throw "A Node.js test runtime is required when PAT_NODE_MODULES is configured."
        }
        $SavedNodePath = $env:NODE_PATH
        $SavedChromiumExecutable = $env:PAT_CHROMIUM_EXECUTABLE
        try {
            $env:NODE_PATH = $BrowserNodeModules
            if ($BrowserChromium) {
                $env:PAT_CHROMIUM_EXECUTABLE = $BrowserChromium
            }
            $BrowserOutput = & $BrowserNode `
                $BrowserCaptureScript `
                $Url `
                $BrowserScreenshotPath `
                $BrowserMetadataPath 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Playwright screenshot failed with exit code $LASTEXITCODE`: $BrowserOutput"
            }
        }
        finally {
            $env:NODE_PATH = $SavedNodePath
            $env:PAT_CHROMIUM_EXECUTABLE = $SavedChromiumExecutable
        }
    }
    $ScreenshotReady = Wait-ForCondition {
        (Test-Path -LiteralPath $BrowserScreenshotPath) -and
        (Get-Item -LiteralPath $BrowserScreenshotPath).Length -ge 10000
    } -TimeoutSeconds 20
    if (-not $ScreenshotReady) {
        throw "Dashboard screenshot is unexpectedly small: $BrowserScreenshotPath"
    }
    Copy-Item -LiteralPath $BrowserScreenshotPath -Destination $ScreenshotPath -Force
    Copy-Item `
        -LiteralPath $BrowserMetadataPath `
        -Destination "$ScreenshotPath.json" `
        -Force
}

function Copy-ApplicationLogs {
    param(
        [Parameter(Mandatory = $true)][string]$AppData,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $Destination = Join-Path $LogEvidenceRoot $Label
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Copied = @()
    foreach ($Source in @(
        (Join-Path $AppData "boot.log"),
        (Join-Path $AppData "startup-status.json")
    )) {
        if (Test-Path -LiteralPath $Source) {
            $Target = Join-Path $Destination (Split-Path -Leaf $Source)
            Copy-Item -LiteralPath $Source -Destination $Target -Force
            $Copied += $Target
        }
    }
    $ApplicationLogRoot = Join-Path $AppData "logs"
    if (Test-Path -LiteralPath $ApplicationLogRoot) {
        foreach ($Source in Get-ChildItem -LiteralPath $ApplicationLogRoot -File) {
            $Target = Join-Path $Destination $Source.Name
            Copy-Item -LiteralPath $Source.FullName -Destination $Target -Force
            $Copied += $Target
        }
    }
    return $Copied
}

function Invoke-DesktopSmoke {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$UserRoot,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $SavedEnvironment = @{
        LOCALAPPDATA = $env:LOCALAPPDATA
        PATH = $env:PATH
        PAT_NO_BROWSER = $env:PAT_NO_BROWSER
        PAT_SILENT = $env:PAT_SILENT
        PAT_DATABASE_URL = $env:PAT_DATABASE_URL
        PAT_LOG_DIR = $env:PAT_LOG_DIR
        PYTHONHOME = $env:PYTHONHOME
        PYTHONPATH = $env:PYTHONPATH
    }
    $Process = $null
    try {
        New-Item -ItemType Directory -Path $UserRoot -Force | Out-Null
        $env:LOCALAPPDATA = $UserRoot
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:PAT_NO_BROWSER = "1"
        $env:PAT_SILENT = "1"
        Remove-Item Env:PAT_DATABASE_URL -ErrorAction SilentlyContinue
        Remove-Item Env:PAT_LOG_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        $PythonVisible = $null -ne (Get-Command python -ErrorAction SilentlyContinue)

        $Process = Start-Process `
            -FilePath $Executable `
            -WorkingDirectory (Split-Path -Parent $Executable) `
            -WindowStyle Hidden `
            -PassThru
        $AppData = Join-Path $UserRoot "PersonalAlphaTerminal"
        $PidPath = Join-Path $AppData "personal-alpha-terminal.pid"
        if (-not (Wait-ForCondition { Test-Path -LiteralPath $PidPath })) {
            throw "$Label did not write its instance metadata within 60 seconds."
        }
        $Instance = Get-Content -LiteralPath $PidPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $HealthUrl = "$($Instance.url)/_stcore/health"
        if (-not (Wait-ForCondition {
            try {
                $Response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
                return $Response.StatusCode -eq 200
            }
            catch {
                return $false
            }
        })) {
            throw "$Label did not become healthy within 60 seconds."
        }
        $RootResponse = Invoke-WebRequest -Uri $Instance.url -UseBasicParsing -TimeoutSec 10
        if ($RootResponse.StatusCode -ne 200 -or $RootResponse.Content.Length -lt 1000) {
            throw "$Label dashboard root did not return a complete HTTP 200 response."
        }

        $RequiredFiles = @(
            (Join-Path $AppData "config.env"),
            (Join-Path $AppData "data\personal_alpha.db"),
            (Join-Path $AppData "startup-status.json")
        )
        foreach ($RequiredFile in $RequiredFiles) {
            if (-not (Test-Path -LiteralPath $RequiredFile)) {
                throw "$Label did not create required file: $RequiredFile"
            }
        }
        $Startup = Get-Content `
            -LiteralPath (Join-Path $AppData "startup-status.json") `
            -Raw `
            -Encoding UTF8 | ConvertFrom-Json
        if ($Startup.status -ne "ready" -or -not $Startup.bundled_runtime) {
            throw "$Label startup diagnostics did not report a ready bundled runtime."
        }
        $Duplicate = Start-Process `
            -FilePath $Executable `
            -WorkingDirectory (Split-Path -Parent $Executable) `
            -WindowStyle Hidden `
            -PassThru
        if (-not $Duplicate.WaitForExit(20000)) {
            Stop-Process -Id $Duplicate.Id -Force -ErrorAction SilentlyContinue
            throw "$Label duplicate launch did not return to the existing instance."
        }
        if ($Duplicate.ExitCode -ne 0) {
            throw "$Label duplicate launch returned exit code $($Duplicate.ExitCode)."
        }
        $RequiredDirectories = @(
            "data", "logs", "reports", "run", "updates", "backups", "diagnostics"
        )
        foreach ($DirectoryName in $RequiredDirectories) {
            $DirectoryPath = Join-Path $AppData $DirectoryName
            if (-not (Test-Path -LiteralPath $DirectoryPath -PathType Container)) {
                throw "$Label did not create required directory: $DirectoryPath"
            }
        }

        $ScreenshotPath = Join-Path $ScreenshotRoot "$Label-dashboard.png"
        Capture-DashboardScreenshot `
            -Url $Instance.url `
            -ScreenshotPath $ScreenshotPath `
            -ProfilePath (Join-Path ([IO.Path]::GetTempPath()) "pat-edge-$Label-$([Guid]::NewGuid())")

        $Stop = Start-Process `
            -FilePath $Executable `
            -ArgumentList "--stop" `
            -WorkingDirectory (Split-Path -Parent $Executable) `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($Stop.ExitCode -ne 0) {
            throw "$Label stop command failed with exit code $($Stop.ExitCode)."
        }
        if (-not (Wait-ForCondition { -not (Test-Path -LiteralPath $PidPath) } -TimeoutSeconds 15)) {
            throw "$Label did not remove its PID file after shutdown."
        }
        if (-not $Process.HasExited) {
            $Process.WaitForExit(15000) | Out-Null
        }
        if (-not $Process.HasExited) {
            throw "$Label process remained alive after the verified stop command."
        }
        $CopiedLogs = @(Copy-ApplicationLogs -AppData $AppData -Label $Label)
        $PythonExecutables = @(
            Get-ChildItem `
                -LiteralPath (Split-Path -Parent $Executable) `
                -Filter "python.exe" `
                -File `
                -Recurse `
                -ErrorAction SilentlyContinue
        )

        return [ordered]@{
            label = $Label
            executable = $Executable
            health_status = 200
            python_visible_on_path = $PythonVisible
            startup_status = $Startup.status
            database_backend = $Startup.database_backend
            migration_revision = $Startup.checks.database_migration
            bundled_runtime = $Startup.bundled_runtime
            external_python_executables_in_install = $PythonExecutables.Count
            created_directories = $RequiredDirectories
            screenshot = $ScreenshotPath
            copied_logs = $CopiedLogs
            clean_shutdown = $true
            duplicate_launch_rejected = $true
        }
    }
    finally {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
        foreach ($Key in $SavedEnvironment.Keys) {
            $Value = $SavedEnvironment[$Key]
            if ($null -eq $Value) {
                Remove-Item "Env:$Key" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$Key" $Value
            }
        }
    }
}

Reset-ValidationDirectory
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ScreenshotRoot -Force | Out-Null
New-Item -ItemType Directory -Path $LogEvidenceRoot -Force | Out-Null
$ManifestPath = Join-Path $ReleaseRoot "release-manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Release manifest is missing: $ManifestPath"
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$Manifest.version -ne $Version) {
    throw "Release manifest version $($Manifest.version) does not match requested $Version."
}
$Results = @()

$PortableExecutable = Join-Path $ReleaseRoot "portable\PersonalAlphaTerminal\PersonalAlphaTerminal.exe"
if (-not (Test-Path -LiteralPath $PortableExecutable)) {
    throw "Portable executable is missing: $PortableExecutable"
}
$PortableStaticIndex = Join-Path $ReleaseRoot "portable\PersonalAlphaTerminal\_internal\streamlit\static\index.html"
if (-not (Test-Path -LiteralPath $PortableStaticIndex -PathType Leaf)) {
    throw "Portable package is incomplete: Streamlit static assets are missing. Extract the full portable directory."
}
$Results += Invoke-DesktopSmoke `
    -Executable $PortableExecutable `
    -UserRoot (Join-Path $ValidationRoot "portable-user") `
    -Label "portable"

if (-not $PortableOnly) {
    $Installer = Join-Path $ReleaseRoot "installer\PersonalAlphaTerminal-$Version-ResearchPreview-Setup.exe"
    if (-not (Test-Path -LiteralPath $Installer)) {
        throw "Installer is missing: $Installer"
    }
    $InstallerEntry = @(
        $Manifest.files | Where-Object {
            ([string]$_.name).EndsWith((Split-Path -Leaf $Installer))
        }
    )
    if ($InstallerEntry.Count -ne 1) {
        throw "Release manifest does not contain exactly one installer entry."
    }
    $InstallerHash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($InstallerHash -ne [string]$InstallerEntry[0].sha256) {
        throw "Installer SHA256 does not match the release manifest."
    }
    $InstallRoot = Join-Path $ValidationRoot "installed-app"
    $InstallerLog = Join-Path $LogEvidenceRoot "installer.log"
    $SavedLocalAppData = $env:LOCALAPPDATA
    try {
        $env:LOCALAPPDATA = Join-Path $ValidationRoot "installer-shell"
        New-Item -ItemType Directory -Path $env:LOCALAPPDATA -Force | Out-Null
        $QuotedInstallRoot = '"' + $InstallRoot + '"'
        $QuotedInstallerLog = '"' + $InstallerLog + '"'
        $Setup = Start-Process `
            -FilePath $Installer `
            -ArgumentList @(
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CURRENTUSER",
                "/TASKS=!desktopicon",
                "/DIR=$QuotedInstallRoot",
                "/LOG=$QuotedInstallerLog"
            ) `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($Setup.ExitCode -ne 0) {
            throw "Installer failed with exit code $($Setup.ExitCode)."
        }
    }
    finally {
        $env:LOCALAPPDATA = $SavedLocalAppData
    }
    $InstalledExecutable = Join-Path $InstallRoot "PersonalAlphaTerminal.exe"
    if (-not (Test-Path -LiteralPath $InstalledExecutable)) {
        throw "Installed executable is missing after silent setup."
    }
    $Results += Invoke-DesktopSmoke `
        -Executable $InstalledExecutable `
        -UserRoot (Join-Path $ValidationRoot "installed-user") `
        -Label "installed"
}

$Evidence = [ordered]@{
    product = "Personal Alpha Terminal"
    version = $Version
    checked_at = [DateTimeOffset]::UtcNow.ToString("o")
    host_os = [Environment]::OSVersion.VersionString
    test_scope = "local Windows host with isolated install and user-data directories"
    clean_vm_validated = $false
    external_python_required = $false
    release_generated_at = $Manifest.generated_at
    installer_sha256 = if ($PortableOnly) { $null } else { $InstallerHash }
    installer_log = if ($PortableOnly) { $null } else { $InstallerLog }
    results = $Results
}
$EvidencePath = Join-Path $EvidenceRoot "windows-smoke.json"
$Evidence | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
Write-Output "Windows release smoke validation passed: $EvidencePath"
