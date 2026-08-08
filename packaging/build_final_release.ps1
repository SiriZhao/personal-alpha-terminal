param(
    [string]$Version = "1.1.0",
    [switch]$SkipSourceTests
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PAT_BUILD_PYTHON) { $env:PAT_BUILD_PYTHON } else { Join-Path $ProjectRoot ".venv\Scripts\python.exe" }
$WorkRoot = Join-Path $ProjectRoot "build\final-product"
$BuildDist = Join-Path $WorkRoot "dist"
$BuiltBundle = Join-Path $BuildDist "QuantTerminal"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$ReleaseBundle = Join-Path $ReleaseRoot "QuantTerminal"
$ArchivePath = Join-Path $ReleaseRoot "QuantTerminal-v$Version-win64.zip"
$UnicodeSmokeName = "smoke-" + [char]0x4E2D + [char]0x6587 + " " + [char]0x7A7A + [char]0x683C
$SmokeRoot = Join-Path $WorkRoot $UnicodeSmokeName

function Assert-ProjectChild([string]$Path) {
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $target = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $target.StartsWith("$root\", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify outside project: $target"
    }
}

function Reset-ProjectDirectory([string]$Path) {
    Assert-ProjectChild $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Executable $($Arguments -join ' ')"
    }
}

function Compress-ReleaseWithRetry([string]$Source, [string]$Destination) {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            if (Test-Path -LiteralPath $Destination) {
                Remove-Item -LiteralPath $Destination -Force
            }
            Compress-Archive -LiteralPath $Source -DestinationPath $Destination -CompressionLevel Optimal
            return
        }
        catch {
            if ($attempt -eq 5) { throw }
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
}

Push-Location $ProjectRoot
try {
    if (-not $SkipSourceTests) {
        Invoke-Checked $Python @("-B", "-m", "ruff", "check", "--no-cache", "src", "tests")
        Invoke-Checked $Python @("-B", "-m", "pip", "check")
    }

    Reset-ProjectDirectory $WorkRoot
    New-Item -ItemType Directory -Path $BuildDist -Force | Out-Null
    Invoke-Checked $Python @(
        "-B", "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", (Join-Path $WorkRoot "pyinstaller"),
        "--distpath", $BuildDist,
        "packaging/personal-alpha-terminal-console.spec"
    )

    $Exe = Join-Path $BuiltBundle "QuantTerminal.exe"
    foreach ($Required in @($Exe, (Join-Path $BuiltBundle "_internal\migrations\env.py"))) {
        if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
            throw "Missing packaged runtime asset: $Required"
        }
    }

    Reset-ProjectDirectory $ReleaseRoot
    Copy-Item -LiteralPath $BuiltBundle -Destination $ReleaseBundle -Recurse
    Copy-Item -LiteralPath "README.md" -Destination (Join-Path $ReleaseBundle "README.txt")
    Set-Content -LiteralPath (Join-Path $ReleaseBundle "VERSION") -Value $Version -Encoding ASCII
    New-Item -ItemType Directory -Path (Join-Path $ReleaseBundle "LICENSES") -Force | Out-Null
    Copy-Item -LiteralPath "docs\console\THIRD_PARTY_LICENSES.md" -Destination (Join-Path $ReleaseBundle "LICENSES\THIRD_PARTY_LICENSES.md")

    Reset-ProjectDirectory $SmokeRoot
    $previousLocalAppData = $env:LOCALAPPDATA
    $previousNonInteractive = $env:PAT_NONINTERACTIVE
    $previousSmoke = $env:PAT_TUI_SMOKE_TEST
    try {
        $env:LOCALAPPDATA = $SmokeRoot
        $env:PAT_NONINTERACTIVE = "1"
        $ReleaseExe = Join-Path $ReleaseBundle "QuantTerminal.exe"
        Invoke-Checked $ReleaseExe @("doctor")
        Invoke-Checked $ReleaseExe @("portfolio-init", "--name", "Release Smoke", "--cash", "100000")
        Invoke-Checked $ReleaseExe @("portfolio-list")
        $env:PAT_TUI_SMOKE_TEST = "1"
        Invoke-Checked $ReleaseExe @()
        $env:PAT_TUI_SMOKE_TEST = $null
        & $ReleaseExe --no-refresh
        if ($LASTEXITCODE -notin @(0, 3)) {
            throw "Fail-closed daily smoke returned unexpected exit code $LASTEXITCODE"
        }
        Invoke-Checked $ReleaseExe @("doctor")
        foreach ($RequiredLog in @("app.log", "data.log", "error.log")) {
            if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot "PersonalAlphaTerminal\logs\$RequiredLog"))) {
                throw "Packaged runtime did not create $RequiredLog"
            }
        }
    }
    finally {
        $env:LOCALAPPDATA = $previousLocalAppData
        $env:PAT_NONINTERACTIVE = $previousNonInteractive
        $env:PAT_TUI_SMOKE_TEST = $previousSmoke
    }

    Start-Sleep -Milliseconds 750
    Compress-ReleaseWithRetry $ReleaseBundle $ArchivePath
    $ExeHash = (Get-FileHash -LiteralPath (Join-Path $ReleaseBundle "QuantTerminal.exe") -Algorithm SHA256).Hash.ToLowerInvariant()
    $ZipHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    @(
        "$ExeHash  QuantTerminal/QuantTerminal.exe",
        "$ZipHash  $([IO.Path]::GetFileName($ArchivePath))"
    ) | Set-Content -LiteralPath (Join-Path $ReleaseRoot "SHA256SUMS.txt") -Encoding ASCII
    Write-Output "RELEASE=$ReleaseBundle"
    Write-Output "ARCHIVE=$ArchivePath"
    Write-Output "EXE_SHA256=$ExeHash"
    Write-Output "ZIP_SHA256=$ZipHash"
}
finally {
    Pop-Location
}
