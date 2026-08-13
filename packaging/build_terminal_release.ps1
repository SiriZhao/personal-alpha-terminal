param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = "1.2.0-rc.1"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$BuildRoot = Join-Path $ProjectRoot "build\terminal"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "work"
$ProductName = "PersonalAlphaTerminal-v$Version-win64"
$ProductRoot = Join-Path $ReleaseRoot $ProductName
$EmbeddedMetadata = Join-Path $ProjectRoot "packaging\build_metadata.json"

$GitCommit = (& git -C $ProjectRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $GitCommit.Length -ne 40) { throw "Git commit unavailable" }
$TrackedDrift = & git -C $ProjectRoot status --porcelain --untracked-files=no
if ($TrackedDrift) { throw "Tracked production tree is dirty; commit before release build" }
$DependencyLockHash = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "pyproject.toml") -Algorithm SHA256).Hash.ToLowerInvariant()
$BuildTime = [DateTimeOffset]::UtcNow.ToString("o")
$BuildId = "pat-$Version-$($GitCommit.Substring(0,12))-$([DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss'))"
$BuildMetadata = [ordered]@{
    version = $Version
    build_id = $BuildId
    git_commit = $GitCommit
    build_time = $BuildTime
    dependency_lock_hash = $DependencyLockHash
}
$Utf8NoBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText($EmbeddedMetadata, ($BuildMetadata | ConvertTo-Json), $Utf8NoBom)

foreach ($target in @($BuildRoot, $ProductRoot)) {
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if (-not $resolved.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove path outside project: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot, $ProductRoot | Out-Null

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $WorkRoot packaging\personal-alpha-terminal-console.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
    if (Test-Path -LiteralPath $EmbeddedMetadata) {
        Remove-Item -LiteralPath $EmbeddedMetadata -Force
    }
}

Copy-Item -Path (Join-Path $DistRoot "PersonalAlphaTerminal\*") -Destination $ProductRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $ProductRoot
New-Item -ItemType Directory -Force -Path (Join-Path $ProductRoot "docs") | Out-Null
foreach ($document in @("TERMINAL_GUIDE.md", "LLM_CONFIGURATION.md", "ARCHITECTURE.md", "TROUBLESHOOTING.md")) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\$document") -Destination (Join-Path $ProductRoot "docs\$document")
}
New-Item -ItemType Directory -Force -Path (Join-Path $ProductRoot "config") | Out-Null
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config.example.yaml") -Destination (Join-Path $ProductRoot "config\config.example.yaml")
Set-Content -LiteralPath (Join-Path $ProductRoot "VERSION") -Value $Version -Encoding utf8

$SklearnTests = Join-Path $ProductRoot "_internal\sklearn\datasets\tests"
if (Test-Path -LiteralPath $SklearnTests) {
    $resolvedTests = (Resolve-Path -LiteralPath $SklearnTests).Path
    if (-not $resolvedTests.StartsWith($ProductRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside release: $resolvedTests"
    }
    Remove-Item -LiteralPath $resolvedTests -Recurse -Force
}

$Forbidden = @(".git", "tests", "node_modules", ".env", "config.env", "personal_alpha.db")
foreach ($name in $Forbidden) {
    if (Get-ChildItem -LiteralPath $ProductRoot -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $name }) {
        throw "Forbidden release content detected: $name"
    }
}

$ReleaseFiles = @(
    Get-ChildItem -LiteralPath $ProductRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        if (-not $_.FullName.StartsWith($ProductRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Release file escaped product root: $($_.FullName)"
        }
        $relative = $_.FullName.Substring($ProductRoot.Length).TrimStart('\').Replace('\', '/')
        [ordered]@{
            path = $relative
            size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
)
$Manifest = [ordered]@{
    schema_version = "pat-build-manifest-v1"
    build = $BuildMetadata
    file_count = $ReleaseFiles.Count
    files = $ReleaseFiles
}
[IO.File]::WriteAllText(
    (Join-Path $ProductRoot "BUILD_MANIFEST.json"),
    ($Manifest | ConvertTo-Json -Depth 6),
    $Utf8NoBom
)
$Checksums = @(
    Get-ChildItem -LiteralPath $ProductRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        if (-not $_.FullName.StartsWith($ProductRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Release file escaped product root: $($_.FullName)"
        }
        $relative = $_.FullName.Substring($ProductRoot.Length).TrimStart('\').Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relative"
    }
)
$Checksums | Set-Content -LiteralPath (Join-Path $ProductRoot "SHA256SUMS.txt") -Encoding ascii

$ZipPath = Join-Path $ReleaseRoot "$ProductName.zip"
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -LiteralPath $ProductRoot -DestinationPath $ZipPath -CompressionLevel Optimal
$ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$ZipHash  $([IO.Path]::GetFileName($ZipPath))" | Set-Content -LiteralPath (Join-Path $ReleaseRoot "SHA256SUMS.txt") -Encoding ascii
Write-Output "RELEASE_DIR=$ProductRoot"
Write-Output "RELEASE_ZIP=$ZipPath"
Write-Output "BUILD_ID=$BuildId"
Write-Output "GIT_COMMIT=$GitCommit"
Write-Output "ZIP_SHA256=$ZipHash"
