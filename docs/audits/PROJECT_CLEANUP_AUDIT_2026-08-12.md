# Personal Alpha Terminal — Project Cleanup Audit 2026-08-12

## Executive Summary

The repository is a working Python quantitative trading terminal. The committed baseline is
stable (`e53fad5`), and the working tree additionally contains a substantial, uncommitted
follow-on feature set (historical research providers, SEC EDGAR text acquisition, provisional
operational mode) with its own tests. This audit preserved all uncommitted work, removed only
regenerable caches/temp artifacts, and identified one P0 governance decision that must be made
before any of the uncommitted feature set is considered production-ready.

Final verdict: `CLEAN_WITH_KNOWN_DEBT`.

## Repository Before

Measured before cleanup:

- Git HEAD: `e53fad5` on `codex/quant-core-closure-part1`
- Tracked files: 659
- Source `.py` files: 372 (`src`), 150 (`tests`), 25 (`scripts`)
- Docs files: 191 total across all subdirectories; 68 tracked; 63 root-level docs, of which 27
  are untracked session reports (3 new audit files were added during this round)
- Reports runtime files: ~737 (git-ignored run snapshots/evidence)
- Runtime caches before cleanup:
  - `.tmp` ~883 MB (mypy/pytest basetemp/fixture copies)
  - `.mypy_cache` ~37 MB
  - `.pytest-tmp` ~20 MB
  - `__pycache__` ~17 MB (59 directories)
  - `.pytest_cache` / `.ruff_cache` small

## Architecture (verified, not inferred)

Formal runtime entry points:

- `main.py` -> `personal_alpha_terminal.terminal.cli.main`
- `personal_alpha_terminal.console.main` (package script `pat` / `pat-console`)
- `run_terminal.bat` -> `.venv\Scripts\python.exe main.py`

Daily chain (single production path):

`Calendar -> Data -> PIT -> LLM Intelligence (optional) -> Feature -> Factor -> Signal ->
Probability -> Portfolio -> Risk -> Decision -> Execution Plan -> Persistence`.

The application service `run_daily_quant_report()` invokes `DailyQuantOrchestrator`; the renderer
consumes one typed `DailyQuantResult`. The working tree also wires
`_ensure_provisional_operational_approval()` into the CLI daily entry and lets
`ProductionDailyWorkflow` run in `operational_mode`.

## Tech Debt Found

### P0

- `TECH-001`: The uncommitted working tree changes production semantics: a daily run
  automatically produces a `provisional-operational-*` approval artifact
  (`cli._ensure_provisional_operational_approval`) and the daily run then classifies as
  `PROVISIONAL_ACTIONABLE` with actual BUY recommendations, replacing the previously observed
  `VALID_ANALYSIS_NON_ACTIONABLE` behavior. The registry explicitly forbids
  `full_research_certified=True` and keeps `research_certification_state=NOT_CERTIFIABLE`, so it
  is not a forged full approval. The decision to keep or disable this path is a product/risk
  governance decision and is preserved unchanged for the user.

### P1

- `TECH-002`: 27 root-level report-style docs are untracked and not yet indexed under
  `docs/reports`; they must be reviewed and committed or archived deliberately. Not deleted.
- `TECH-003`: Runtime report/data directories (`reports/`, `var/`) are git-ignored but continue
  to grow (10.6 MB / 67 MB); retention is handled by `core.retention`, but no policy review was
  part of this round.

### P2

- `TECH-004`: Legacy `src/personal_alpha_terminal/cli.py` is not the formal entry point; its only
  in-tree caller is `src/personal_alpha_terminal/scripts/daily_pipeline.py`. Kept because it is
  packaged code with no verified removal contract.
- `TECH-005`: `src/personal_alpha_terminal/scripts/` duplicates research CLI capability that also
  exists as root `scripts/*` and the terminal CLI. Only `run_alpha_discovery` and
  `update_daily_data` have direct test coverage. Kept pending a dedicated cleanup round.
- `TECH-006`: Duplicate module names exist in separate packages (`models.event_study` vs
  `intelligence.event_study`, `alpha_discovery.walk_forward` vs `backtest.walk_forward`,
  `models.portfolio_risk` vs `quant_engine.risk.portfolio_risk`). Reference counts show the
  `quant_engine`/`intelligence` variants are the active ones; no deletion performed this round.
- `TECH-007`: Two local virtual environments (`.venv` ~1.1 GB, `.venv314` ~0.9 GB) are both
  git-ignored; a single canonical env would reduce local disk use.

## Duplicate Implementations

Documented above as TECH-004/005/006. All duplicate-looking modules remain untouched; the active
path is the terminal CLI + `quant_engine`/`intelligence` packages.

## Dead Code Removed

None. No source, test, config, migration, or documentation file was deleted.

## Files Archived

None. All uncommitted source/tests/docs/scripts/artifacts remain in place for review.

## Dependency Cleanup

No dependency was removed or upgraded. `pyproject.toml` already separates optional groups
(`ai`, `market-data`, `postgres`, `research`, `quant-backends`, `qlib-research`, `dev`);
`openai` remains the AI optional extra only because the provider abstraction supports OpenAI
compatible endpoints; DeepSeek runs through that same client. No unused dependency was proven,
so none was changed.

## Config Cleanup

No config semantics were changed. `.gitignore` working-tree change (`.pytest-tmp/`) is safe and
was retained. Root `config.yaml`, `.env.example`, `.env.production.example`, `config/` research
contracts, and `data/validation/historical_validation_spec_v1.json` were untouched.

## Documentation Cleanup

This report is the audit record. `docs/REPOSITORY_GUIDE.md` and `docs/TECH_DEBT.md` were created
to give future maintainers a stable orientation and a single debt list. Existing
`docs/ARCHITECTURE.md` remains the architecture truth source; this audit found no drift in its
committed description of the formal chain. The 27 untracked docs were not moved or edited because
their review belongs to the pending uncommitted feature set.

## Security

`scripts/secret_scan.py`: `SECRET_SCAN_PASS` (generic token patterns over tracked + untracked
files). A targeted check confirmed the real `DEEPSEEK_API_KEY` value appears nowhere in the
tracked or staged content. No `.env` exists in the repo root; `config.yaml` contains no secrets.

## Quant Regression

Full suite before cleanup: 727 passed. After cache/temp cleanup: 727 passed (the single rerun
failure was the Windows pytest basetemp parent-directory issue, resolved by recreating `.tmp`
and rerunning). Ruff: pass. Strict mypy: pass (372 source files).

Daily run smoke before and after cleanup:

- Before: `PROVISIONAL_ACTIONABLE`, 3 actions, 9 provisional operational signals.
- After: identical factor rows, 9 provisional operational signals, same gate path.

No quant, data, PIT, factor, probability, portfolio, or risk semantic change was introduced by
this audit.

## Data Regression

No data file, provider priority, cache policy, PIT rule, corporate-action rule, or provenance
storage was modified. Only regenerable Python/mypy/pytest caches and basetemp dirs were removed.

## Test Results

- Baseline (working tree, before cleanup): 727 passed.
- After cleanup: 727 passed (`python -m pytest -q --basetemp=.tmp/pytest-cleanup`).
- Ruff: `All checks passed`.
- Mypy strict: `Success: no issues found in 372 source files`.
- Secret scan: `SECRET_SCAN_PASS`.

## Repository After

- `.tmp`, `.mypy_cache`, `.pytest-tmp`, `.pytest_cache`, `.ruff_cache`, and all 59 in-tree
  `__pycache__` dirs removed (~958 MB regenerable space).
- After final verification, test re-created caches were removed a second time so the delivered
  working tree is clean of regenerable artifacts.
- Tracked files unchanged at 659; no tracked file was modified by this audit except the already
  pending `.gitignore` working-tree line.

## Disk Reduction

Regenerable cache/temp space removed across both passes: approximately 958 MB (`.tmp` 883 MB,
`.mypy_cache` 37 MB, `.pytest-tmp` 20 MB, `__pycache__` 17 MB, plus small caches). No
meaningful data was deleted; all removal targets were git-ignored and reproducible.

## Remaining Tech Debt

See `docs/TECH_DEBT.md`. The single decision required before closing the uncommitted feature set
is TECH-001 (keep provisional operational recommendations as designed, gate them behind explicit
user opt-in, or revert the semantic change while keeping the research/EDGAR work).

## Final Verdict

`CLEAN_WITH_KNOWN_DEBT`
