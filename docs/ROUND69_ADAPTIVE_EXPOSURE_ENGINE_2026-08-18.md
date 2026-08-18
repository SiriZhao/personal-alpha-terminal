# ROUND69 — Adaptive Exposure Engine

Date: 2026-08-18

Starting SHA: `8ab5b18181deebb8724111e84e64e8abe915bd9c`

Final SHA: the separate ROUND69 commit containing this report, recorded in the handoff.

Verdict: `BLOCKED_DATA_QUALITY`

## Design and safety

ROUND69 preserves the Production Quant Champion, long-only/manual execution,
disabled auto execution, all-eligible-candidate optimization, no fixed Top-N or
holdings cap, and zero LLM/Probability formal influence. No Alpha Engine 4 was
created. The controller is shadow-only because ROUND67/68 evidence gates remain
blocked.

`AdaptiveExposureController` makes target gross/net exposure explicit and
records raw target, risk-adjusted target, final target, confidence, dominant
drivers, binding constraints, risk state, participation state, recovery phase,
model version, and config version. Net exposure equals gross exposure for this
long-only controller. Existing `PortfolioConstraints` remain hard limits.

The controller combines regime probabilities, breadth, trend, volatility,
drawdown, opportunity quality, Alpha confidence, concentration, liquidity, risk
budget headroom, correlation, uncertainty, and recovery evidence. It uses
raw-target hysteresis and a bounded step to reduce whipsaw while allowing
re-entry after recovery. Crisis/volatility/liquidity caps are risk-reduction
only; no fixed regime-to-exposure mapping is promoted as final logic.

## Cash attribution

`attribute_cash` distinguishes `INTENTIONAL_RISK_CASH`,
`NO_VALID_OPPORTUNITY_CASH`, `OPTIMIZER_ARTIFACT_CASH`,
`CONSTRAINT_BINDING_CASH`, `ROUNDING_CASH`, and `DATA_QUALITY_CASH`.
Optimizer residuals and blocked data take precedence over optimistic intent, so
implementation artifacts cannot silently become cash drag explanations.

## Before/after economic result

No legitimate before/after economic comparison is available. A complete
PIT/survivorship-safe aligned panel and sealed independent OOS remain absent.
Therefore all real-data values are explicitly `N/A`:

- average exposure: `N/A`
- bull exposure: `N/A`
- normal exposure: `N/A`
- bear exposure: `N/A`
- crisis exposure: `N/A`
- upside capture: `N/A`
- downside capture: `N/A`
- cash drag: `N/A`
- maximum drawdown: `N/A`
- recovery capture: `N/A`

Existing Round61/flagship synthetic participation scenarios remain engineering
counterfactuals only. They are not historical Alpha or promotion evidence and
were not used to activate the new controller.

## Terminal UX

`python main.py adaptive-exposure` displays concise Chinese operator output:
current participation state, suggested/actual exposure, cash, reason for
change, dominant risk, recovery phase, and upside participation. With current
evidence it reports shadow mode, `N/A`, and the data-quality blocker rather than
inventing a position.

## Promotion decision

Final status: `CHALLENGER_ONLY` / `BLOCKED_DATA_QUALITY`; the Production
Champion remains active. Promotion requires materially better normal/bull
participation, acceptable bear/crisis drawdown and downside capture, no stress
regression, acceptable costs/turnover, deterministic tests, and a certifiable
PIT/survivorship-safe locked-OOS comparison. None of those missing evidence
requirements is bypassed here.

## QA

Passed:

- Adaptive exposure/controller tests: `4 passed`.
- Legacy adaptive participation plus Round61 tests: `11 passed`.
- Full Ruff: passed.
- Strict mypy: passed across `507` source files.
- Secret scan: `SECRET_SCAN_PASS`.
- Chinese terminal smoke: passed; output remains shadow/N/A under blocked evidence.

Environment-blocked:

- Flagship `stress-exam` simulation could not write `reports/stress-exam` in
  this managed sandbox (`PermissionError`).
- Full pytest reached 25% before the known managed Windows runtime-write and
  pre-existing `.codex-temp/r7-version-registry` ACL failures. No tests were
  weakened and no runtime state was deleted.

## Changed files

- `src/personal_alpha_terminal/quant_engine/risk/adaptive_exposure.py`
- `src/personal_alpha_terminal/quant_engine/risk/__init__.py`
- `src/personal_alpha_terminal/terminal/cli.py`
- `tests/unit/quant_engine/risk/test_adaptive_exposure.py`
- `docs/ROUND69_ADAPTIVE_EXPOSURE_ENGINE_2026-08-18.md`
