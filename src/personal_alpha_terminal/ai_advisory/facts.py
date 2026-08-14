"""ROUND24 AI brief quant-facts assembly (B1, B4, B5).

Every fact is read from immutable run artifacts and PIT SEC evidence.
Anything timestamped after the decision cutoff is dropped and reported as a
data gap.  The module never fetches news and never consults the network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

EVIDENCE_PREFIX = "evidence"


def _iso_after(as_of: datetime, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return parsed > as_of


def _bounded(payload: Any, as_of: datetime) -> Any:
    """Recursively drop dict values timestamped after the cutoff (future leakage guard)."""

    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str) and _iso_after(as_of, value):
                result[key] = "FUTURE_DATA_DROPPED"
                continue
            result[key] = _bounded(value, as_of)
        return result
    if isinstance(payload, list):
        bounded_list: list[Any] = []
        for item in payload:
            if isinstance(item, str) and _iso_after(as_of, item):
                bounded_list.append("FUTURE_DATA_DROPPED")
                continue
            bounded_list.append(_bounded(item, as_of))
        return bounded_list
    return payload


def build_quant_facts(
    *,
    run_certificate: dict[str, Any],
    pit_events: tuple[dict[str, Any], ...],
    etf_evidence: dict[str, Any] | None,
    decision_as_of: datetime,
) -> tuple[dict[str, Any], list[str]]:
    """Assemble the PIT-safe facts payload for the Chinese brief."""

    if decision_as_of.tzinfo is None:
        raise ValueError("decision_as_of must be timezone-aware")
    data_gaps: list[str] = []
    bounded_cert = _bounded(run_certificate, decision_as_of)
    analysis_date = bounded_cert.get("analysis_date")
    trade_date = bounded_cert.get("trade_date")
    stages = bounded_cert.get("stages") or []
    stage_status = {
        str(item.get("name")): str(item.get("status"))
        for item in stages
        if isinstance(item, dict)
    }
    for name, status in stage_status.items():
        if status != "PASS":
            data_gaps.append(f"stage {name} status {status}")

    data_section = bounded_cert.get("data") or {}
    universe_counts: dict[str, Any] = {}
    if isinstance(data_section, list):
        universe_row = next(
            (
                item
                for item in data_section
                if isinstance(item, dict)
                and str(item.get("dataset")) == "CERTIFIED_US_UNIVERSE"
            ),
            None,
        )
        if universe_row:
            universe_counts = {
                "members": universe_row.get("member_count"),
                "as_of": universe_row.get("as_of"),
                "certification_state": universe_row.get("certification_state"),
            }

    recommendations = bounded_cert.get("decision_recommendations") or []
    actions: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        actions.append(
            {
                "symbol": str(item.get("symbol", "")),
                "instrument_type": str(item.get("instrument_type", "COMMON_STOCK")),
                "sleeve": str(item.get("sleeve", "EQUITY_ALPHA")),
                "action": str(item.get("action", "")),
                "current_weight": item.get("current_weight"),
                "target_weight": item.get("target_weight"),
                "expected_alpha": item.get("expected_alpha"),
                "risk_contribution": item.get("risk_contribution"),
                "estimated_cost": item.get("estimated_cost"),
                "estimated_value": item.get("estimated_value"),
                "data_quality": str(item.get("data_quality", "")),
                "reason": str(item.get("reason", "")),
            }
        )
    action_symbols = frozenset(item["symbol"] for item in actions if item["symbol"])

    portfolio = bounded_cert.get("portfolio") or {}
    risk = bounded_cert.get("risk") or {}
    benchmarks = bounded_cert.get("benchmarks") or []
    benchmark_facts: list[dict[str, Any]] = []
    for item in benchmarks:
        if not isinstance(item, dict):
            continue
        benchmark_facts.append(
            {
                "symbol": item.get("symbol"),
                "period_return": item.get("period_return"),
                "annualized_volatility": item.get("annualized_volatility"),
                "observations": item.get("observations"),
            }
        )

    factor_statistics = bounded_cert.get("factor_statistics") or {}
    factor_count = bounded_cert.get("factor_count")
    candidate_count = bounded_cert.get("candidate_count")

    events: list[dict[str, Any]] = []
    event_refs: list[str] = []
    for index, event in enumerate(pit_events):
        observed = event.get("observed_at")
        if isinstance(observed, str):
            try:
                parsed = datetime.fromisoformat(observed)
            except ValueError:
                parsed = None
            if parsed is not None and parsed.tzinfo is not None and parsed > decision_as_of:
                data_gaps.append(f"PIT event {event.get('event_id')} observed after cutoff")
                continue
        reference = f"pit-event-{event.get('event_id') or index}"
        event_refs.append(reference)
        events.append(
            {
                "symbol": event.get("symbol"),
                "event_type": event.get("event_type"),
                "effective_at": event.get("effective_at"),
                "summary": (event.get("payload") or {}).get("summary")
                if isinstance(event.get("payload"), dict)
                else None,
                "evidence_ref": reference,
            }
        )

    evidence_refs: list[str] = [
        f"run-certificate:{run_certificate.get('run_id', 'UNKNOWN')}",
        *event_refs,
    ]
    etf_section: dict[str, Any] = {}
    if isinstance(etf_evidence, dict):
        etf_section = {
            "universe": {
                "raw_listed_etfs": (etf_evidence.get("counts") or {}).get("raw_listed_etfs"),
                "core_eligible": (etf_evidence.get("counts") or {}).get("core_eligible"),
                "tactical_eligible": (etf_evidence.get("counts") or {}).get("tactical_eligible"),
                "blocked_complex": (etf_evidence.get("counts") or {}).get("blocked_complex"),
                "research_only": (etf_evidence.get("counts") or {}).get("research_only"),
            },
            "targets": etf_evidence.get("targets") or [],
            "composition": etf_evidence.get("composition") or {},
        }
        for target in etf_section["targets"]:
            if target.get("eligible") and target.get("symbol"):
                action_symbols = frozenset({*action_symbols, str(target["symbol"])})

    facts = {
        "analysis_date": analysis_date,
        "trade_date": trade_date,
        "market_session": bounded_cert.get("market_session"),
        "market_state": stage_status,
        "universe": universe_counts,
        "factor_count": factor_count,
        "candidate_count": candidate_count,
        "factor_statistics": factor_statistics,
        "actions": actions,
        "portfolio": portfolio,
        "risk": risk,
        "benchmarks": benchmark_facts,
        "pit_events": events,
        "etf": etf_section,
        "warnings": bounded_cert.get("warnings") or [],
        "llm_mode": bounded_cert.get("llm_mode"),
        "probability_mode": bounded_cert.get("probability_mode"),
        "probability_influence": bounded_cert.get("probability_influence"),
        "operational_authorization": bounded_cert.get("operational_authorization"),
        "signal_authorization_class": bounded_cert.get("signal_authorization_class"),
        "research_certification_state": bounded_cert.get("research_certification_state"),
        "auto_execution": bounded_cert.get("auto_execution"),
        "broker_api": bounded_cert.get("broker_api"),
        "manual_execution_only": bounded_cert.get("manual_execution_only"),
        "evidence_refs": evidence_refs,
        "allowed_action_symbols": sorted(action_symbols),
    }
    return facts, data_gaps
