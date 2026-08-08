from __future__ import annotations

import json
import os
import subprocess
import sys


def test_terminal_core_does_not_eagerly_import_research_or_dev_stacks() -> None:
    code = """
import json
import sys
blocked = ('vectorbt', 'backtrader', 'numba', 'llvmlite', 'pyarrow',
           'IPython', 'jedi', 'mypy', 'coverage')
for package in blocked:
    sys.modules[package] = None
import personal_alpha_terminal.application.quant_daily_service
import personal_alpha_terminal.application.diagnostic_service
import personal_alpha_terminal.application.manual_execution_service
import personal_alpha_terminal.application.backtest_service
import personal_alpha_terminal.quant_engine.backtest
loaded = sorted(
    name for name, module in sys.modules.items()
    if name.split('.')[0] in blocked and module is not None
)
print(json.dumps(loaded))
"""
    environment = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    assert json.loads(result.stdout) == []
