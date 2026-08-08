param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = "1.1.0"
$ReleaseRoot = Join-Path $ProjectRoot "release"
$BuildRoot = Join-Path $ProjectRoot "build\terminal"
$DistRoot = Join-Path $BuildRoot "dist"
$WorkRoot = Join-Path $BuildRoot "work"
$ProductName = "PersonalAlphaTerminal-v$Version-win64"
$ProductRoot = Join-Path $ReleaseRoot $ProductName

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

$ZipPath = Join-Path $ReleaseRoot "$ProductName.zip"
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
Compress-Archive -LiteralPath $ProductRoot -DestinationPath $ZipPath -CompressionLevel Optimal
Write-Output "RELEASE_DIR=$ProductRoot"
Write-Output "RELEASE_ZIP=$ZipPath"
