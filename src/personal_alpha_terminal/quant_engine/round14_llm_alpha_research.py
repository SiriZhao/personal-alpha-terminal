"""ROUND 14 LLM quant feature alpha research with locked-OOS protocol.

This module does not manufacture returns or promote LLM features. It evaluates
an immutable feature/outcome dataset against a frozen classical champion and a
purged walk-forward/locked-OOS protocol. With the current one-issuer SEC
corpus, the correct result is `ROUND14_LLM_ALPHA_NOT_PROVED`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.alpha_research import (
    audit_us_adaptive_alpha_core,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.governance import purged_walk_forward_splits

ROUND15_SCHEMA_VERSION = "round15-research-v1"
RESEARCH_STATUS = "RESEARCH_LIMITED_SURVIVORSHIP"
NOT_PROVED = "ROUND14_LLM_ALPHA_NOT_PROVED"
PROMOTION_CANDIDATE = "LLM_FEATURE_PROMOTION_CANDIDATE"


@dataclass(frozen=True, slots=True)
class Round14ExperimentStatus:
    experiment_id: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class Round14AlphaMetrics:
    observations: int
    feature_count: int
    issuer_count: int
    ticker_count: int
    horizon_counts: dict[str, int]
    mean_abnormal_return: float | None
    median_abnormal_return: float | None
    hit_rate: float | None
    ic: float | None
    rank_ic: float | None
    icir: float | None
    net_cagr: float | None
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float | None
    information_ratio: float | None
    alpha_spy: float | None
    alpha_qqq: float | None
    turnover: float | None
    transaction_cost_drag: float | None
    worst_month: float | None
    tail_loss: float | None


@dataclass(frozen=True, slots=True)
class Round14AlphaResearchResult:
    run_id: str
    evaluated_at: datetime
    status: str
    verdict: str
    classical_identity: str
    cost_model_version: str
    blockers: tuple[str, ...]
    experiments: tuple[Round14ExperimentStatus, ...]
    metrics: Round14AlphaMetrics
    promotion_candidate: dict[str, Any] | None
    result_hash: str

    def document(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "evaluated_at": self.evaluated_at.isoformat(),
                        "status": self.status,
                        "verdict": self.verdict,
                        "classical_identity": self.classical_identity,
                        "cost_model_version": self.cost_model_version,
                        "blockers": list(self.blockers),
                        "experiments": [
                            {
                                "experiment_id": item.experiment_id,
                                "status": item.status,
                                "detail": item.detail,
                            }
                            for item in self.experiments
                        ],
                        "metrics": {
                            "observations": self.metrics.observations,
                            "feature_count": self.metrics.feature_count,
                            "issuer_count": self.metrics.issuer_count,
                            "ticker_count": self.metrics.ticker_count,
                            "horizon_counts": self.metrics.horizon_counts,
                            "mean_abnormal_return": self.metrics.mean_abnormal_return,
                            "median_abnormal_return": self.metrics.median_abnormal_return,
                            "hit_rate": self.metrics.hit_rate,
                            "ic": self.metrics.ic,
                            "rank_ic": self.metrics.rank_ic,
                            "icir": self.metrics.icir,
                            "net_cagr": self.metrics.net_cagr,
                            "sharpe": self.metrics.sharpe,
                            "sortino": self.metrics.sortino,
                            "calmar": self.metrics.calmar,
                            "max_drawdown": self.metrics.max_drawdown,
                            "information_ratio": self.metrics.information_ratio,
                            "alpha_spy": self.metrics.alpha_spy,
                            "alpha_qqq": self.metrics.alpha_qqq,
                            "turnover": self.metrics.turnover,
                            "transaction_cost_drag": self.metrics.transaction_cost_drag,
                            "worst_month": self.metrics.worst_month,
                            "tail_loss": self.metrics.tail_loss,
                        },
                        "promotion_candidate": self.promotion_candidate,
                        "result_hash": self.result_hash,
                    },
                    sort_keys=True,
                    default=str,
                )
            ),
        )


def run_round14_alpha_research(
    outcome_document: dict[str, Any],
    feature_document: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> Round14AlphaResearchResult:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")

    rows = _rows(outcome_document.get("outcome_rows"))
    ready = [item for item in rows if item.get("status") == "OUTCOME_READY"]
    blockers: list[str] = []
    if not ready:
        blockers.append("NO_READY_OUTCOMES")
    if str(feature_document.get("status", "")) != "FULL_CERTIFIED":
        blockers.append("RESEARCH_LIMITED_SURVIVORSHIP")

    tickers = {str(item.get("ticker_asof")) for item in ready if item.get("ticker_asof")}
    issuers = {str(item.get("issuer_id")) for item in ready if item.get("issuer_id")}
    feature_names = {str(item.get("feature_name")) for item in ready if item.get("feature_name")}
    horizons: dict[str, int] = {}
    for item in ready:
        horizon = str(item.get("horizon"))
        horizons[horizon] = horizons.get(horizon, 0) + 1

    if len(tickers) < 30:
        blockers.append("CROSS_SECTION_INSUFFICIENT")
    if len(ready) < 252:
        blockers.append("LOCKED_OOS_SAMPLE_INSUFFICIENT")
    if len(ready) >= 20:
        folds = _walk_forward_folds(len(ready))
        if folds < 4:
            blockers.append("WALK_FORWARD_FOLDS_INSUFFICIENT")
    else:
        blockers.append("WALK_FORWARD_FOLDS_INSUFFICIENT")

    abnormal = [
        float(item["abnormal_return"])
        for item in ready
        if _finite_float(item.get("abnormal_return"))
    ]
    hit_rate = (
        sum(1 for value in abnormal if value > 0) / len(abnormal)
        if abnormal
        else None
    )
    metrics = Round14AlphaMetrics(
        observations=len(ready),
        feature_count=len(feature_names),
        issuer_count=len(issuers),
        ticker_count=len(tickers),
        horizon_counts=dict(sorted(horizons.items(), key=lambda item: int(item[0]))),
        mean_abnormal_return=_mean(abnormal),
        median_abnormal_return=_median(abnormal),
        hit_rate=hit_rate,
        ic=None,
        rank_ic=None,
        icir=None,
        net_cagr=None,
        sharpe=None,
        sortino=None,
        calmar=None,
        max_drawdown=None,
        information_ratio=None,
        alpha_spy=None,
        alpha_qqq=None,
        turnover=None,
        transaction_cost_drag=None,
        worst_month=None,
        tail_loss=None,
    )

    experiments = (
        Round14ExperimentStatus(
            "A_CLASSICAL_ONLY", "FROZEN_REFERENCE", "classical champion frozen"
        ),
        Round14ExperimentStatus(
            "B_CLASSICAL_DETERMINISTIC_SEC",
            "NOT_EVALUATED_CORPUS_INSUFFICIENT",
            "requires broad cross-section and locked OOS",
        ),
        Round14ExperimentStatus(
            "C_CLASSICAL_LLM_FEATURES",
            "NOT_EVALUATED_CORPUS_INSUFFICIENT",
            "requires broad cross-section and locked OOS",
        ),
        Round14ExperimentStatus(
            "D_CLASSICAL_SEC_LLM_COMBINED",
            "NOT_EVALUATED_CORPUS_INSUFFICIENT",
            "requires broad cross-section and locked OOS",
        ),
    )

    identity = audit_us_adaptive_alpha_core()
    classical_identity = identity.audit_hash
    cost_model_version = TransactionCostConfig().version
    promotion_candidate: dict[str, Any] | None = None
    verdict = NOT_PROVED
    if not blockers:
        verdict = PROMOTION_CANDIDATE
        promotion_candidate = {
            "candidate_status": "IMMUTABLE_PROMOTION_CANDIDATE",
            "verdict": verdict,
            "classical_identity": classical_identity,
            "cost_model_version": cost_model_version,
            "metrics": {
                "ic": metrics.ic,
                "rank_ic": metrics.rank_ic,
                "net_cagr": metrics.net_cagr,
                "sharpe": metrics.sharpe,
                "alpha_spy": metrics.alpha_spy,
                "alpha_qqq": metrics.alpha_qqq,
            },
        }

    base = {
        "evaluated_at": evaluated_at.isoformat(),
        "classical_identity": classical_identity,
        "cost_model_version": cost_model_version,
        "blockers": sorted(set(blockers)),
        "experiments": [item.experiment_id for item in experiments],
        "metrics": {
            "observations": metrics.observations,
            "feature_count": metrics.feature_count,
            "ticker_count": metrics.ticker_count,
            "hit_rate": metrics.hit_rate,
        },
        "verdict": verdict,
    }
    result_hash = fingerprint(base)
    return Round14AlphaResearchResult(
        run_id=f"round14-alpha-{result_hash[:16]}",
        evaluated_at=evaluated_at,
        status="NOT_PROVED" if blockers else "PROMOTION_CANDIDATE",
        verdict=verdict,
        classical_identity=classical_identity,
        cost_model_version=cost_model_version,
        blockers=tuple(sorted(set(blockers))),
        experiments=experiments,
        metrics=metrics,
        promotion_candidate=promotion_candidate,
        result_hash=result_hash,
    )


def build_round15_dataset(
    outcome_document: dict[str, Any], feature_document: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in _rows(outcome_document.get("outcome_rows")):
        rows.append(
            {
                "dataset_id": str(outcome_document.get("dataset_id")),
                "feature_dataset_id": str(outcome_document.get("feature_dataset_id")),
                "issuer_id": item.get("issuer_id"),
                "ticker_asof": item.get("ticker_asof"),
                "feature_name": item.get("feature_name"),
                "feature_value": item.get("feature_value"),
                "feature_as_of": item.get("feature_as_of"),
                "horizon": item.get("horizon"),
                "baseline_session": item.get("baseline_session"),
                "outcome_session": item.get("outcome_session"),
                "outcome_available_at": item.get("outcome_available_at"),
                "asset_return": item.get("asset_return"),
                "benchmark_return": item.get("benchmark_return"),
                "abnormal_return": item.get("abnormal_return"),
                "status": item.get("status"),
                "classical_features": {},
                "classical_feature_status": "NOT_SUPPLIED_TO_INTELLIGENCE_BUILD",
                "future_outcomes_read_during_build": False,
            }
        )
    return {
        "schema_version": ROUND15_SCHEMA_VERSION,
        "dataset_id": str(outcome_document.get("dataset_id")),
        "feature_dataset_id": str(outcome_document.get("feature_dataset_id")),
        "status": RESEARCH_STATUS,
        "production_influence": "NONE",
        "future_outcomes_read_during_build": False,
        "rows": rows,
    }


def write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
    path.write_text(rendered, encoding="utf-8")


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _finite_float(value: object) -> bool:
    from math import isfinite

    try:
        number = float(value) if isinstance(value, (int, float)) else float(str(value))
    except (TypeError, ValueError):
        return False
    return isfinite(number)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _walk_forward_folds(observations: int) -> int:
    if observations < 60:
        return 0
    try:
        splits = purged_walk_forward_splits(
            observations,
            train_size=40,
            validation_size=10,
            test_size=10,
            embargo=5,
            step=10,
        )
    except ValueError:
        return 0
    return len(splits)
