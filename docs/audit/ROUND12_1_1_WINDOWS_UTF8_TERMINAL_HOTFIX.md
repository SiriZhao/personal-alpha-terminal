# ROUND 12.1.1 - Windows UTF-8 Terminal Final Hotfix

Date: 2026-08-14

Verdict: `ROUND12_1_1_READY`

## Root cause

The Windows CMD/PowerShell corruption was caused by localized strings stored as
literal ASCII `????` characters in `daily_renderer.py`, not by a general
terminal Unicode failure. In addition, the execution-plan panel had not yet
shown the required Chinese human labels for broker execution state and
execution mode.

This hotfix restores the full localized output while preserving the machine
status codes:

- `NOT_EXECUTED`
- `MANUAL_ONLY`
- `PASS`
- `PASS_DEGRADED`
- `FAIL_BLOCKING`
- `BLOCKED`
- `BUY`
- `SELL`
- `HOLD`
- `NO_TRADE`

## Required strings now covered

- `执行计划`
- `券商执行`
- `未执行`
- `执行方式`
- `仅手动`
- `券商`
- `最终有效决策`
- `被拒绝信号 / 门禁原因`
- `决策形成过程`
- `条件概率评估`
- `规模倾斜诊断`
- `候选池`
- `优化器输入`
- `最大允许持仓`
- `优化后目标持仓`

Execution display now renders both human and machine state, for example:

- `???????? NOT_EXECUTED`
- `???????? MANUAL_ONLY`

## Implementation

- `src/personal_alpha_terminal/terminal/daily_renderer.py`
  - Restored corrupted Chinese localization strings.
  - Added `???` and `???` alongside `NOT_EXECUTED` and `MANUAL_ONLY`.
  - Preserved all existing machine status codes.
- `src/personal_alpha_terminal/terminal/cli.py`
  - Kept the Windows-only UTF-8 stdout/stderr reconfigure and interactive
    console code-page fallback.
- `tests/unit/application/test_round12_1_live_semantics.py`
  - Extended the Chinese renderer regression labels.
  - Extended blocked-execution and UTF-8 redirected stdout smoke assertions.

## Quality gates

- Full pytest: `947 passed`
- `quant_critical`: `31 passed`
- Focused Round 12.1 / Unicode tests: `17 passed`
- Ruff: `All checks passed`
- Strict mypy: `Success: no issues found in 417 source files`
- Secret scan: `SECRET_SCAN_PASS`

## Scope and safety

No Alpha, Factor, Probability, Portfolio, Risk, LLM, SEC/PIT, Policy
governance, or execution semantics were changed. Automatic execution remains
disabled and broker execution remains manual-only.

## Next step

ROUND12.1.1 is closed. ROUND14 may now proceed as the next development round.
