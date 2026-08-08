param(
    [string]$Version = "0.9.0",
    [switch]$SkipTests,
    [switch]$SkipApplicationBuild,
    [switch]$FinalizeOnly,
    [switch]$PortableOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
$Python = if ($env:PAT_BUILD_PYTHON) { $env:PAT_BUILD_PYTHON } else { "python" }
$ReleaseRoot = Join-Path $ProjectRoot "release-preview"
$BundleRoot = Join-Path $ProjectRoot "dist\PersonalAlphaTerminal"
$InstallerRoot = Join-Path $ReleaseRoot "installer"
$PortableRoot = Join-Path $ReleaseRoot "portable"
$ChecksumRoot = Join-Path $ReleaseRoot "checksums"
$SbomRoot = Join-Path $ReleaseRoot "sbom"
$DocsRoot = Join-Path $ReleaseRoot "docs"
$ReportsRoot = Join-Path $ReleaseRoot "reports"
$BuildScriptsRoot = Join-Path $ReleaseRoot "build-scripts"
$KnownIssuesRoot = Join-Path $ReleaseRoot "known-issues"
$ReleaseBundle = Join-Path $PortableRoot "PersonalAlphaTerminal"
$ArchivePath = Join-Path $PortableRoot "PersonalAlphaTerminal-$Version-ResearchPreview-windows-x64.zip"

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

function Copy-ReleaseFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Required release file is missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Assert-BundledRuntimeAssets {
    param([Parameter(Mandatory = $true)][string]$Bundle)
    $RequiredAssets = @(
        (Join-Path $Bundle "PersonalAlphaTerminal.exe"),
        (Join-Path $Bundle "_internal\streamlit\static\index.html"),
        (Join-Path $Bundle "_internal\personal_alpha_terminal\dashboard\app.py"),
        (Join-Path $Bundle "_internal\migrations\env.py")
    )
    foreach ($Asset in $RequiredAssets) {
        if (-not (Test-Path -LiteralPath $Asset -PathType Leaf)) {
            throw "Packaged runtime asset is missing: $Asset"
        }
    }
}

Push-Location $ProjectRoot
try {
    $InstallerPath = Join-Path $InstallerRoot "PersonalAlphaTerminal-$Version-ResearchPreview-Setup.exe"
    if (-not $FinalizeOnly -and -not $SkipTests) {
        $TestRoot = Join-Path ([IO.Path]::GetTempPath()) "pat-release-tests"
        $TestTemp = Join-Path $TestRoot "pytest"
        foreach ($Directory in @(
            $TestRoot, $TestTemp, (Join-Path $TestRoot "pycache"),
            (Join-Path $TestRoot "mypy")
        )) {
            New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        }
        $env:TEMP = $TestRoot
        $env:TMP = $TestRoot
        $env:PYTHONPYCACHEPREFIX = Join-Path $TestRoot "pycache"
        $env:MYPY_CACHE_DIR = Join-Path $TestRoot "mypy"
        $env:PYTEST_DEBUG_TEMPROOT = $TestTemp
        Invoke-Checked $Python @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--basetemp", $TestTemp
        )
        Invoke-Checked $Python @(
            "-m", "ruff", "check", "--no-cache", "src", "tests", "scripts", "migrations"
        )
        Invoke-Checked $Python @(
            "-m", "mypy", "--no-incremental", "src/personal_alpha_terminal"
        )
        Invoke-Checked $Python @("-m", "pip", "check")
    }

    if (-not $FinalizeOnly -and -not $SkipApplicationBuild) {
        Invoke-Checked $Python @("-c", "import PyInstaller")
        Invoke-Checked $Python @(
            "-m", "PyInstaller", "--noconfirm", "--clean",
            "packaging/personal-alpha-terminal.spec"
        )
    }
    elseif (-not $FinalizeOnly -and -not (
        Test-Path -LiteralPath (Join-Path $BundleRoot "PersonalAlphaTerminal.exe")
    )) {
        throw "-SkipApplicationBuild requires an existing freshly built application bundle."
    }

    if (-not $FinalizeOnly) {
        Assert-BundledRuntimeAssets -Bundle $BundleRoot
        Copy-ReleaseFile "packaging/START_HERE.txt" $BundleRoot
        Copy-ReleaseFile "packaging/README_RELEASE.md" $BundleRoot
        Copy-ReleaseFile "packaging/Stop Personal Alpha Terminal.cmd" $BundleRoot
        Copy-ReleaseFile "packaging/Update Personal Alpha Terminal.cmd" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/USER_GUIDE.md" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/QUICK_START.md" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/DATA_SOURCE_GUIDE.md" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/AI_PROVIDER_GUIDE.md" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/TROUBLESHOOTING.md" $BundleRoot
        Copy-ReleaseFile "docs/user-guide/PRIVACY_AND_SECURITY.md" $BundleRoot
        Copy-ReleaseFile "docs/reports/strategy/RESEARCH_LIMITATIONS.md" $BundleRoot
        Copy-ReleaseFile "docs/reports/release/KNOWN_ISSUES.md" $BundleRoot
        Copy-ReleaseFile "docs/reports/release/RELEASE_NOTES_0.9.0.md" $BundleRoot
        Copy-ReleaseFile "docs/architecture/DASHBOARD.md" $BundleRoot

        Reset-SafeDirectory $ReleaseRoot
        foreach ($Directory in @(
            $InstallerRoot, $PortableRoot, $ChecksumRoot, $SbomRoot, $DocsRoot,
            $ReportsRoot, $BuildScriptsRoot, $KnownIssuesRoot
        )) {
            New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        }
        Copy-Item -LiteralPath $BundleRoot -Destination $ReleaseBundle -Recurse -Force
        Copy-ReleaseFile "packaging/START_HERE.txt" $ReleaseRoot
        Copy-ReleaseFile "packaging/README_RELEASE.md" (Join-Path $ReleaseRoot "README.md")
        foreach ($Document in @(
            "README.md", "CHANGELOG.md",
            "docs/user-guide/USER_GUIDE.md", "docs/user-guide/QUICK_START.md",
            "docs/user-guide/DATA_SOURCE_GUIDE.md", "docs/user-guide/AI_PROVIDER_GUIDE.md",
            "docs/user-guide/DEEPSEEK_SETUP.md", "docs/user-guide/TROUBLESHOOTING.md",
            "docs/user-guide/PRIVACY_AND_SECURITY.md",
            "docs/reports/strategy/RESEARCH_LIMITATIONS.md",
            "docs/reports/validation/PERSONAL_TEST_CHECKLIST.md",
            "docs/reports/release/RELEASE_NOTES_0.9.0.md"
        )) {
            Copy-ReleaseFile $Document (Join-Path $DocsRoot (Split-Path -Leaf $Document))
        }
        foreach ($Report in @(
            "docs/reports/validation/TEST_REPORT_PREVIEW.md",
            "docs/reports/release/PACKAGING_REPORT.md",
            "docs/reports/release/STARTUP_FIX_REPORT.md",
            "docs/reports/release/PACKAGE_FINAL_REPORT.md"
        )) {
            Copy-ReleaseFile $Report (Join-Path $ReportsRoot (Split-Path -Leaf $Report))
        }
        Copy-ReleaseFile "docs/reports/release/KNOWN_ISSUES.md" $KnownIssuesRoot
        Copy-ReleaseFile "packaging/build_windows_release.ps1" $BuildScriptsRoot
        Copy-ReleaseFile "packaging/test_windows_release.ps1" $BuildScriptsRoot
        Copy-ReleaseFile "packaging/capture_dashboard_cdp.py" $BuildScriptsRoot
        Copy-ReleaseFile "packaging/capture_dashboard.cjs" $BuildScriptsRoot
        Copy-ReleaseFile "packaging/personal-alpha-terminal.spec" $BuildScriptsRoot
        Copy-ReleaseFile "packaging/personal-alpha-terminal.iss" $BuildScriptsRoot

        Compress-Archive `
            -Path (Join-Path $BundleRoot "*") `
            -DestinationPath $ArchivePath `
            -CompressionLevel Optimal `
            -Force
    }

    if (-not $FinalizeOnly -and -not $PortableOnly) {
        $IsccCandidates = @(
            @(
                $env:PAT_ISCC,
                (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
                (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe")
            ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        )
        if ($IsccCandidates.Count -eq 0) {
            Write-Warning "ISCC.exe not found. Portable output will be retained; installer is environment-blocked."
            $PortableOnly = $true
        }
        if (-not $PortableOnly) {
            Invoke-Checked $IsccCandidates[0] @(
                "/DMyAppVersion=$Version",
                "packaging/personal-alpha-terminal.iss"
            )
            if (-not (Test-Path -LiteralPath $InstallerPath)) {
                throw "Inno Setup completed without producing the expected installer."
            }
        }
    }
    if (-not (Test-Path -LiteralPath $ArchivePath)) {
        throw "Portable ZIP is missing: $ArchivePath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ReleaseBundle "PersonalAlphaTerminal.exe"))) {
        throw "Release application bundle is missing."
    }
    if (-not $PortableOnly -and -not (Test-Path -LiteralPath $InstallerPath)) {
        throw "Installer is missing: $InstallerPath"
    }

    $Artifacts = @($ArchivePath, (Join-Path $ReleaseBundle "PersonalAlphaTerminal.exe"))
    if (Test-Path -LiteralPath $InstallerPath) {
        $Artifacts += $InstallerPath
    }
    $HashLines = foreach ($Artifact in $Artifacts) {
        $Hash = Get-FileHash -LiteralPath $Artifact -Algorithm SHA256
        $RelativeName = $Artifact.Substring($ReleaseRoot.Length).TrimStart('\')
        "$($Hash.Hash.ToLowerInvariant())  $RelativeName"
    }
    Set-Content `
        -LiteralPath (Join-Path $ChecksumRoot "SHA256SUMS.txt") `
        -Value $HashLines `
        -Encoding UTF8

    $ManifestFiles = foreach ($Artifact in $Artifacts) {
        $Item = Get-Item -LiteralPath $Artifact
        $Hash = Get-FileHash -LiteralPath $Artifact -Algorithm SHA256
        [ordered]@{
            name = $Artifact.Substring($ReleaseRoot.Length).TrimStart('\')
            size_bytes = $Item.Length
            sha256 = $Hash.Hash.ToLowerInvariant()
        }
    }
    $Manifest = [ordered]@{
        product = "Personal Alpha Terminal"
        version = $Version
        platform = "windows-x64"
        generated_at = [DateTimeOffset]::UtcNow.ToString("o")
        installer_included = (Test-Path -LiteralPath $InstallerPath)
        files = @($ManifestFiles)
    }
    $Manifest | ConvertTo-Json -Depth 5 | Set-Content `
        -LiteralPath (Join-Path $ReleaseRoot "release-manifest.json") `
        -Encoding UTF8

    Invoke-Checked $Python @(
        "scripts/generate_sbom.py",
        "--sbom", (Join-Path $SbomRoot "sbom.cyclonedx.json"),
        "--licenses", (Join-Path $SbomRoot "THIRD_PARTY_LICENSES.json")
    )

    Write-Output "Release created at: $ReleaseRoot"
}
finally {
    Pop-Location
}
