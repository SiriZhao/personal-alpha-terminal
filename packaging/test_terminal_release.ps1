param(
    [Parameter(Mandatory=$true)][string]$ReleaseDirectory
)

$ErrorActionPreference = "Stop"
$ResolvedRelease = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
if (-not (Test-Path -LiteralPath (Join-Path $ResolvedRelease "PersonalAlphaTerminal.exe") -PathType Leaf)) {
    throw "Executable missing from source release: $ResolvedRelease"
}

$Chinese = ([string][char]0x4E2D) + ([string][char]0x6587)
$SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "PAT Release Smoke $Chinese User"
if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $SmokeRoot | Out-Null
$CleanRelease = Join-Path $SmokeRoot "Clean Install With Spaces $Chinese"
Copy-Item -LiteralPath $ResolvedRelease -Destination $CleanRelease -Recurse
$Exe = Join-Path $CleanRelease "PersonalAlphaTerminal.exe"
$UserDataRoot = Join-Path $SmokeRoot "Fresh User Data $Chinese"
New-Item -ItemType Directory -Force -Path $UserDataRoot | Out-Null
$env:LOCALAPPDATA = $UserDataRoot
$env:PAT_NONINTERACTIVE = "1"
$ForbiddenProcesses = @("node", "npm", "msedge", "chrome", "firefox")
$BeforeProcessIds = @(
    Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in $ForbiddenProcesses } | ForEach-Object Id
)

& $Exe version
if ($LASTEXITCODE -ne 0) { throw "Version smoke failed: $LASTEXITCODE" }
& $Exe doctor
if ($LASTEXITCODE -notin @(0, 3)) { throw "Doctor smoke failed: $LASTEXITCODE" }
& $Exe --no-refresh daily
if ($LASTEXITCODE -notin @(0, 3)) { throw "First-launch daily smoke failed: $LASTEXITCODE" }
& $Exe data
if ($LASTEXITCODE -notin @(0, 3)) { throw "Persisted section smoke failed: $LASTEXITCODE" }
& $Exe portfolio-init --name "Smoke Portfolio" --cash 100000
if ($LASTEXITCODE -ne 0) { throw "Portfolio initialization smoke failed: $LASTEXITCODE" }
& $Exe portfolio-list
if ($LASTEXITCODE -ne 0) { throw "Portfolio listing smoke failed: $LASTEXITCODE" }
& $Exe portfolio-show --portfolio-id 1
if ($LASTEXITCODE -ne 0) { throw "Portfolio status smoke failed: $LASTEXITCODE" }
& $Exe --no-refresh daily
if ($LASTEXITCODE -notin @(0, 3)) { throw "Initialized daily smoke failed: $LASTEXITCODE" }
& $Exe mark-executed --help
if ($LASTEXITCODE -ne 0) { throw "Manual partial-fill CLI smoke failed: $LASTEXITCODE" }

$UserRoot = Join-Path $UserDataRoot "PersonalAlphaTerminal"
foreach ($required in @("config.env", "config.yaml", "data\personal_alpha.db", "logs\app.log")) {
    if (-not (Test-Path -LiteralPath (Join-Path $UserRoot $required))) {
        throw "First-launch artifact missing: $required"
    }
}
$AfterNewProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            [IO.Path]::GetFileNameWithoutExtension($_.Name) -in $ForbiddenProcesses -and
            $_.ProcessId -notin $BeforeProcessIds
        }
)
$NewForbiddenIds = @($AfterNewProcesses | ForEach-Object ProcessId)
$UnexpectedProcesses = @(
    $AfterNewProcesses | Where-Object {
        $_.ParentProcessId -notin $BeforeProcessIds -and
        $_.ParentProcessId -notin $NewForbiddenIds
    }
)
if ($UnexpectedProcesses) {
    $details = $UnexpectedProcesses | ForEach-Object { "$($_.Name):$($_.ProcessId) parent=$($_.ParentProcessId)" }
    throw "Release started a forbidden browser/Node process lineage: $($details -join ', ')"
}
foreach ($required in @("BUILD_MANIFEST.json", "SHA256SUMS.txt", "VERSION")) {
    if (-not (Test-Path -LiteralPath (Join-Path $CleanRelease $required) -PathType Leaf)) {
        throw "Release evidence missing: $required"
    }
}
Write-Output "PACKAGED_SMOKE_OK=$CleanRelease"
