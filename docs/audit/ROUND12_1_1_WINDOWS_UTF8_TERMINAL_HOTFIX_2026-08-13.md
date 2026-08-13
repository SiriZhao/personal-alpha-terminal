# ROUND 12.1.1 - Windows Terminal UTF-8 / Chinese Rendering Final Hotfix

Date: 2026-08-13

Verdict: `ROUND12_1_1_READY_FOR_POLICY_RENEWAL`

## Executive conclusion

The Windows CMD corruption was a source-string defect, not a general console
Unicode failure. Several Round 12.1 localization strings in
`src/personal_alpha_terminal/terminal/daily_renderer.py` had been stored as
literal ASCII `????` characters. Those strings could never render as Chinese,
regardless of console code page or terminal encoding.

The hotfix restored the intended Chinese localization, added a Windows-only
UTF-8 console fallback at the CLI entry point, and added renderer/encoding
regression coverage. No strategy, factor, alpha, probability, portfolio, risk,
LLM, SEC/PIT, OperationalPolicy, or execution semantics were changed.

## 1. Root cause

- Source files are UTF-8.
- The corrupt strings were already literal `?` characters inside Python source.
- Python stdout on this machine is `gbk` and the Windows console code page is
  `936`, but those were not the primary defect.
- The primary defect was confirmed by source search:
  `??????`, `????`, `????? / ????`, `SIZE_TILT_DIAGNOSTIC ? ?????????`, and
  related execution-plan strings appeared directly in `daily_renderer.py`.
- The fix uses valid Python Unicode escapes for the intended Chinese labels.
- The CLI entry now reconfigures Windows stdout/stderr to UTF-8 and sets the
  interactive console output code page to `65001` as a best-effort fallback.
- The encoding fallback does not touch JSON artifacts, hashes, databases, or
  quant calculations.

## 2. Changed user-visible strings

The following labels now render in the Chinese daily report:

- `执行计划`
- `券商执行`
- `执行方式`
- `券商`
- `被拒绝信号 / 门禁原因`
- `最终有效决策 · 仅显示正式买卖区`
- `决策形成过程`
- `条件概率评估`
- `生产权重`
- `SIZE_TILT_DIAGNOSTIC · 规模倾斜诊断`
- `候选池`
- `优化器输入`
- `最大允许持仓`
- `优化后目标持仓`

Machine status codes remain unchanged:

`PASS`, `PASS_DEGRADED`, `FAIL_BLOCKING`, `BLOCKED`, `NOT_EXECUTED`,
`MANUAL_ONLY`, `BUY`, `SELL`, `HOLD`, `NO_TRADE`.

## 3. Files changed

- `src/personal_alpha_terminal/terminal/daily_renderer.py`
  - Restored corrupted localization strings.
  - Localized candidate-pool and optimizer labels.
  - Preserved all existing machine state codes.
- `src/personal_alpha_terminal/terminal/cli.py`
  - Added `_configure_terminal_utf8()` for Windows-only output encoding.
  - Called it at the start of `main()`.
- `tests/unit/application/test_round12_1_live_semantics.py`
  - Added Unicode renderer regression tests.
  - Added blocked-pipeline, actionable-pipeline, probability-fallback,
    size-unavailable, execution-plan, and LLM SHADOW coverage.
  - Added UTF-8 redirected stdout smoke and GBK CMD-compatible smoke.

## 4. Verification evidence

- Full pytest with `.venv314` and repository-local basetemp:
  `947 passed`
- `quant_critical` marker suite:
  `31 passed`
- Focused Round 12.1 / Unicode tests:
  `17 passed`
- `ruff check .`:
  `All checks passed`
- Strict mypy:
  `Success: no issues found in 417 source files`
- Secret scan:
  `SECRET_SCAN_PASS`
- `python main.py doctor`:
  PASS for runtime, dependencies, DeepSeek, SEC, database, market data,
  intelligence corpus, timezone/calendar, broker API disabled.
- UTF-8 redirected `python main.py --no-refresh daily` smoke:
  stdout decoded as UTF-8, all required Chinese labels present,
  return code `3` because the stored OperationalPolicy is not effective.
- `python main.py operational-policy status`:
  `Status: IDENTITY_MISMATCH`, `Effective: false`.
  No policy was created or renewed.

## 5. Scope and policy status

- Automatic execution remains disabled.
- LLM production influence remains `NONE` / shadow-only.
- OperationalPolicy remains fail-closed and waits for explicit user renewal:
  `python main.py operational-policy create --decision ALLOW_PROVISIONAL`
- This round does not claim live actionable acceptance.
- This round does not begin Round 14.
