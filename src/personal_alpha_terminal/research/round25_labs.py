"""ROUND25 PHASE 8/9/10: research promotion labs with honest evidence labels.

The Classical Champion stays frozen.  Every A/B here uses the same universe
window, the same benchmark, the same cost model and the same execution
assumptions as the champion evaluation; overlays are never allowed to swap
benchmarks or costs to look better.

Because the local database does not contain a multi-decade survivorship-safe
history, every result is labeled ``LIMITED_EVIDENCE_RESEARCH`` and, when the
common window is shorter than the certification minimum,
``INSUFFICIENT_CERTIFIED_HISTORY``.  No result may be called CERTIFIED_ALPHA.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import Price, SecurityMaster

LIMITED_EVIDENCE_RESEARCH = "LIMITED_EVIDENCE_RESEARCH"
INSUFFICIENT_CERTIFIED_HISTORY = "INSUFFICIENT_CERTIFIED_HISTORY"
FORWARD_RESEARCH_CANDIDATE = "FORWARD_RESEARCH_CANDIDATE"

MINIMUM_SESSIONS_FOR_CERTIFICATION = 1260  # ~5 years of daily sessions


@dataclass(frozen=True, slots=True)
class ExperimentRegistryEntry:
    experiment_id: str
    hypothesis: str
    registered_at: str
    factor_definition: dict[str, object]
    parameters: dict[str, object]
    train: tuple[str, str]
    validation: tuple[str, str]
    embargo_sessions: int
    locked_test: tuple[str, str]
    benchmark: str
    cost_model: str
    result: dict[str, object]
    status: str

    def document(self) -> dict[str, object]:
        payload = {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "registered_at": self.registered_at,
            "factor_definition": dict(self.factor_definition),
            "parameters": dict(self.parameters),
            "train": list(self.train),
            "validation": list(self.validation),
            "embargo_sessions": self.embargo_sessions,
            "locked_test": list(self.locked_test),
            "benchmark": self.benchmark,
            "cost_model": self.cost_model,
            "result": dict(self.result),
            "status": self.status,
        }
        return payload


class ExperimentRegistry:
    """Append-only JSONL registry; hypotheses are frozen at registration."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("var/alpha-engine2")

    @property
    def path(self) -> Path:
        return self.root / "round25-experiment-registry.jsonl"

    def register(self, entry: ExperimentRegistryEntry) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(entry.document(), ensure_ascii=False, sort_keys=True) + "\n"
            )

    def entries(self) -> tuple[dict[str, object], ...]:
        if not self.path.exists():
            return ()
        rows: list[dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return tuple(rows)

    @staticmethod
    def frozen_hypothesis_hash(entry: dict[str, object]) -> str:
        canonical = json.dumps(
            {
                key: entry.get(key)
                for key in (
                    "hypothesis",
                    "factor_definition",
                    "parameters",
                    "train",
                    "validation",
                    "embargo_sessions",
                    "locked_test",
                    "benchmark",
                    "cost_model",
                )
            },
            sort_keys=True,
            default=str,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _load_returns(
    session: Session, *, symbols: tuple[str, ...], as_of: datetime
) -> pd.DataFrame:
    rows = session.execute(
        select(SecurityMaster.symbol, Price.trade_date, Price.close)
        .join(Price, Price.stock_id == SecurityMaster.id)
        .where(
            SecurityMaster.symbol.in_(list(symbols)),
            Price.price_type == "unadjusted_ohlcv",
            Price.available_time <= as_of,
            Price.trade_date <= as_of.date(),
        )
        .order_by(SecurityMaster.symbol, Price.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    pivot = frame.pivot_table(
        index="trade_date", columns="symbol", values="close", aggfunc="last"
    ).sort_index()
    pivot.index = pd.to_datetime(pivot.index)
    return pivot.pct_change().dropna(how="all")


def _metrics(
    returns: pd.Series,
    *,
    benchmark_returns: pd.Series | None = None,
    annualization: float = 252.0,
) -> dict[str, float | None]:
    returns = returns.dropna()
    if len(returns) < 2:
        return {
            "net_return": None,
            "cagr": None,
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_drawdown": None,
            "cvar_95": None,
            "tracking_error": None,
            "information_ratio": None,
            "recovery_sessions": None,
            "time_under_water": None,
            "worst_month": None,
            "worst_5d": None,
            "worst_20d": None,
        }
    net = float((1.0 + returns).prod() - 1.0)
    total_vol = float(returns.std(ddof=1) * math.sqrt(annualization))
    years = len(returns) / annualization
    cagr = float((1.0 + net) ** (1.0 / years) - 1.0) if years > 0 and 1 + net > 0 else None
    downside = returns[returns < 0]
    downside_vol = (
        float(downside.std(ddof=1) * math.sqrt(annualization))
        if len(downside) > 1
        else None
    )
    sharpe = float((returns.mean() * annualization) / total_vol) if total_vol > 0 else None
    sortino = (
        float((returns.mean() * annualization) / downside_vol)
        if downside_vol and downside_vol > 0
        else None
    )
    equity = (1.0 + returns).cumprod()
    rolling_max = equity.cummax()
    drawdown = equity / rolling_max - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if cagr is not None and max_drawdown < 0 else None
    cvar_95 = float(-returns.quantile(0.05)) if len(returns) >= 20 else None
    underwater = drawdown < 0
    time_under_water = float(underwater.sum() / len(drawdown)) if len(drawdown) else None
    recovery: int | None = None
    if max_drawdown < 0:
        trough_position = int(np.argmin(drawdown.values))
        after = equity.iloc[trough_position:]
        target_level = float(rolling_max.iloc[trough_position])
        recovered_positions = np.where(after.values >= target_level)[0]
        recovery = int(recovered_positions[0]) if len(recovered_positions) else None
    tracking_error: float | None = None
    information_ratio: float | None = None
    if benchmark_returns is not None:
        common = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
        if len(common) >= 20:
            active = common.iloc[:, 0] - common.iloc[:, 1]
            tracking_error = float(active.std(ddof=1) * math.sqrt(annualization))
            information_ratio = (
                float(
                    active.mean()
                    * annualization
                    / (active.std(ddof=1) * math.sqrt(annualization))
                )
                if active.std(ddof=1) > 0
                else None
            )
    month_returns = returns.resample("ME").apply(lambda window: (1.0 + window).prod() - 1.0)
    worst_month = float(month_returns.min()) if len(month_returns) else None
    worst_5d = float(returns.rolling(5).apply(lambda window: (1.0 + window).prod() - 1.0).min())
    worst_20d = float(returns.rolling(20).apply(lambda window: (1.0 + window).prod() - 1.0).min())
    return {
        "net_return": net,
        "cagr": cagr,
        "volatility": total_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown": max_drawdown,
        "cvar_95": cvar_95,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "recovery_sessions": recovery,
        "time_under_water": time_under_water,
        "worst_month": worst_month,
        "worst_5d": worst_5d,
        "worst_20d": worst_20d,
    }


def _evidence_labels(sessions: int) -> dict[str, object]:
    certification = (
        INSUFFICIENT_CERTIFIED_HISTORY
        if sessions < MINIMUM_SESSIONS_FOR_CERTIFICATION
        else "NOT_CERTIFIABLE_SURVIVORSHIP_UNVERIFIED"
    )
    return {
        "evidence_class": LIMITED_EVIDENCE_RESEARCH,
        "certification": certification,
        "common_window_sessions": sessions,
        "certified_alpha": False,
        "promoted_to_production": False,
        "forward_status": FORWARD_RESEARCH_CANDIDATE,
    }


def evaluate_etf_sleeve_experiments(
    session: Session,
    *,
    as_of: datetime,
    benchmark_symbol: str = "SPY",
    core_symbols: tuple[str, ...] = ("IVV", "VOO", "VTI", "IJR"),
    tactical_symbols: tuple[str, ...] = ("XLK", "XLF", "XLV", "XLE"),
    core_weight: float = 0.25,
    tactical_weight: float = 0.10,
    cost_bps: float = 5.0,
) -> dict[str, object]:
    """Baseline equity-only vs equity+core vs equity+tactical vs core+tactical.

    All legs share the same common window, benchmark and cost assumptions.
    """

    symbols = tuple(
        dict.fromkeys((benchmark_symbol, *core_symbols, *tactical_symbols))
    )
    returns = _load_returns(session, symbols=symbols, as_of=as_of)
    if returns.empty:
        return {
            "status": "ETF_RESEARCH_DATA_UNAVAILABLE",
            "evidence": _evidence_labels(0),
            "experiments": {},
        }
    common = returns.dropna(how="all")
    benchmark_series = common.get(benchmark_symbol)
    if benchmark_series is None or benchmark_series.dropna().empty:
        return {
            "status": "ETF_RESEARCH_BENCHMARK_UNAVAILABLE",
            "evidence": _evidence_labels(len(common)),
            "experiments": {},
        }
    core_returns = common[[symbol for symbol in core_symbols if symbol in common]]
    tactical_returns = common[
        [symbol for symbol in tactical_symbols if symbol in common]
    ]
    entry_cost = cost_bps / 10_000.0

    def experiment(name: str, weights: pd.Series) -> dict[str, object]:
        selected = [symbol for symbol in weights.index if symbol in common.columns]
        if not selected:
            return {
                "metrics": _metrics(pd.Series(dtype=float)),
                "turnover": None,
                "cost": None,
            }
        aligned = common[selected].dropna()
        if aligned.empty or len(aligned) < 20:
            return {"metrics": _metrics(pd.Series(dtype=float)), "turnover": None, "cost": None}
        portfolio = (aligned * weights[selected]).sum(axis=1)
        portfolio.iloc[0] -= entry_cost * sum(weights)
        metrics = _metrics(portfolio, benchmark_returns=benchmark_series)
        metrics["cost_bps"] = cost_bps
        return {
            "metrics": metrics,
            "turnover": None,
            "cost": None,
            "weights": {str(key): float(value) for key, value in weights.items()},
        }

    base_weights = pd.Series({benchmark_symbol: 1.0})
    core_weights = pd.Series(
        {
            symbol: core_weight / max(1, len(core_returns.columns))
            for symbol in core_returns.columns
        }
    )
    core_weights[benchmark_symbol] = 1.0 - core_weights.sum()
    tactical_weights = pd.Series(
        {
            symbol: tactical_weight / max(1, len(tactical_returns.columns))
            for symbol in tactical_returns.columns
        }
    )
    tactical_weights[benchmark_symbol] = 1.0 - tactical_weights.sum()
    combined_weights = pd.Series(
        {
            **{
                symbol: core_weight / max(1, len(core_returns.columns))
                for symbol in core_returns.columns
            },
            **{
                symbol: tactical_weight / max(1, len(tactical_returns.columns))
                for symbol in tactical_returns.columns
            },
        }
    )
    combined_weights[benchmark_symbol] = max(0.0, 1.0 - combined_weights.sum())
    experiments = {
        "baseline_equity_only": experiment("baseline_equity_only", base_weights),
        "equity_plus_etf_core": experiment("equity_plus_etf_core", core_weights),
        "equity_plus_etf_tactical": experiment("equity_plus_etf_tactical", tactical_weights),
        "equity_plus_core_and_tactical": experiment(
            "equity_plus_core_and_tactical", combined_weights
        ),
    }
    core_overlap = None
    if len(core_returns.columns) >= 2:
        correlation = core_returns.corr()
        pairs = {
            f"{left}:{right}": float(correlation.loc[left, right])
            for index, left in enumerate(correlation.columns)
            for right in correlation.columns[index + 1 :]
        }
        core_overlap = {
            "status": "CORRELATION_CLUSTERING_ONLY",
            "look_through": "UNAVAILABLE",
            "max_pairwise_correlation": max(pairs.values()) if pairs else None,
            "pairs": pairs,
        }
    return {
        "status": "ETF_RESEARCH_COMPLETE",
        "evidence": _evidence_labels(len(common)),
        "assumptions": {
            "universe_window": "same common price window for all legs",
            "benchmark": benchmark_symbol,
            "cost_model": f"entry cost {cost_bps} bps; buy-and-hold weights",
            "execution_timing": "single entry at window start",
            "core_weight": core_weight,
            "tactical_weight": tactical_weight,
        },
        "core_overlap": core_overlap,
        "experiments": experiments,
    }
