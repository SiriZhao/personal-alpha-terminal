"""Export scoped, hash-verified latest universe and probability certificates."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from personal_alpha_terminal.core.effective_config import resolve_effective_runtime_config
from personal_alpha_terminal.data.us_market.broad_universe import read_directory_snapshot
from personal_alpha_terminal.quant_engine.probability_overlay import OverlayApprovalPolicy


def _canonical_hash(document: dict[str, Any]) -> str:
    material = {key: value for key, value in document.items() if key != "artifact_hash"}
    encoded = json.dumps(
        material,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _latest_certificate(report_root: Path) -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for path in report_root.glob("daily-*/run_certificate.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Keep the committed latest certificate portable and free of local
        # workstation paths. The immutable run evidence remains under reports/.
        payload["_path"] = path.as_posix()
        documents.append(payload)
    if not documents:
        raise ValueError(f"no daily run certificate exists under {report_root}")
    return max(documents, key=lambda item: str(item.get("finished_at", "")))


def _write_hashed(document: dict[str, Any], path: Path) -> None:
    document["artifact_hash"] = _canonical_hash(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def export(config_path: Path, output_root: Path) -> tuple[Path, Path]:
    config = resolve_effective_runtime_config(config_path)
    certificate = _latest_certificate(config.report_dir / "daily-runs")
    provenance = certificate["provenance"]
    universe = provenance["universe_evidence"]
    overlay = provenance["probability_overlay"]
    directory = read_directory_snapshot(
        config.cache_dir / "us-current-directory" / "latest.json"
    )
    if directory.content_hash != universe["directory_hash"]:
        raise ValueError("latest run and current-directory content hashes do not match")

    capabilities = asdict(directory.capabilities)
    historical_blockers = [
        blocker
        for capability, blocker in (
            ("historical_membership", "HISTORICAL_MEMBERSHIP_INCOMPLETE"),
            ("delistings", "DELISTING_HISTORY_INCOMPLETE"),
            ("identifier_history", "SECURITY_IDENTIFIER_HISTORY_INCOMPLETE"),
            ("corporate_actions", "CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE"),
            ("total_return_vintages", "PIT_TOTAL_RETURN_HISTORY_INCOMPLETE"),
        )
        if not capabilities[capability]
    ]
    universe_document: dict[str, Any] = {
        "schema_version": "broad-universe-certification-v1",
        "artifact_id": f"broad-us-current-{certificate['analysis_date']}-"
        f"{str(universe['eligibility_hash'])[:12]}",
        "generated_at": certificate["finished_at"],
        "source_run_id": certificate["run_id"],
        "source_git_commit": certificate["git_commit"],
        "source_run_certificate": certificate["_path"],
        "analysis_date": certificate["analysis_date"],
        "decision_cutoff": certificate["data_cutoff"],
        "scope_classification": "CURRENT_DAILY_PIT_PARTIAL",
        "current_daily_selection_status": "PASS",
        "historical_research_status": "NOT_CERTIFIABLE",
        "eligible_for_strategy_production_approval": False,
        "fixed_bootstrap_list_is_alpha_universe": False,
        "provider": directory.provider,
        "provider_scope": "CURRENT_LISTINGS_ONLY",
        "provider_retrieved_at": directory.retrieved_at.isoformat(),
        "provider_source_timestamp": directory.source_timestamp,
        "provider_capabilities": capabilities,
        "directory_content_hash": directory.content_hash,
        "directory_manifest_hash": directory.manifest_hash,
        "eligibility_content_hash": universe["eligibility_hash"],
        "rules_fingerprint": universe["rules_fingerprint"],
        "daily_data_snapshot_id": provenance["data_snapshot_id"],
        "daily_data_hash": provenance["data_hash"],
        "pit_total_return_version": provenance["research_data_version"],
        "certified_universe_snapshot_id": provenance["universe_version"],
        "counts": {
            key: universe[key]
            for key in (
                "raw_listed_securities",
                "raw_listed_equities",
                "security_type_eligible",
                "data_eligible",
                "liquidity_eligible",
                "factor_eligible",
                "signal_eligible",
            )
        },
        "configured_filters": asdict(config.broad_universe),
        "adv_cutoff_convention": "STRICTLY_BEFORE_UNIVERSE_DATE",
        "segregation": {
            "equity_alpha": "COMMON_STOCK_ONLY",
            "benchmark": [config.benchmark, config.nasdaq_benchmark],
            "risk_reference": "ETF_OR_CURRENT_HOLDING_NOT_ALPHA_RANKED",
            "macro_regime": "OPTIONAL_UNAVAILABLE",
        },
        "pit_status": universe["pit_status"],
        "survivorship_status": universe["survivorship_status"],
        "historical_use_allowed": universe["historical_use_allowed"],
        "blockers": historical_blockers,
    }

    overlay_active = bool(overlay["active"])
    probability_blockers = []
    if not overlay_active:
        probability_blockers.append(str(overlay["reason"]))
    if historical_blockers:
        probability_blockers.append("RESEARCH_DATA_NOT_CERTIFIED")
    if provenance["probability_artifact_id"] == "OPTIONAL_UNAVAILABLE":
        probability_blockers.extend(
            (
                "LOCKED_OOS_EVIDENCE_UNAVAILABLE",
                "BASE_OVERLAY_AFTER_COST_COMPARISON_UNAVAILABLE",
                "CALIBRATION_EVIDENCE_UNAVAILABLE",
            )
        )
    probability_document: dict[str, Any] = {
        "schema_version": "probability-overlay-certification-v1",
        "artifact_id": f"probability-overlay-{certificate['analysis_date']}-"
        f"{str(certificate['canonical_result_hash'])[:12]}",
        "generated_at": certificate["finished_at"],
        "source_run_id": certificate["run_id"],
        "source_git_commit": certificate["git_commit"],
        "source_run_certificate": certificate["_path"],
        "strategy_version": provenance["strategy_version"],
        "strategy_parameter_hash": certificate["identity_hashes"][
            "strategy_parameter_hash"
        ],
        "research_data_version": provenance["research_data_version"],
        "universe_version": provenance["universe_version"],
        "state": overlay["state"],
        "production_approved": overlay["state"] == "PRODUCTION_APPROVED",
        "active_in_latest_daily_run": overlay_active,
        "fallback_strategy": "BASE_FACTOR_ALPHA",
        "fallback_reason": None if overlay_active else overlay["reason"],
        "mechanism_if_approved": "OOS_NET_RESIDUAL_SHRINKAGE",
        "production_effects": {
            "expected_return_changed": overlay_active,
            "ranking_changed": overlay_active,
            "target_weight_may_change": overlay_active,
            "recommendation_may_change": overlay_active,
            "effect_count": len(overlay.get("effects", [])),
        },
        "calibration": {
            "status": provenance["probability_calibration_status"],
            "sample_size": 0,
            "brier_score": None,
            "baseline_brier_score": None,
            "log_loss": None,
            "ece": None,
            "calibration_slope": None,
            "calibration_intercept": None,
        },
        "walk_forward": {
            "status": "NOT_EXECUTED",
            "locked_oos_sessions": 0,
            "base_metrics": None,
            "overlay_metrics": None,
            "benchmark": config.benchmark,
            "transaction_costs_included": False,
        },
        "approval_policy": asdict(OverlayApprovalPolicy()),
        "blockers": list(dict.fromkeys(probability_blockers)),
    }

    universe_path = output_root / "universe_certification.json"
    probability_path = output_root / "probability_overlay_certification.json"
    _write_hashed(universe_document, universe_path)
    _write_hashed(probability_document, probability_path)
    return universe_path, probability_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/latest"))
    args = parser.parse_args()
    for path in export(args.config, args.output):
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
