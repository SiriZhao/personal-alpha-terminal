param(
    [string]$PythonExecutable = "python",
    [string]$EnvironmentDirectory = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$environmentPath = Join-Path $projectRoot $EnvironmentDirectory

if (-not (Test-Path -LiteralPath $environmentPath)) {
    & $PythonExecutable -m venv $environmentPath
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
}

$python = Join-Path $environmentPath "Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -e "$projectRoot[dev,dashboard,research,market-data,ai,quant-backends]"
if ($LASTEXITCODE -ne 0) { throw "Personal Alpha Terminal dependency installation failed" }

Write-Host "Quant environment ready. Qlib is intentionally installed separately with setup_qlib_research.ps1."
