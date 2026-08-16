"""ROUND 7: gated historical research rerun.

The rerun only executes after the historical PIT dataset is certified
(HISTORICAL_PIT_CERTIFIED).  A LIMITED verdict refuses to rerun and records the
blockers honestly — no fabricated certification and no rerun on uncertified
data.  The rerun reuses the deterministic ROUND 4 factor/quantile/walk-forward/
probability/portfolio machinery against a certified provider package.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, cast

import pandas as pd

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.historical_pit.certification import (
    HistoricalPitCertification,
    HistoricalPitVerdict,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetPackage,
    SecurityType,
)
from personal_alpha_terminal.quant_engine.round4_research import (
    ResearchIdentity,
    build_factor_panel,
    build_labeled_panel,
    factor_diagnostics,
    rebalance_dates,
    simple_portfolio_ab,
    temporal_splits,
    train_probability_calibration,
)


@dataclass(frozen=True, slots=True)
class HistoricalResearchRerun:
    run_id: str
    verdict: HistoricalPitVerdict
    research_data_version: str
    executed: bool
    blockers: tuple[str, ...]
    diagnostics: dict[str, Any] | None
    walk_forward: dict[str, Any] | None
    probability: dict[str, Any] | None
    portfolio_ab: dict[str, Any] | None
    round4_comparison: dict[str, Any] | None
    run_at: datetime

    def document(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "verdict": self.verdict.value,
            "research_data_version": self.research_data_version,
            "executed": self.executed,
            "blockers": list(self.blockers),
            "diagnostics": self.diagnostics,
            "walk_forward": self.walk_forward,
            "probability": self.probability,
            "portfolio_ab": self.portfolio_ab,
            "round4_comparison": self.round4_comparison,
            "run_at": self.run_at.isoformat(),
        }
        return cast(dict[str, Any], __import__("json").loads(
            __import__("json").dumps(payload, default=str, sort_keys=True)
        ))

    @property
    def rerun_hash(self) -> str:
        return fingerprint(self.document())


def price_panel_from_package(
    package: ResearchDatasetPackage,
    *,
    benchmark: str = "SPY",
    history_start: date | None = None,
) -> pd.DataFrame:
    """Build a ROUND 4-compatible price panel from a certified provider package.

    Only RAW rows (or rows whose PIT total-return vintage is available at the
    package cutoff) are used; no future data and no current-adjusted prices.
    """
    from personal_alpha_terminal.quant_engine.research_dataset import AdjustmentKind

    benchmark_ids = {
        item.permanent_security_id
        for item in package.securities
        if item.security_type is SecurityType.BENCHMARK
    }
    by_security = {item.permanent_security_id: item for item in package.securities}
    rows: list[dict[str, object]] = []
    start_date = history_start
    for price in package.prices:
        security = by_security.get(price.permanent_security_id)
        if security is None:
            continue
        if price.available_at > package.cutoff:
            continue
        if price.adjustment_kind is AdjustmentKind.CURRENT_FINAL_ADJUSTED:
            continue
        if price.adjustment_kind is AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE:
            if (
                price.total_return_available_at is None
                or price.total_return_available_at > package.cutoff
            ):
                continue
            close = price.total_return_value
        else:
            close = price.close
        if close is None or close <= 0:
            continue
        if start_date is not None and price.observation_date < start_date:
            continue
        role = (
            "reference"
            if price.permanent_security_id in benchmark_ids
            or price.ticker in {benchmark, "QQQ"}
            else "alpha"
        )
        rows.append(
            {
                "permanent_security_id": price.permanent_security_id,
                "ticker": price.ticker,
                "exchange": price.exchange,
                "trade_date": price.observation_date,
                "available_time": price.available_at,
                "close": float(close),
                "volume": float(price.volume),
                "role": role,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("certified package contains no rerunnable price rows")
    return frame


def run_historical_research(
    certification: HistoricalPitCertification,
    package: ResearchDatasetPackage,
    *,
    benchmark: str = "SPY",
    horizon: int = 21,
    history_start: date | None = None,
    rules: Any = None,
    strategy_config: Any = None,
    round4_baseline: dict[str, Any] | None = None,
    run_at: datetime | None = None,
) -> HistoricalResearchRerun:
    """Run the historical research suite only when the dataset is certified."""
    from datetime import UTC

    now = run_at or datetime.now(UTC)
    run_id = f"round7-{now.strftime('%Y%m%dT%H%M%SZ')}"
    if certification.verdict is not HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED:
        return HistoricalResearchRerun(
            run_id=run_id,
            verdict=certification.verdict,
            research_data_version=certification.version.research_data_version,
            executed=False,
            blockers=certification.blockers,
            diagnostics=None,
            walk_forward=None,
            probability=None,
            portfolio_ab=None,
            round4_comparison=None,
            run_at=now,
        )

    from personal_alpha_terminal.data.us_market.broad_universe import EligibilityRules

    configured_rules = rules or EligibilityRules()
    try:
        price_panel = price_panel_from_package(
            package,
            benchmark=benchmark,
            history_start=history_start,
        )
        dates = rebalance_dates(
            price_panel,
            end_date=package.as_of,
            horizon=horizon,
        )
        if len(dates) < 6:
            raise ValueError("round7 research requires at least six rebalance dates")
        factor_panel = build_factor_panel(
            price_panel,
            dates=dates,
            config=strategy_config,
            rules=configured_rules,
        )
        labeled_panel = build_labeled_panel(
            price_panel,
            factor_panel,
            benchmark=benchmark,
            horizon=horizon,
        )
        diagnostics = factor_diagnostics(labeled_panel, horizon=horizon)
        train, calibration, oos = temporal_splits(dates)
        identity = ResearchIdentity(
            strategy_id="USAdaptiveAlphaCoreV1",
            strategy_version="1.0.0",
            model_id="Round7LogisticCalibrationV1",
            feature_schema_hash=fingerprint(
                {
                    "momentum_12_1__normalized",
                    "trend_slope__normalized",
                    "volatility__normalized",
                    "composite",
                    "expected_alpha",
                }
            ),
            factor_identity="USAdaptiveAlphaCoreV1Config().parameter_fingerprint",
            universe_identity=certification.version.universe_hash,
            benchmark=benchmark,
            holding_horizon=horizon,
            transaction_cost_assumption="commission+spread+slippage+impact bps",
            data_version=certification.version.research_data_version,
            config_hash=configured_rules.fingerprint,
        )
        calibration_evidence = train_probability_calibration(
            labeled_panel,
            identity=identity,
            train_period=train,
            calibration_period=calibration,
            oos_period=oos,
        )
        ab = simple_portfolio_ab(
            labeled_panel,
            price_panel=price_panel,
            dates=oos,
            benchmark=benchmark,
        )
    except (ArithmeticError, FloatingPointError, RuntimeError, TypeError, ValueError) as error:
        return HistoricalResearchRerun(
            run_id=run_id,
            verdict=certification.verdict,
            research_data_version=certification.version.research_data_version,
            executed=False,
            blockers=(f"RESEARCH_RERUN_FAILED: {error}",),
            diagnostics=None,
            walk_forward=None,
            probability=None,
            portfolio_ab=None,
            round4_comparison=None,
            run_at=now,
        )

    walk_forward: dict[str, Any] = {
        "train_start": train[0].isoformat(),
        "train_end": train[1].isoformat(),
        "calibration_start": calibration[0].isoformat(),
        "calibration_end": calibration[1].isoformat(),
        "oos_start": oos[0].isoformat(),
        "oos_end": oos[1].isoformat(),
        "rebalance_dates": len(dates),
        "factor_rows": int(len(labeled_panel)),
    }
    probability: dict[str, Any] = {}
    if calibration_evidence is not None:
        probability = {
            "brier_score": calibration_evidence.brier_score,
            "baseline_brier_score": calibration_evidence.baseline_brier_score,
            "log_loss": calibration_evidence.log_loss,
            "expected_calibration_error": calibration_evidence.expected_calibration_error,
            "roc_auc": calibration_evidence.roc_auc,
            "base_rate": calibration_evidence.base_rate,
            "training_samples": calibration_evidence.training_samples,
            "calibration_samples": calibration_evidence.calibration_samples,
            "oos_samples": calibration_evidence.oos_samples,
        }
    ab_doc: dict[str, Any] = {}
    if ab is not None:
        ab_doc = asdict(ab)
    composite_ic = next(
        (item.rank_ic for item in diagnostics if item.factor == "composite"),
        None,
    )
    comparison: dict[str, Any] | None = None
    if round4_baseline is not None:
        comparison = {
            "baseline_verdict": "ROUND4_PRODUCTION_READY_DEGRADED_RESEARCH",
            "round4_rank_ic": round4_baseline.get("rank_ic"),
            "round7_rank_ic": composite_ic,
            "round4_oos_net_alpha": round4_baseline.get("oos_net_alpha"),
            "round7_oos_classical_net_return": (
                ab.classical_net_return
                if ab is not None and ab.classical_net_return is not None
                else None
            ),
            "round7_oos_probability_net_return": (
                ab.probability_net_return
                if ab is not None and ab.probability_net_return is not None
                else None
            ),
            "survivorship_classification": (
                certification.survivorship.classification.value
            ),
        }
    return HistoricalResearchRerun(
        run_id=run_id,
        verdict=certification.verdict,
        research_data_version=certification.version.research_data_version,
        executed=True,
        blockers=(),
        diagnostics=(
            {item.factor: asdict(item) for item in diagnostics} if diagnostics else None
        ),
        walk_forward=walk_forward,
        probability=probability,
        portfolio_ab=ab_doc,
        round4_comparison=comparison,
        run_at=now,
    )
