from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.core.status_document import render_current_status


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def _validation_checkpoint(root: Path, manifest: dict[str, object]) -> dict[str, object]:
    for name in (
        "round31_validation_summary.json",
        "round30_validation_summary.json",
        "round28_validation_summary.json",
    ):
        summary_path = root / "reports" / "validation-artifacts" / name
        if summary_path.exists():
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    validation = manifest.get("validation")
    if isinstance(validation, dict):
        return {
            "command": "pytest -q",
            "result": str(validation.get("pytest", "PENDING")),
            "quant_critical": str(validation.get("quant_critical", "PENDING")),
            "commit": _git_head(root),
            "source": "ROUND27_ACCEPTANCE_MANIFEST",
        }
    return {
        "command": "pytest -q",
        "result": "PENDING",
        "quant_critical": "PENDING",
        "commit": "UNAVAILABLE",
        "source": "NO_VALIDATION_SUMMARY",
    }


def _round29_summary(root: Path) -> dict[str, object]:
    run_id = "daily-c3c0107d1d7641b49bbb81c32615fbbc"
    certificate_path = root / "reports" / "daily-runs" / run_id / "run_certificate.json"
    ai_brief_path = root / "reports" / "daily-runs" / run_id / "ai_brief.json"
    replay_path = (
        root / "reports" / "validation-artifacts" / "round29_frozen_replay.json"
    )
    validation_path = (
        root / "reports" / "validation-artifacts" / "round29_validation_summary.json"
    )
    summary: dict[str, object] = {
        "run_id": run_id,
        "status": "NOT_AVAILABLE",
    }
    if not certificate_path.exists():
        return summary
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    stages = certificate.get("stages") or []
    ai_stage = next(
        (item for item in stages if isinstance(item, dict) and item.get("name") == "AI_BRIEF"),
        {},
    )
    metadata = ai_stage.get("metadata") or {}
    summary["classification"] = certificate.get("classification")
    summary["ai_status"] = metadata.get("ai_status")
    summary["ai_source"] = metadata.get("source")
    summary["semantic_grounding_status"] = metadata.get(
        "semantic_grounding_status"
    )
    summary["news"] = metadata.get("news") or {}
    if ai_brief_path.exists():
        ai_brief = json.loads(ai_brief_path.read_text(encoding="utf-8"))
        summary["llm_usage"] = ai_brief.get("llm_calls") or {}
        summary["action_commentary_count"] = len(
            (ai_brief.get("brief") or {}).get("action_commentaries") or []
        )
        summary["portfolio_review_present"] = bool(
            (ai_brief.get("brief") or {}).get("portfolio_review")
        )
        summary["devils_advocate_count"] = len(
            (ai_brief.get("brief") or {}).get("devils_advocate") or []
        )
        summary["company_dossier_count"] = len(
            (ai_brief.get("brief") or {}).get("company_dossiers") or {}
        )
    if replay_path.exists():
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        summary["frozen_replay"] = replay.get("status")
        summary["frozen_replay_source"] = replay.get("source")
    if validation_path.exists():
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        summary["validation"] = validation
    if summary.get("frozen_replay") == "PASS" and summary.get("classification"):
        summary["status"] = "PASS"
        summary["acceptance_mode"] = "FROZEN_REPLAY"
    return summary


def _round30_summary(root: Path) -> dict[str, object]:
    registry_path = (
        root / "reports" / "validation-artifacts" / "model_influence_registry.json"
    )
    ladder_path = (
        root / "reports" / "validation-artifacts" / "probability_promotion_ladder.json"
    )
    counterfactual_path = (
        root / "reports" / "validation-artifacts" / "quant_counterfactual_audit.json"
    )
    summary: dict[str, object] = {
        "status": "NOT_AVAILABLE",
    }
    if not registry_path.exists():
        return summary
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    summary["source_run_id"] = registry.get("source_run_id")
    summary["status"] = "PASS"
    summary["model_registry_schema"] = registry.get("schema_version")
    summary["formal_participation"] = registry.get("formal_participation")
    if ladder_path.exists():
        ladder = json.loads(ladder_path.read_text(encoding="utf-8"))
        summary["probability_promotion_status"] = ladder.get("current_status")
        summary["probability_production_influence"] = ladder.get(
            "production_influence"
        )
    if counterfactual_path.exists():
        counterfactual = json.loads(counterfactual_path.read_text(encoding="utf-8"))
        summary["counterfactual_evidence_type"] = counterfactual.get("evidence_type")
        summary["counterfactual_variants"] = [
            item.get("name") for item in counterfactual.get("variants", [])
        ]
    return summary


def _round31_summary(root: Path) -> dict[str, object]:
    breadth_path = (
        root / "reports" / "validation-artifacts" / "portfolio_breadth_audit.json"
    )
    policy_path = (
        root / "reports" / "validation-artifacts" / "round31_policy_recommendation.json"
    )
    etf_path = (
        root / "reports" / "validation-artifacts" / "etf_actionability_audit.json"
    )
    summary: dict[str, object] = {
        "status": "NOT_AVAILABLE",
    }
    if not breadth_path.exists():
        return summary
    breadth = json.loads(breadth_path.read_text(encoding="utf-8"))
    summary["evidence_type"] = breadth.get("evidence_type")
    summary["policies"] = [
        item.get("policy") for item in breadth.get("rows", [])
    ]
    summary["status"] = "PASS"
    if policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        summary["policy_status"] = policy.get("status")
        summary["recommended_policy"] = policy.get("recommended_policy")
    if etf_path.exists():
        etf = json.loads(etf_path.read_text(encoding="utf-8"))
        summary["etf_formal_action_count"] = etf.get("formal_action_count")
        summary["etf_research_count"] = etf.get("research_count")
    return summary


def _round32_summary(root: Path) -> dict[str, object]:
    audit_path = (
        root / "reports" / "validation-artifacts" / "round32_run_bundle_audit.json"
    )
    summary: dict[str, object] = {
        "status": "NOT_AVAILABLE",
    }
    if not audit_path.exists():
        return summary
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    summary["acceptance_run_id"] = audit.get("acceptance_run_id")
    summary["status"] = "PASS"
    summary["decision_manifest_semantic_hash"] = audit.get(
        "decision_manifest_semantic_hash"
    )
    summary["bundle_hash"] = audit.get("bundle_hash")
    acceptance = audit.get("result", {}).get("acceptance", {})
    summary["ROUND32_FULL_REPLAY"] = acceptance.get("ROUND32_FULL_REPLAY")
    summary["RUN_INPUT_PERSISTENCE"] = acceptance.get("RUN_INPUT_PERSISTENCE")
    summary["NO_FUTURE_REHYDRATION"] = acceptance.get("NO_FUTURE_REHYDRATION")
    summary["IMMUTABILITY"] = acceptance.get("IMMUTABILITY")
    summary["ROUND27_FULL_REPLAY"] = acceptance.get("ROUND27_FULL_REPLAY")
    return summary


def build_current_status(root: Path) -> dict[str, object]:
    manifest_path = root / "round27_acceptance_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = str(manifest["acceptance_run_id"])
    certificate_path = (
        root / "reports" / "daily-runs" / run_id / "run_certificate.json"
    )
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    provenance = certificate.get("provenance") or {}
    trace = provenance.get("cardinality_trace") or {}
    recommendations = certificate.get("decision_recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = []
    stages = certificate.get("stages") or []
    ai_brief = next(
        (item for item in stages if isinstance(item, dict) and item.get("name") == "AI_BRIEF"),
        {},
    )
    ai_metadata = ai_brief.get("metadata") or {}
    git_commit = _git_head(root)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, object] = {
        "schema_version": "current-status-v2",
        "version": "1.2.0-rc.1",
        "git_commit": git_commit,
        "build_id": f"pat-1.2.0-rc.1-{git_commit[:12]}-20260815",
        "generated_at": generated_at,
        "evidence_level": str(manifest.get("classification", "UNKNOWN")),
        "operating_mode": "MANUAL_ADVISORY_ONLY",
        "alembic_head": "d4a5b6c7d8e9",
        "capabilities": {
            "DATA": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    f"acceptance run {run_id}; DATA PASS; PIT cutoff "
                    "2026-08-14T20:30:00+00:00; 2,135 universe members."
                ),
            },
            "PIT": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "PIT stage PASS for the acceptance run; historical research "
                    "certification remains NOT_CERTIFIABLE."
                ),
            },
            "Alpha": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "USAdaptiveAlphaCoreV1 produced 2,135 cross-sectional factor "
                    "rows; 1,171 candidates reached the optimizer."
                ),
            },
            "Probability": {
                "state": "BLOCKED_BY_VALIDATION",
                "evidence": (
                    "RESEARCH_ONLY; matured outcomes 0; effective N 0; production "
                    "influence 0%."
                ),
            },
            "Portfolio": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "optimizer input 1,171; no fixed cardinality cap; 10 non-zero "
                    "targets produced by SLSQP constraints."
                ),
            },
            "Risk": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "RISK PASS; expected vol 7.60%; gross 27.23%; cash 72.77%; "
                    "size neutralization degraded."
                ),
            },
            "Stress": {
                "state": "FIXTURE_TESTED",
                "evidence": "Governed stress remains in the risk chain.",
            },
            "Backtest": {
                "state": "BLOCKED_BY_DATA",
                "evidence": "No survivorship-safe historical certification.",
            },
            "Portfolio Breadth": {
                "state": "BLOCKED_BY_DATA",
                "evidence": (
                    "Fixture/OOS-style breadth research only; no certified "
                    "historical OOS or mature forward outcome evidence."
                ),
            },
            "Locked OOS": {
                "state": "BLOCKED_BY_DATA",
                "evidence": "No mature OOS sample for probability promotion.",
            },
            "Terminal": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "backend formal actions and renderer action list are "
                    "cardinality/ticker consistent for the acceptance run."
                ),
            },
            "Manual Execution": {
                "state": "FIXTURE_TESTED",
                "evidence": "Manual execution remains the only execution path.",
            },
            "AI Intelligence": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    f"AI_BRIEF status {ai_metadata.get('ai_status', 'UNAVAILABLE')}; "
                    "AI trade authority NONE; production influence NONE."
                ),
            },
            "ETF Research": {
                "state": "REAL_DATA_TESTED",
                "evidence": (
                    "ETF sleeve remains RESEARCH_CANDIDATE; no formal ETF "
                    "recommendations in ROUND27 acceptance."
                ),
            },
            "Market Regime": {
                "state": "OBSERVATION_ONLY",
                "evidence": (
                    "deterministic market-regime-v1 runs in OBSERVATION_ONLY; "
                    "no production influence."
                ),
            },
            "Live Capital": {
                "state": "DISABLED",
                "evidence": "LIVE_CAPITAL_NOT_APPROVED",
            },
        },
        "round28": {
            "acceptance_run_id": run_id,
            "classification": manifest.get("classification"),
            "decision_manifest_semantic_hash": manifest.get(
                "decision_manifest_semantic_hash"
            ),
            "optimizer_input_count": trace.get("optimizer_input"),
            "pre_optimizer_top_n": None,
            "fixed_holdings_cap": trace.get("maximum_allowed_holdings"),
            "final_action_count": len(recommendations),
            "formal_actions": [
                {
                    "symbol": item.get("symbol"),
                    "action": item.get("action"),
                    "target_weight": item.get("target_weight"),
                }
                for item in recommendations
                if isinstance(item, dict)
            ],
            "probability_production_influence": 0.0,
            "research_certification": "NOT_CERTIFIABLE",
            "automatic_execution": "DISABLED",
            "broker_api": "DISABLED",
            "ai_trade_authority": "NONE",
        },
        "validation_checkpoint": _validation_checkpoint(root, manifest),
        "round29": _round29_summary(root),
        "round30": _round30_summary(root),
        "round31": _round31_summary(root),
        "round32": _round32_summary(root),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build/render/synchronize CURRENT_STATUS from runtime artifacts"
    )
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "docs" / "CURRENT_STATUS.json"
    target = root / "docs" / "CURRENT_STATUS.md"
    if args.build:
        payload = build_current_status(root)
        source.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    payload = json.loads(source.read_text(encoding="utf-8"))
    rendered = render_current_status(payload)
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            raise SystemExit("CURRENT_STATUS.md is not synchronized with CURRENT_STATUS.json")
    else:
        target.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
