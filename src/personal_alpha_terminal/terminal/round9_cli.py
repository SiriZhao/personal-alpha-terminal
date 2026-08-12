"""CLI handlers for ROUND 9 LLM Quant Modernization (Shadow -> Advisory)."""
from __future__ import annotations

import json
from argparse import Namespace
from datetime import datetime
from pathlib import Path

from rich.console import Console

from personal_alpha_terminal.quant_engine.llm_advisory import (
    AdvisoryIntelligenceService,
    DataAnomalyReport,
    EvidenceRef,
    PortfolioExplanation,
    evaluate_llm,
    evaluate_llm_shadow_research,
)

console = Console()


def round9_research_command(args: Namespace) -> int:
    action = str(args.round9_action)
    if action == "advisory-snapshot":
        return _advisory_snapshot(args)
    if action == "evaluate":
        return _evaluate(args)
    if action == "shadow-research":
        return _shadow_research(args)
    console.print(f"Unknown round9 action: {action}")
    return 2


def _advisory_snapshot(args: Namespace) -> int:
    """Assemble a deterministic advisory snapshot from injected contract outputs.

    This is a demonstration/audit path: it validates the structured contracts
    and shows the SHADOW/ADVISORY status, quant impact and fallback.  It never
    changes a target.
    """
    service = AdvisoryIntelligenceService()
    now = datetime.now()
    service.record(
        DataAnomalyReport(
            classification="STALE_DATA",
            confidence=0.8,
            timestamp=now,
            source="market-data",
            model="advisory-v1",
            prompt_version="anomaly-v1",
            evidence=[EvidenceRef(evidence_id="e1", source="provider-log")],
            summary="Latest session older than expected",
            anomaly_kind="STALE_DATA",
            severity="MEDIUM",
            affected_symbols=[],
        )
    )
    service.record(
        PortfolioExplanation(
            classification="HOLD",
            confidence=0.7,
            timestamp=now,
            source="quant-result",
            model="advisory-v1",
            prompt_version="portfolio-explanation-v1",
            evidence=[],
            summary="Explains the formal quant result without changing targets",
            explanations=["Momentum remains positive but below the no-trade band"],
            risk_notes=["Concentration above baseline"],
            quant_impact="NONE",
        )
    )
    snapshot = service.snapshot(
        model=str(args.model or "advisory-v1"),
        pit_documents=int(getattr(args, "pit_documents", 0)),
        quant_impact="NONE",
    )
    console.print(json.dumps(snapshot.document(), ensure_ascii=False, indent=2, sort_keys=True))
    console.print(f"Status: {snapshot.status}   Quant impact: {snapshot.quant_impact}   "
                  f"Fallback: {snapshot.fallback}")
    return 0


def _evaluate(args: Namespace) -> int:
    payload = json.loads(Path(str(args.metrics)).read_text(encoding="utf-8"))
    evaluation = evaluate_llm(
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        grounded=int(payload["grounded"]),
        temporally_correct=int(payload["temporally_correct"]),
        consistent=int(payload.get("consistent", payload["grounded"])),
        schema_valid=int(payload["schema_valid"]),
        total=int(payload["total"]),
        repeated=int(payload.get("repeated", payload["total"])),
        latencies_ms=[float(item) for item in payload.get("latencies_ms", [])],
        total_cost_usd=float(payload.get("total_cost_usd", 0.0)),
        incremental_quant_value=(
            float(payload["incremental_quant_value"])
            if payload.get("incremental_quant_value") is not None
            else None
        ),
    )
    console.print(json.dumps(evaluation.document(), ensure_ascii=False, indent=2, sort_keys=True))
    console.print(f"Pass thresholds: {evaluation.pass_thresholds}")
    return 0 if evaluation.pass_thresholds else 3


def _shadow_research(args: Namespace) -> int:
    payload = json.loads(Path(str(args.metrics)).read_text(encoding="utf-8"))
    result = evaluate_llm_shadow_research(
        feature_name=str(payload["feature_name"]),
        classical_oos_net_return=(
            float(payload["classical_oos_net_return"])
            if payload.get("classical_oos_net_return") is not None
            else None
        ),
        combined_oos_net_return=(
            float(payload["combined_oos_net_return"])
            if payload.get("combined_oos_net_return") is not None
            else None
        ),
        classical_oos_rank_ic=(
            float(payload["classical_oos_rank_ic"])
            if payload.get("classical_oos_rank_ic") is not None
            else None
        ),
        combined_oos_rank_ic=(
            float(payload["combined_oos_rank_ic"])
            if payload.get("combined_oos_rank_ic") is not None
            else None
        ),
        classical_oos_sharpe=(
            float(payload["classical_oos_sharpe"])
            if payload.get("classical_oos_sharpe") is not None
            else None
        ),
        combined_oos_sharpe=(
            float(payload["combined_oos_sharpe"])
            if payload.get("combined_oos_sharpe") is not None
            else None
        ),
        sample_size=int(payload["sample_size"]),
        min_sample_size=int(payload.get("min_sample_size", 252)),
    )
    console.print(json.dumps(result.document(), ensure_ascii=False, indent=2, sort_keys=True))
    console.print(f"Verdict: {result.verdict.value}")
    return 0 if result.verdict.value == "INCREMENTAL_VALUE" else 3
