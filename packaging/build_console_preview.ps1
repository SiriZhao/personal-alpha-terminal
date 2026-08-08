param(
    [string]$Version = "1.1.0-console-preview",
    [switch]$SkipTests,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PAT_BUILD_PYTHON) { $env:PAT_BUILD_PYTHON } else { Join-Path $ProjectRoot ".venv\Scripts\python.exe" }
$BundleRoot = Join-Path $ProjectRoot "dist\PersonalAlphaTerminal-Console"
$WorkRoot = Join-Path $ProjectRoot "build\console-preview"
$UnicodeSmokeName = "console-smoke-user-{0}{1} {2}{3}" -f (
    [char]0x4E2D, [char]0x6587, [char]0x7A7A, [char]0x683C
)
$SmokeRoot = Join-Path $ProjectRoot ("build\" + $UnicodeSmokeName)
$ArchivePath = Join-Path $ProjectRoot "dist\PersonalAlphaTerminal-Console-v$Version-win64.zip"

function Assert-ChildPath {
    param([string]$Path)
    $Root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $Target = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $Target.StartsWith("$Root\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project: $Target"
    }
}

function Reset-Directory {
    param([string]$Path)
    Assert-ChildPath $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

Push-Location $ProjectRoot
try {
    if (-not $SkipTests) {
        Invoke-Checked $Python @("-B", "-m", "pytest", "-q")
        Invoke-Checked $Python @("-B", "-m", "ruff", "check", "--no-cache", "src", "tests")
        Invoke-Checked $Python @("-B", "-m", "pip", "check")
    }

    if (-not $SkipBuild) {
        Reset-Directory $WorkRoot
        if (Test-Path -LiteralPath $BundleRoot) {
            Assert-ChildPath $BundleRoot
            Remove-Item -LiteralPath $BundleRoot -Recurse -Force
        }
        Invoke-Checked $Python @(
            "-B", "-m", "PyInstaller", "--noconfirm", "--clean",
            "--workpath", $WorkRoot, "--distpath", (Join-Path $ProjectRoot "dist"),
            "packaging/personal-alpha-terminal-console.spec"
        )
    }

    $Exe = Join-Path $BundleRoot "PersonalAlphaTerminal.exe"
    foreach ($Required in @($Exe, (Join-Path $BundleRoot "_internal\migrations\env.py"))) {
        if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
            throw "Missing packaged runtime asset: $Required"
        }
    }

    Copy-Item -LiteralPath "packaging\README_FIRST.txt" -Destination (Join-Path $BundleRoot "README_FIRST.txt") -Force
    New-Item -ItemType Directory -Path (Join-Path $BundleRoot "LICENSES") -Force | Out-Null
    Copy-Item -LiteralPath "docs\console\THIRD_PARTY_LICENSES.md" -Destination (Join-Path $BundleRoot "LICENSES\THIRD_PARTY_LICENSES.md") -Force

    Reset-Directory $SmokeRoot
    $PreviousLocalAppData = $env:LOCALAPPDATA
    $PreviousNonInteractive = $env:PAT_NONINTERACTIVE
    $PreviousSmoke = $env:PAT_TUI_SMOKE_TEST
    try {
        $env:LOCALAPPDATA = $SmokeRoot
        $env:PAT_NONINTERACTIVE = "1"
        Invoke-Checked $Exe @("doctor")
        $env:PAT_TUI_SMOKE_TEST = "1"
        Invoke-Checked $Exe @()
    }
    finally {
        $env:LOCALAPPDATA = $PreviousLocalAppData
        $env:PAT_NONINTERACTIVE = $PreviousNonInteractive
        $env:PAT_TUI_SMOKE_TEST = $PreviousSmoke
    }

    if (Test-Path -LiteralPath $ArchivePath) {
        Assert-ChildPath $ArchivePath
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    Compress-Archive -LiteralPath $BundleRoot -DestinationPath $ArchivePath -CompressionLevel Optimal
    $ExeHash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $ZipHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    @(
        "$ExeHash  PersonalAlphaTerminal-Console/PersonalAlphaTerminal.exe",
        "$ZipHash  $([IO.Path]::GetFileName($ArchivePath))"
    ) | Set-Content -LiteralPath (Join-Path $ProjectRoot "dist\SHA256SUMS-console.txt") -Encoding UTF8
    Write-Output "BUNDLE=$BundleRoot"
    Write-Output "ARCHIVE=$ArchivePath"
    Write-Output "EXE_SHA256=$ExeHash"
    Write-Output "ZIP_SHA256=$ZipHash"
}
finally {
    Pop-Location
}
