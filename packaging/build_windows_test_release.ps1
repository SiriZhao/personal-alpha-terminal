param(
    [string]$Version = "1.0.0-test",
    [switch]$SkipApplicationBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PAT_BUILD_PYTHON) { $env:PAT_BUILD_PYTHON } else { "python" }
$BundleRoot = Join-Path $ProjectRoot "dist\PersonalAlphaTerminal"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$ReleaseExecutable = Join-Path $ReleaseRoot "Personal_Alpha_Terminal.exe"
$ArchivePath = Join-Path $ReleaseRoot "Personal_Alpha_Terminal-$Version-windows-x64.zip"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$Executable $($Arguments -join ' ')' failed with exit code $LASTEXITCODE."
    }
}

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

Push-Location $ProjectRoot
try {
    if (-not $SkipApplicationBuild) {
        Invoke-Checked $Python @("-c", "import PyInstaller")
        Invoke-Checked $Python @(
            "-m", "PyInstaller", "--noconfirm", "--clean",
            "packaging/personal-alpha-terminal.spec"
        )
    }

    $BundleExecutable = Join-Path $BundleRoot "PersonalAlphaTerminal.exe"
    foreach ($RequiredPath in @(
        $BundleExecutable,
        (Join-Path $BundleRoot "_internal\streamlit\static\index.html"),
        (Join-Path $BundleRoot "_internal\personal_alpha_terminal\dashboard\app.py"),
        (Join-Path $BundleRoot "_internal\migrations\env.py")
    )) {
        if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
            throw "Packaged runtime asset is missing: $RequiredPath"
        }
    }

    Reset-SafeDirectory $ReleaseRoot
    Get-ChildItem -LiteralPath $BundleRoot -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $ReleaseRoot -Recurse -Force
    }
    Move-Item -LiteralPath (Join-Path $ReleaseRoot "PersonalAlphaTerminal.exe") -Destination $ReleaseExecutable

    foreach ($Directory in @("config", "database", "logs")) {
        New-Item -ItemType Directory -Path (Join-Path $ReleaseRoot $Directory) -Force | Out-Null
    }
    Copy-Item -LiteralPath "packaging\README_START_1.0.0-test.md" -Destination (Join-Path $ReleaseRoot "README_START.md")
    Copy-Item -LiteralPath "docs\reports\release\BUILD_REPORT.md" -Destination (Join-Path $ReleaseRoot "BUILD_REPORT.md")
    Copy-Item -LiteralPath "packaging\release_config_README.md" -Destination (Join-Path $ReleaseRoot "config\README.md")
    Copy-Item -LiteralPath "packaging\release_database_README.md" -Destination (Join-Path $ReleaseRoot "database\README.md")
    Copy-Item -LiteralPath "packaging\release_logs_README.md" -Destination (Join-Path $ReleaseRoot "logs\README.md")

    if (Test-Path -LiteralPath $ArchivePath) {
        Remove-Item -LiteralPath $ArchivePath -Force
    }
    $ArchiveEntries = @(Get-ChildItem -LiteralPath $ReleaseRoot -Force | Where-Object {
        $_.FullName -ne $ArchivePath
    } | Select-Object -ExpandProperty Name)
    $Tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
    if ($null -ne $Tar) {
        Push-Location $ReleaseRoot
        try {
            & $Tar.Source "-a" "-c" "-f" $ArchivePath @ArchiveEntries
            if ($LASTEXITCODE -ne 0) {
                throw "tar.exe failed to create the release ZIP (exit $LASTEXITCODE)."
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        $ArchivePaths = $ArchiveEntries | ForEach-Object { Join-Path $ReleaseRoot $_ }
        Compress-Archive -Path $ArchivePaths -DestinationPath $ArchivePath -CompressionLevel Optimal
    }

    $Artifacts = @($ReleaseExecutable, $ArchivePath)
    $ManifestFiles = foreach ($Artifact in $Artifacts) {
        $Item = Get-Item -LiteralPath $Artifact
        $Hash = Get-FileHash -LiteralPath $Artifact -Algorithm SHA256
        [ordered]@{
            name = $Item.Name
            size_bytes = $Item.Length
            sha256 = $Hash.Hash.ToLowerInvariant()
        }
    }
    $Manifest = [ordered]@{
        product = "Personal Alpha Terminal"
        version = $Version
        platform = "windows-x64"
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        packaging = "PyInstaller onedir"
        user_data_root = "%LOCALAPPDATA%\PersonalAlphaTerminal"
        external_python_required = $false
        files = @($ManifestFiles)
    }
    $Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ReleaseRoot "release-manifest.json") -Encoding UTF8

    $HashLines = foreach ($Artifact in $Artifacts) {
        $Hash = Get-FileHash -LiteralPath $Artifact -Algorithm SHA256
        "$($Hash.Hash.ToLowerInvariant())  $((Get-Item -LiteralPath $Artifact).Name)"
    }
    Set-Content -LiteralPath (Join-Path $ReleaseRoot "SHA256SUMS.txt") -Value $HashLines -Encoding UTF8
    Write-Output "Windows test release created at: $ReleaseRoot"
}
finally {
    Pop-Location
}
