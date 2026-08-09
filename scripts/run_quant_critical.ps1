param(
    [string]$Python = ".\.venv314\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Manifest = Get-Content -LiteralPath (Join-Path $ProjectRoot "tests\quant_critical\SUITE_MANIFEST.json") -Raw | ConvertFrom-Json
Push-Location $ProjectRoot
try {
    $Collected = @(& $Python -m pytest -m quant_critical --collect-only -q -p no:cacheprovider)
    if ($LASTEXITCODE -ne 0) { throw "quant_critical collection failed" }
    $Count = @($Collected | Where-Object { $_ -match '::' }).Count
    if ($Count -lt [int]$Manifest.minimum_test_count) {
        throw "quant_critical count $Count is below governed minimum $($Manifest.minimum_test_count)"
    }
    & $Python -m pytest -m quant_critical -q -p no:cacheprovider --basetemp ".tmp\quant-critical-script"
    if ($LASTEXITCODE -ne 0) { throw "quant_critical regression failed" }
    Write-Output "QUANT_CRITICAL_COUNT=$Count"
} finally {
    Pop-Location
}
