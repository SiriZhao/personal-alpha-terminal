$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
python "$PSScriptRoot\run_phase1_final_exam.py" --root $projectRoot
exit $LASTEXITCODE
