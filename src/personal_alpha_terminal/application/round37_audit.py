"""ROUND37 probability forward validation and promotion readiness."""

from __future__ import annotations

import json
from pathlib import Path

from personal_alpha_terminal.probability.forward_ledger import (
    ProbabilityForwardLedger,
    audit_canonical_predictions,
    evaluate_forward_probability,
)

ROUND37_SCHEMA = "round37-probability-forward-validation-v1"


def build_round37_forward_dataset(
    ledger: ProbabilityForwardLedger,
) -> dict[str, object]:
    raw = ledger.predictions()
    outcomes = ledger.outcomes()
    canonical = audit_canonical_predictions(raw)
    decision_dates = sorted(
        {str(row.get("decision_cutoff", ""))[:10] for row in canonical.values()}
    )
    return {
        "schema_version": ROUND37_SCHEMA,
        "prediction_count": len(raw),
        "canonical_prediction_count": len(canonical),
        "matured_count": sum(1 for row in outcomes if row.get("target_hit") is not None),
        "pending_count": len(outcomes) - sum(
            1 for row in outcomes if row.get("target_hit") is not None
        ),
        "independent_decision_dates": len(decision_dates),
        "decision_dates": decision_dates,
    }


def build_round37_calibration(
    ledger: ProbabilityForwardLedger,
) -> dict[str, object]:
    return evaluate_forward_probability(ledger)


def build_round37_incremental_value(
    artifacts_dir: Path,
) -> dict[str, object]:
    retest = json.loads(
        (artifacts_dir / "round33_probability_retest.json").read_text(encoding="utf-8")
    )
    return {
        "schema_version": ROUND37_SCHEMA,
        "corrected_historical_oos": retest,
        "real_forward": "INSUFFICIENT_SAMPLE",
    }


def build_round37_promotion_gate(
    calibration: dict[str, object],
    incremental: dict[str, object],
) -> dict[str, object]:
    matured = _int_value(calibration.get("matured_canonical_predictions", 0))
    decision_dates = _int_value(calibration.get("decision_date_n", 0))
    verdict = (
        "PROBABILITY_PROMOTION_ELIGIBLE"
        if matured >= 60 and decision_dates >= 5
        else "PROBABILITY_FORWARD_SAMPLE_INSUFFICIENT"
    )
    return {
        "schema_version": ROUND37_SCHEMA,
        "verdict": verdict,
        "production_weight": 0.0,
        "human_approval_required": True,
        "unmet_conditions": [
            "matured N >= 60",
            "decision dates >= 5",
            "positive after-cost incremental value",
        ],
        "incremental_value": incremental,
    }


def _int_value(value: object) -> int:
    if isinstance(value, (int, float, str)):
        return int(value)
    return 0


def write_round37_artifacts(
    artifacts_dir: Path,
    *,
    ledger_root: Path | None = None,
) -> dict[str, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    ledger = ProbabilityForwardLedger(ledger_root)
    dataset = build_round37_forward_dataset(ledger)
    calibration = build_round37_calibration(ledger)
    incremental = build_round37_incremental_value(artifacts_dir)
    gate = build_round37_promotion_gate(calibration, incremental)
    payloads: dict[str, dict[str, object]] = {
        "round37_probability_forward_dataset.json": dataset,
        "round37_probability_calibration.json": calibration,
        "round37_probability_incremental_value.json": incremental,
        "round37_probability_forward_vs_historical.json": {
            "schema_version": ROUND37_SCHEMA,
            "corrected_historical_oos": incremental,
            "real_forward": dataset,
            "combined": False,
        },
        "round37_probability_promotion_gate.json": gate,
        "round37_validation_summary.json": {
            "schema_version": ROUND37_SCHEMA,
            "FINAL_VERDICT": gate["verdict"],
            "PROBABILITY_PRODUCTION_INFLUENCE": 0.0,
            "READY_FOR_ROUND38": "YES",
        },
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = artifacts_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        paths[name] = path
    return paths
