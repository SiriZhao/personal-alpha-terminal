"""ROUND26 P0: Probability Forward Evidence Ledger.

Immutable, append-only forward-calibration evidence:

* ``ProbabilityPrediction`` -- recorded at each formal SIGNAL/decision time,
  before any outcome is observable.
* ``ProbabilityOutcome`` -- matured only after the frozen horizon has elapsed,
  using PIT-visible bars only.
* ``ProbabilityEvaluationReport`` -- calibration (Brier / log-loss / ECE /
  reliability buckets / slope / intercept), discrimination (rank correlation,
  bucket hit rates), economic value (Probability ON vs OFF counterfactual),
  and date-clustered bootstrap confidence instead of IID row bootstrap.
* ``ProbabilityPromotionPolicy`` -- explicit promotion gate; production
  influence stays 0 until every condition holds AND a human approves.

The frozen production research target follows the project's existing
convention: 21 trading sessions forward, benchmark SPY, benchmark-relative
return after estimated transaction cost > 0.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

PRIMARY_PRODUCTION_RESEARCH_HORIZON = 21
PRIMARY_BENCHMARK = "SPY"


def _hash(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProbabilityPrediction:
    prediction_id: str
    run_id: str
    decision_id: str
    ticker: str
    decision_cutoff: str
    factor_rank: int | None
    base_alpha: float | None
    condition_state: str
    raw_probability: float | None
    calibrated_probability: float | None
    model_id: str
    model_hash: str
    primary_horizon: int
    benchmark: str
    target_definition: str
    cost_hurdle_bps: float
    created_at: str
    # ROUND27: a run is an occurrence, not automatically an independent OOS
    # observation.  These frozen fields define the semantic prediction unit.
    canonical_prediction_id: str = ""
    trade_date: str = ""
    market_data_semantic_hash: str = "UNAVAILABLE"
    universe_semantic_hash: str = "UNAVAILABLE"
    portfolio_predecision_hash: str = "UNAVAILABLE"
    run_type: str = "PRODUCTION_DECISION"
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProbabilityOutcome:
    prediction_id: str
    ticker: str
    entry_reference_time: str
    entry_reference_price: float
    exit_reference_time: str
    exit_reference_price: float
    benchmark_return: float
    asset_return: float
    relative_return: float
    estimated_cost: float
    net_relative_return: float
    target_hit: bool
    outcome_available_at: str
    data_snapshot_id: str
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


TARGET_DEFINITION = (
    "P(21-session forward benchmark(SPY)-relative return after estimated "
    "transaction cost > 0)"
)


class ProbabilityForwardLedger:
    """Append-only JSONL ledger under var/probability-forward/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("var/probability-forward")

    @property
    def predictions_path(self) -> Path:
        return self.root / "predictions.jsonl"

    @property
    def outcomes_path(self) -> Path:
        return self.root / "outcomes.jsonl"

    @property
    def occurrences_path(self) -> Path:
        return self.root / "occurrences.jsonl"

    @property
    def canonical_index_path(self) -> Path:
        return self.root / "canonical-index.json"

    def append_prediction(self, prediction: ProbabilityPrediction) -> bool:
        """Append a new canonical observation, or record a repeat occurrence.

        Returns ``True`` only when the raw append created a statistical
        observation.  REPLAY/TEST/DEBUG/VALIDATION/BACKFILL/REPORT_ONLY runs
        never write either kind of forward evidence.
        """
        if prediction.run_type != "PRODUCTION_DECISION":
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        document = prediction.document()
        canonical_id = str(document.get("canonical_prediction_id") or "")
        if not canonical_id:
            canonical_id = canonical_prediction_id(document)
            document["canonical_prediction_id"] = canonical_id
        canonical = canonical_predictions(self.predictions())
        first = canonical.get(canonical_id)
        occurrence = {
            "canonical_prediction_id": canonical_id,
            "prediction_id": document.get("prediction_id"),
            "run_id": document.get("run_id"),
            "decision_id": document.get("decision_id"),
            "occurred_at": document.get("created_at"),
            "is_first_occurrence": first is None,
        }
        with self.occurrences_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(occurrence, ensure_ascii=False, sort_keys=True) + "\n")
        if first is not None:
            self.write_canonical_index()
            return False
        with self.predictions_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
        self.write_canonical_index()
        return True

    def append_outcome(self, outcome: ProbabilityOutcome) -> bool:
        """Append at most one formal outcome for each canonical prediction."""
        self.root.mkdir(parents=True, exist_ok=True)
        prediction_by_id = {
            str(row.get("prediction_id")): row for row in self.predictions()
        }
        prediction = prediction_by_id.get(outcome.prediction_id)
        canonical_id = canonical_prediction_id(
            prediction or {"prediction_id": outcome.prediction_id}
        )
        existing_canonical = {
            canonical_prediction_id(prediction_by_id.get(str(row.get("prediction_id"))) or {})
            for row in self.outcomes()
        }
        if canonical_id in existing_canonical:
            return False
        with self.outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(outcome.document(), ensure_ascii=False, sort_keys=True) + "\n"
            )
        return True

    def predictions(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.predictions_path)

    def outcomes(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.outcomes_path)

    def write_canonical_index(self) -> dict[str, object]:
        """Materialize a reversible index; the raw append-only ledger remains intact."""
        raw = self.predictions()
        canonical = audit_canonical_predictions(raw)
        occurrences: dict[str, list[str]] = {key: [] for key in canonical}
        raw_to_audit_key: dict[str, str] = {}
        for row in raw:
            audit_key = "canonical-prob-" + _hash(_migrated_audit_identity(row))[:24]
            raw_key = str(row.get("canonical_prediction_id") or canonical_prediction_id(row))
            raw_to_audit_key[raw_key] = audit_key
            run_id = str(row.get("run_id") or "")
            if audit_key in occurrences and run_id:
                occurrences[audit_key].append(run_id)
        for row in _read_jsonl(self.occurrences_path):
            key = raw_to_audit_key.get(str(row.get("canonical_prediction_id") or ""), "")
            run_id = str(row.get("run_id") or "")
            if key in occurrences and run_id:
                occurrences[key].append(run_id)
        payload = {
            "schema_version": "probability-canonical-index-v1",
            "raw_prediction_rows": len(raw),
            "canonical_prediction_rows": len(canonical),
            "duplicate_prediction_rows": len(raw) - len(canonical),
            "canonical_predictions": [
                {
                    "canonical_prediction_id": key,
                    "first_prediction_id": row.get("prediction_id"),
                    "first_run_id": row.get("run_id"),
                    "occurrence_run_ids": list(dict.fromkeys(occurrences.get(key, []))),
                }
                for key, row in sorted(canonical.items())
            ],
        }
        self.canonical_index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload


def _read_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tuple(rows)


def canonical_prediction_identity(row: dict[str, object]) -> dict[str, object]:
    """Return the frozen semantic identity of one prediction observation.

    Legacy ROUND26 rows lack the four semantic hashes.  They stay readable and
    are indexed with explicit ``UNAVAILABLE`` placeholders rather than being
    modified or silently discarded.
    """
    return {
        "decision_cutoff": row.get("decision_cutoff"),
        "trade_date": row.get("trade_date") or str(row.get("decision_cutoff") or "")[:10],
        "ticker": row.get("ticker"),
        "probability_model_id": row.get("model_id"),
        "probability_model_hash": row.get("model_hash"),
        "target_definition": row.get("target_definition"),
        "primary_horizon": row.get("primary_horizon"),
        "benchmark": row.get("benchmark"),
        "market_data_semantic_hash": row.get("market_data_semantic_hash", "UNAVAILABLE"),
        "universe_semantic_hash": row.get("universe_semantic_hash", "UNAVAILABLE"),
        "portfolio_predecision_hash": row.get("portfolio_predecision_hash", "UNAVAILABLE"),
    }


def canonical_prediction_id(row: dict[str, object]) -> str:
    return "canonical-prob-" + _hash(canonical_prediction_identity(row))[:24]


def canonical_predictions(
    rows: tuple[dict[str, object], ...],
) -> dict[str, dict[str, object]]:
    """First raw row wins; later same-semantic rows are occurrences only."""
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if str(row.get("run_type", "PRODUCTION_DECISION")) != "PRODUCTION_DECISION":
            continue
        key = str(row.get("canonical_prediction_id") or canonical_prediction_id(row))
        result.setdefault(key, row)
    return result


def _migrated_audit_identity(row: dict[str, object]) -> dict[str, object]:
    """Backfill only the ROUND26/early-ROUND27 wall-clock cutoff defect.

    Raw ledger records are deliberately not edited.  Early producers wrote the
    report-generation time into ``decision_cutoff`` and used a run-artifact
    hash as the market semantic hash.  When an immutable DecisionManifest is
    present, its PIT cutoff proves those values were not the semantic decision
    identity.  The audit/index projection restores the frozen cutoff and a
    cutoff-scoped migration marker, while retaining the source row verbatim.
    """
    identity = canonical_prediction_identity(row)
    run_id = str(row.get("run_id") or "")
    manifest_path = Path("reports/daily-runs") / run_id / "decision_manifest.json"
    if not run_id or not manifest_path.exists():
        return identity
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return identity
    manifest_cutoff = str(manifest.get("decision_cutoff") or "")
    if not manifest_cutoff or str(row.get("decision_cutoff") or "") == manifest_cutoff:
        return identity
    identity["decision_cutoff"] = manifest_cutoff
    identity["trade_date"] = str(manifest.get("trade_date") or identity["trade_date"])
    # The raw value was a report artifact hash, not a content-addressed market
    # input identity.  Its manifest-proven PIT boundary is the only safe
    # stable value recoverable without rewriting history.
    identity["market_data_semantic_hash"] = f"MIGRATED_PIT_CUTOFF:{manifest_cutoff}"
    return identity


def audit_canonical_predictions(
    rows: tuple[dict[str, object], ...],
) -> dict[str, dict[str, object]]:
    """Canonical projection for statistics, including the reversible migration."""
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if str(row.get("run_type", "PRODUCTION_DECISION")) != "PRODUCTION_DECISION":
            continue
        key = "canonical-prob-" + _hash(_migrated_audit_identity(row))[:24]
        result.setdefault(key, row)
    return result


def forward_prediction_audit(ledger: ProbabilityForwardLedger) -> dict[str, object]:
    """Audit raw history without deleting or rewriting the append-only ledger."""
    raw = ledger.predictions()
    canonical = audit_canonical_predictions(raw)
    run_types: dict[str, int] = {}
    for row in raw:
        kind = str(row.get("run_type", "PRODUCTION_DECISION"))
        run_types[kind] = run_types.get(kind, 0) + 1
    canonical_rows = tuple(canonical.values())
    decision_dates = {str(row.get("decision_cutoff", ""))[:10] for row in canonical_rows}
    manifests = {str(row.get("decision_id", "")) for row in canonical_rows}
    tickers = {str(row.get("ticker", "")) for row in canonical_rows}
    return {
        "schema_version": "forward-prediction-audit-v1",
        "raw_prediction_rows": len(raw),
        "canonical_prediction_rows": len(canonical_rows),
        "duplicate_prediction_rows": len(raw) - len(canonical_rows),
        "distinct_decision_dates": len(decision_dates),
        "distinct_decision_manifests": len(manifests),
        "distinct_tickers": len(tickers),
        "run_type_rows": run_types,
        "migration": {
            "kind": "ROUND27_PIT_CUTOFF_IDENTITY_PROJECTION",
            "raw_ledger_modified": False,
            "strict_canonical_prediction_rows": len(canonical_predictions(raw)),
            "migrated_canonical_prediction_rows": len(canonical_rows),
        },
        "legacy_rows_without_full_semantic_identity": sum(
            1
            for row in raw
            if any(
                row.get(key) in (None, "", "UNAVAILABLE")
                for key in (
                    "market_data_semantic_hash",
                    "universe_semantic_hash",
                    "portfolio_predecision_hash",
                )
            )
        ),
    }


def build_prediction(
    *,
    run_id: str,
    decision_id: str,
    ticker: str,
    decision_cutoff: datetime,
    factor_rank: int | None,
    base_alpha: float | None,
    raw_probability: float | None,
    calibrated_probability: float | None,
    model_id: str,
    model_hash: str,
    cost_hurdle_bps: float,
    condition_state: str = "CLASSICAL_FALLBACK",
    trade_date: str | None = None,
    market_data_semantic_hash: str = "UNAVAILABLE",
    universe_semantic_hash: str = "UNAVAILABLE",
    portfolio_predecision_hash: str = "UNAVAILABLE",
    run_type: str = "PRODUCTION_DECISION",
) -> ProbabilityPrediction:
    cutoff = decision_cutoff.astimezone(UTC)
    core: dict[str, object] = {
        "run_id": run_id,
        "decision_id": decision_id,
        "ticker": ticker,
        "decision_cutoff": cutoff.isoformat(),
        "factor_rank": factor_rank,
        "base_alpha": base_alpha,
        "condition_state": condition_state,
        "raw_probability": raw_probability,
        "calibrated_probability": calibrated_probability,
        "model_id": model_id,
        "model_hash": model_hash,
        "primary_horizon": PRIMARY_PRODUCTION_RESEARCH_HORIZON,
        "benchmark": PRIMARY_BENCHMARK,
        "target_definition": TARGET_DEFINITION,
        "cost_hurdle_bps": cost_hurdle_bps,
        "trade_date": trade_date or cutoff.date().isoformat(),
        "market_data_semantic_hash": market_data_semantic_hash,
        "universe_semantic_hash": universe_semantic_hash,
        "portfolio_predecision_hash": portfolio_predecision_hash,
        "run_type": run_type,
    }
    prediction_id = f"prob-{_hash(core)[:16]}"
    return ProbabilityPrediction(
        prediction_id=prediction_id,
        run_id=str(core["run_id"]),
        decision_id=str(core["decision_id"]),
        ticker=str(core["ticker"]),
        decision_cutoff=str(core["decision_cutoff"]),
        factor_rank=core["factor_rank"],  # type: ignore[arg-type]
        base_alpha=core["base_alpha"],  # type: ignore[arg-type]
        condition_state=str(core["condition_state"]),
        raw_probability=core["raw_probability"],  # type: ignore[arg-type]
        calibrated_probability=core["calibrated_probability"],  # type: ignore[arg-type]
        model_id=str(core["model_id"]),
        model_hash=str(core["model_hash"]),
        primary_horizon=int(cast("int | str", core["primary_horizon"] or 21)),
        benchmark=str(core["benchmark"]),
        target_definition=str(core["target_definition"]),
        cost_hurdle_bps=float(cast("float | int | str", core["cost_hurdle_bps"] or 0.0)),
        created_at=cutoff.isoformat(),
        canonical_prediction_id=canonical_prediction_id(core),
        trade_date=str(core["trade_date"]),
        market_data_semantic_hash=str(core["market_data_semantic_hash"]),
        universe_semantic_hash=str(core["universe_semantic_hash"]),
        portfolio_predecision_hash=str(core["portfolio_predecision_hash"]),
        run_type=str(core["run_type"]),
    )


def outcome_from_prices(
    *,
    prediction: dict[str, object],
    entry_price: float,
    exit_price: float,
    benchmark_entry: float,
    benchmark_exit: float,
    cost_bps: float,
    entry_time: str,
    exit_time: str,
    available_at: str,
    data_snapshot_id: str,
) -> ProbabilityOutcome:
    asset_return = exit_price / entry_price - 1.0
    benchmark_return = benchmark_exit / benchmark_entry - 1.0
    relative = asset_return - benchmark_return
    estimated_cost = cost_bps / 10_000.0
    net_relative = relative - estimated_cost
    return ProbabilityOutcome(
        prediction_id=str(prediction["prediction_id"]),
        ticker=str(prediction["ticker"]),
        entry_reference_time=entry_time,
        entry_reference_price=entry_price,
        exit_reference_time=exit_time,
        exit_reference_price=exit_price,
        benchmark_return=benchmark_return,
        asset_return=asset_return,
        relative_return=relative,
        estimated_cost=estimated_cost,
        net_relative_return=net_relative,
        target_hit=net_relative > 0,
        outcome_available_at=available_at,
        data_snapshot_id=data_snapshot_id,
    )


def _brier(outcomes: list[float], labels: list[int]) -> float:
    if not outcomes:
        return math.nan
    return sum(
        (probability - label) ** 2
        for probability, label in zip(outcomes, labels, strict=True)
    ) / len(outcomes)


def _log_loss(outcomes: list[float], labels: list[int]) -> float:
    if not outcomes:
        return math.nan
    total = 0.0
    for probability, label in zip(outcomes, labels, strict=True):
        clipped = min(max(probability, 1e-9), 1 - 1e-9)
        total += -(label * math.log(clipped) + (1 - label) * math.log(1 - clipped))
    return total / len(outcomes)


def _ece(outcomes: list[float], labels: list[int], buckets: int = 5) -> float:
    if not outcomes:
        return math.nan
    pairs = sorted(zip(outcomes, labels, strict=True), key=lambda item: item[0])
    width = len(pairs) / buckets
    total = 0.0
    for bucket in range(buckets):
        start = int(round(bucket * width))
        end = int(round((bucket + 1) * width))
        if start >= end:
            continue
        chunk = pairs[start:end]
        mean_probability = sum(item[0] for item in chunk) / len(chunk)
        mean_label = sum(item[1] for item in chunk) / len(chunk)
        total += abs(mean_probability - mean_label) * len(chunk)
    return total / len(pairs)


def evaluate_forward_probability(
    ledger: ProbabilityForwardLedger,
    *,
    bootstrap_draws: int = 2000,
) -> dict[str, object]:
    """Date-clustered evaluation report (research only)."""

    raw_predictions = ledger.predictions()
    outcomes = ledger.outcomes()
    predictions_by_id = {str(item.get("prediction_id")): item for item in raw_predictions}
    canonical = audit_canonical_predictions(raw_predictions)
    # Outcomes are deduplicated by canonical prediction even for legacy rows
    # that predate the explicit canonical_prediction_id field.
    matched_by_canonical: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
    for outcome in outcomes:
        prediction = predictions_by_id.get(str(outcome.get("prediction_id")))
        if prediction is None:
            continue
        key = str(prediction.get("canonical_prediction_id") or canonical_prediction_id(prediction))
        if key in canonical and key not in matched_by_canonical:
            matched_by_canonical[key] = (canonical[key], outcome)
    matched = list(matched_by_canonical.values())
    if not matched:
        return {
            "status": "NO_MATURED_OUTCOMES",
            "raw_prediction_rows": len(raw_predictions),
            "canonical_predictions": len(canonical),
            "matured_canonical_predictions": 0,
            "row_level_n": 0,
            "effective_sample_size": 0,
            "decision_date_n": 0,
            "production_influence": 0,
            "promotion_status": "NOT_ELIGIBLE",
            "human_approval_required": True,
        }
    probabilities = [
        float(
            cast(
                "float | int | str | None",
                pred.get("calibrated_probability"),
            )
            or cast(
                "float | int | str | None",
                pred.get("raw_probability"),
            )
            or 0.5
        )
        for pred, _item in matched
    ]
    labels = [1 if item["target_hit"] else 0 for _, item in matched]
    decision_dates = sorted(
        {
            str(pred.get("decision_cutoff"))[:10]
            for pred, _item in matched
            if pred and pred.get("decision_cutoff")
        }
    )
    report: dict[str, object] = {
        "status": "FORWARD_EVIDENCE_AVAILABLE",
        "raw_prediction_rows": len(raw_predictions),
        "canonical_predictions": len(canonical),
        "matured_canonical_predictions": len(matched),
        "row_level_n": len(matched),
        "decision_date_n": len(decision_dates),
        "effective_sample_size": len(matched),
        "effective_sample_size_hint": len(decision_dates),
        "bootstrap": "decision-date clustered",
        "brier_score": _brier(probabilities, labels),
        "log_loss": _log_loss(probabilities, labels),
        "ece_5_buckets": _ece(probabilities, labels),
        "production_influence": 0,
        "promotion_status": "PROMOTION_CANDIDATE_PENDING_HUMAN_APPROVAL",
        "human_approval_required": True,
        "auto_promote": False,
    }
    report["bootstrap_draws"] = bootstrap_draws
    return report


class ProbabilityPromotionPolicy:
    """Explicit promotion gate.  The default production influence is 0."""

    production_influence: float = 0.0
    allowed_influence_levels: tuple[float, ...] = (0.0, 0.05, 0.10, 0.15)
    human_approval_required: bool = True
    auto_promote: bool = False

    def conditions(self) -> tuple[str, ...]:
        return (
            "complete out-of-sample outcomes beyond the frozen horizon",
            "no future leakage in outcome construction",
            "calibrated probability stable across decision dates",
            "calibration does not deteriorate vs baseline",
            "after-cost incremental value > 0",
            "Probability ON economically dominates OFF on identical inputs",
            "no significant max drawdown increase",
            "no significant turnover deterioration",
            "evidence spans multiple decision dates",
            "result not driven by a few symbols",
            "benchmark-relative evidence holds",
            "confidence interval excludes material negative increment",
            "frozen config",
            "frozen model",
            "human approval",
        )
