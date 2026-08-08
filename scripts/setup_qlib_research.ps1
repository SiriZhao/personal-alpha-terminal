param(
    [string]$Python312 = "py -3.12",
    [string]$EnvironmentDirectory = ".qlib-venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$environmentPath = Join-Path $projectRoot $EnvironmentDirectory

Write-Host "Creating isolated Qlib factor-research environment at $environmentPath"
& cmd /c "$Python312 -m venv `"$environmentPath`""
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 environment creation failed" }

$python = Join-Path $environmentPath "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install "pyqlib>=0.9.7,<1"
if ($LASTEXITCODE -ne 0) { throw "Qlib installation failed" }

Write-Host "Qlib research runtime ready. It is not used for price prediction or order generation."
