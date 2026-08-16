"""ROUND29 frozen-output replay for AI brief integrity.

The replay uses a real persisted LLM output from a completed daily run and
re-runs only deterministic merging/grounding logic. It never contacts the LLM
provider and never sends formal action data to any external service.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from personal_alpha_terminal.ai_advisory.action_commentary import (
    build_deterministic_action_commentaries,
    build_deterministic_devils_advocate,
    build_deterministic_portfolio_review,
)
from personal_alpha_terminal.ai_advisory.brief_v2 import (
    apply_deepseek_synthesis,
    build_deterministic_v2,
)
from personal_alpha_terminal.ai_advisory.facts import build_quant_facts
from personal_alpha_terminal.ai_advisory.facts_v3 import build_facts_v3
from personal_alpha_terminal.ai_advisory.grounding_v3 import quarantine_sections
from personal_alpha_terminal.intelligence.company_dossier import build_company_dossiers


def replay_round29_brief(run_dir: Path) -> dict[str, object]:
    """Replay a persisted AI brief output and return a grounding verdict."""

    ai_brief_path = run_dir / "ai_brief.json"
    certificate_path = run_dir / "run_certificate.json"
    exposure_path = run_dir / "current_exposure.json"
    if not ai_brief_path.exists() or not certificate_path.exists():
        return {
            "status": "NOT_AVAILABLE",
            "reason": "run artifacts missing",
        }
    ai_brief = json.loads(ai_brief_path.read_text(encoding="utf-8"))
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    current_exposure = (
        json.loads(exposure_path.read_text(encoding="utf-8"))
        if exposure_path.exists()
        else {}
    )
    manifest = certificate.get("decision_manifest") or {}
    cutoff_raw = manifest.get("decision_cutoff") or certificate.get("data_cutoff")
    decision_as_of = datetime.fromisoformat(str(cutoff_raw).replace("Z", "+00:00"))
    facts, data_gaps = build_quant_facts(
        run_certificate=certificate,
        pit_events=(),
        etf_evidence={},
        decision_as_of=decision_as_of,
    )
    facts["data_gaps"] = data_gaps
    facts["current_exposure"] = current_exposure
    dossiers = build_company_dossiers(
        symbols=tuple(
            str(item.get("symbol"))
            for item in (facts.get("formal_actions") or [])
            if isinstance(item, dict) and item.get("symbol")
        ),
        current_exposure=current_exposure,
        as_of=decision_as_of,
    )
    dossier_map = {item.ticker: item.document() for item in dossiers}
    facts["company_dossiers"] = dossier_map
    facts["action_commentaries"] = build_deterministic_action_commentaries(
        facts=facts,
        dossiers=dossier_map,
    )
    facts["portfolio_review"] = build_deterministic_portfolio_review(
        facts=facts,
        dossiers=dossier_map,
    )
    facts["devils_advocate"] = build_deterministic_devils_advocate(facts=facts)

    passes = ai_brief.get("passes") or {}
    pass4 = passes.get("pass4_final") or {}
    payload = pass4.get("parsed_response")
    if not isinstance(payload, dict):
        return {
            "status": "NOT_AVAILABLE",
            "reason": "pass4 parsed response missing",
        }
    base_brief = build_deterministic_v2(facts)
    merged_brief = apply_deepseek_synthesis(
        base_brief,
        payload,
        facts=facts,
        allowed_action=frozenset(facts.get("allowed_action_symbols") or []),
    )
    facts_v3 = build_facts_v3(facts_v2=facts)
    _merged, report = quarantine_sections(
        merged_brief,
        base_brief,
        facts_v3=facts_v3,
    )
    formal_action_count = len(facts.get("formal_actions") or [])
    commentaries = merged_brief.get("action_commentaries") or []
    formal_fields_preserved = all(
        item.get("formal_action") == "BUY"
        and item.get("formal_target_weight") is not None
        for item in commentaries
    )
    status = (
        "PASS"
        if report.get("critical_failure") is not True and formal_fields_preserved
        else "FAIL"
    )
    return {
        "status": status,
        "run_id": str(certificate.get("run_id")),
        "semantic_validation_status": report.get("status"),
        "critical_failure": bool(report.get("critical_failure")),
        "quarantined_sections": report.get("quarantined_sections") or [],
        "issues": report.get("issues") or {},
        "formal_action_count": formal_action_count,
        "action_commentary_count": len(commentaries),
        "portfolio_review_present": bool(merged_brief.get("portfolio_review")),
        "devils_advocate_count": len(merged_brief.get("devils_advocate") or []),
        "company_dossier_count": len(dossier_map),
        "formal_fields_preserved": formal_fields_preserved,
        "llm_usage": ai_brief.get("llm_calls") or {},
        "source": "FROZEN_LLM_OUTPUT_REPLAY",
    }
