"""End-to-end research capability audit with a truthful terminal state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.alpha_research import (
    StrategyCandidate,
    StrategyFactorAudit,
    append_candidate,
    audit_us_adaptive_alpha_core,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.research_data import (
    ResearchDataInventory,
    ResearchDatasetManifest,
    ResearchDatasetState,
    audit_research_inventory,
    persist_research_manifest,
)
from personal_alpha_terminal.quant_engine.strategy_certification import (
    StrategyCertificationArtifact,
    StrategyCertificationEvidence,
    certify_strategy,
    persist_certification_artifact,
)


@dataclass(frozen=True, slots=True)
class ResearchStage:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class AlphaResearchRun:
    run_id: str
    inventory: ResearchDataInventory
    dataset_manifest: ResearchDatasetManifest
    factor_audit: StrategyFactorAudit
    candidate_id: str
    certification: StrategyCertificationArtifact
    stages: tuple[ResearchStage, ...]
    result_hash: str

    def document(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(json.dumps(asdict(self), default=str, sort_keys=True)),
        )


def run_alpha_research_capability_audit(
    inventory: ResearchDataInventory,
    *,
    output_root: Path,
    evaluated_at: datetime,
) -> AlphaResearchRun:
    """Run as far as evidence allows; never fill missing metrics with zeroes."""

    if evaluated_at.tzinfo is None:
        raise ValueError("research evaluated_at must be timezone-aware")
    dataset = audit_research_inventory(inventory)
    factor_audit = audit_us_adaptive_alpha_core()
    strategy_version = f"{factor_audit.strategy_id}:{factor_audit.strategy_version}"
    data_version = dataset.dataset_version or "RESEARCH_DATA_NOT_AVAILABLE"
    universe_version = inventory.latest_universe_version or "UNIVERSE_HISTORY_NOT_AVAILABLE"
    candidate = StrategyCandidate(
        strategy_id=factor_audit.strategy_id,
        strategy_version=factor_audit.strategy_version,
        parameter_hash=factor_audit.parameter_hash,
        data_version=data_version,
        research_manifest_hash=dataset.manifest_hash,
        selected_using="ENGINEERING_DEFAULT",
        locked_oos_definition_hash="NOT_DEFINED_DATA_NOT_CERTIFIABLE",
        status="DIAGNOSTIC_ONLY",
        created_at=evaluated_at,
    )
    costs = TransactionCostConfig()
    evidence = StrategyCertificationEvidence(
        strategy_version=strategy_version,
        parameter_hash=factor_audit.parameter_hash,
        data_version=data_version,
        universe_version=universe_version,
        research_manifest_id=dataset.manifest_hash,
        research_manifest_hash=dataset.manifest_hash,
        research_data_hash=dataset.content_hash,
        candidate_manifest_hash=candidate.candidate_id,
        locked_oos_definition_hash=candidate.locked_oos_definition_hash,
        data_certification_state=dataset.certification_state.value,
        train_end=None,
        validation_end=None,
        oos_start=None,
        oos_end=None,
        oos_sessions=0,
        walk_forward_folds=0,
        pit_valid=False,
        survivorship_controlled=False,
        corporate_actions_valid=False,
        future_rows=0,
        benchmark_same_pit_convention=False,
        net_sharpe=None,
        net_return=None,
        spy_net_return=None,
        qqq_net_return=None,
        max_drawdown=None,
        annual_turnover=None,
        max_position_weight=None,
        stability_score=None,
        commission_bps=costs.commission_bps,
        spread_bps=costs.spread_bps,
        slippage_bps=costs.slippage_bps,
        impact_bps=costs.impact_coefficient_bps,
    )
    certification = certify_strategy(evidence, created_at=evaluated_at)
    stages = (
        ResearchStage(
            "RESEARCH_DATA",
            dataset.certification_state.value,
            "; ".join(dataset.blockers) or "row-level research dataset certified",
        ),
        ResearchStage(
            "PIT_SURVIVORSHIP",
            (
                "BLOCKED"
                if dataset.certification_state is not ResearchDatasetState.CERTIFIED
                else "PASS"
            ),
            "historical membership, delisting and corporate-action vintages required",
        ),
        ResearchStage(
            "FACTOR_RESEARCH",
            "NOT_RUN_UPSTREAM_DATA",
            "definitions audited; IC/Rank IC withheld because the panel is not survivorship-safe",
        ),
        ResearchStage("WALK_FORWARD", "NOT_RUN_UPSTREAM_DATA", "no certifiable folds"),
        ResearchStage("LOCKED_OOS", "NOT_RUN_UPSTREAM_DATA", "no locked OOS was opened"),
        ResearchStage(
            "AFTER_COST",
            "NOT_RUN_UPSTREAM_DATA",
            f"cost model {costs.version} configured but no PnL was fabricated",
        ),
        ResearchStage(
            "BENCHMARK",
            "NOT_RUN_UPSTREAM_DATA",
            "SPY/QQQ comparison requires the same certified research PIT calendar",
        ),
        ResearchStage(
            "CERTIFICATION",
            certification.status.value,
            "; ".join(certification.blockers),
        ),
    )
    identity = {
        "inventory_hash": dataset.inventory_hash,
        "manifest_hash": dataset.manifest_hash,
        "factor_audit_hash": factor_audit.audit_hash,
        "candidate_id": candidate.candidate_id,
        "certification_id": certification.artifact_id,
        "stages": stages,
    }
    result_hash = fingerprint(identity)
    run_id = f"alpha-research-{result_hash[:16]}"
    run_root = output_root / run_id
    persist_research_manifest(dataset, run_root / "research-manifests")
    append_candidate(candidate, run_root / "candidate-ledger.jsonl")
    persist_certification_artifact(certification, run_root / "certification-evidence")
    run = AlphaResearchRun(
        run_id,
        inventory,
        dataset,
        factor_audit,
        candidate.candidate_id,
        certification,
        stages,
        result_hash,
    )
    target = run_root / "result.json"
    rendered = json.dumps(run.document(), ensure_ascii=False, indent=2, sort_keys=True)
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"research result is immutable: {target}")
    target.write_text(rendered, encoding="utf-8")
    return run
