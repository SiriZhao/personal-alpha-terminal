"""Research-only factor contracts and anti-snooping candidate ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)


@dataclass(frozen=True, slots=True)
class FactorDefinitionAudit:
    name: str
    definition: str
    direction: str
    horizon_sessions: int
    pit_requirement: str
    enabled: bool
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrategyFactorAudit:
    strategy_id: str
    strategy_version: str
    parameter_hash: str
    factors: tuple[FactorDefinitionAudit, ...]
    cross_section_policy: str
    blockers: tuple[str, ...]
    audit_hash: str


def audit_us_adaptive_alpha_core() -> StrategyFactorAudit:
    strategy = USAdaptiveAlphaCoreV1()
    config = strategy.config
    factors = (
        FactorDefinitionAudit(
            "momentum_12_1",
            f"close[t-{config.momentum_skip}] / close[t-{config.momentum_lookback}] - 1",
            "higher_is_better",
            config.horizon_sessions,
            "raw close available_at <= decision cutoff",
            True,
        ),
        FactorDefinitionAudit(
            "trend_slope",
            f"annualized log-price OLS slope over {config.trend_window} sessions",
            "higher_is_better",
            config.horizon_sessions,
            "raw close available_at <= decision cutoff",
            True,
            ("trend_consistency is computed but not used in the composite",),
        ),
        FactorDefinitionAudit(
            "low_volatility",
            f"negative annualized close-return volatility over {config.volatility_window} sessions",
            "lower_is_better",
            config.horizon_sessions,
            "raw close available_at <= decision cutoff",
            True,
        ),
        FactorDefinitionAudit(
            "quality",
            "PIT filing-vintage quality composite",
            "higher_is_better",
            config.horizon_sessions,
            "filing publication/available_at and revisions required",
            config.quality_coefficient != 0,
            ("disabled because no certified PIT fundamentals are supplied",),
        ),
    )
    blockers = (
        "ETF_EQUITY_HETEROGENEOUS_CROSS_SECTION_NOT_VALIDATED",
        "SECTOR_SIZE_NEUTRALIZATION_METADATA_NOT_RESEARCH_CERTIFIED",
        "EXPECTED_ALPHA_COEFFICIENTS_ARE_ENGINEERING_DEFAULTS_NOT_OOS_ESTIMATES",
    )
    material = {
        "strategy_id": strategy.model_id,
        "strategy_version": strategy.version,
        "parameter_hash": config.parameter_fingerprint,
        "factors": factors,
        "cross_section_policy": "current implementation mixes ETF and equity diagnostics",
        "blockers": blockers,
    }
    return StrategyFactorAudit(
        strategy_id=strategy.model_id,
        strategy_version=strategy.version,
        parameter_hash=config.parameter_fingerprint,
        factors=factors,
        cross_section_policy="current implementation mixes ETF and equity diagnostics",
        blockers=blockers,
        audit_hash=fingerprint(material),
    )


@dataclass(frozen=True, slots=True)
class LockedOOSDefinition:
    start: date
    end: date
    session_hash: str
    defined_at: datetime
    maximum_evaluations: int = 1

    def __post_init__(self) -> None:
        if self.start > self.end or self.defined_at.tzinfo is None:
            raise ValueError("locked OOS definition is invalid")
        if not self.session_hash.strip() or self.maximum_evaluations != 1:
            raise ValueError("locked OOS must bind sessions and permit one evaluation")

    @property
    def definition_hash(self) -> str:
        return fingerprint(self)


@dataclass(frozen=True, slots=True)
class StrategyCandidate:
    strategy_id: str
    strategy_version: str
    parameter_hash: str
    data_version: str
    research_manifest_hash: str
    selected_using: str
    locked_oos_definition_hash: str
    status: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.selected_using not in {"TRAIN", "TRAIN_VALIDATION", "ENGINEERING_DEFAULT"}:
            raise ValueError("locked OOS cannot participate in candidate selection")
        if self.created_at.tzinfo is None:
            raise ValueError("candidate created_at must be timezone-aware")
        if not all(
            item.strip()
            for item in (
                self.strategy_id,
                self.strategy_version,
                self.parameter_hash,
                self.data_version,
                self.research_manifest_hash,
                self.locked_oos_definition_hash,
                self.status,
            )
        ):
            raise ValueError("candidate identity is incomplete")

    @property
    def candidate_id(self) -> str:
        identity = asdict(self)
        identity.pop("created_at")
        return f"candidate-{fingerprint(identity)}"


def append_candidate(candidate: StrategyCandidate, ledger: Path) -> None:
    """Append every candidate; never overwrite losers or reuse an identity."""

    ledger.parent.mkdir(parents=True, exist_ok=True)
    existing = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    document = json.loads(json.dumps(asdict(candidate), default=str, sort_keys=True))
    document["candidate_id"] = candidate.candidate_id
    for line in existing:
        prior = json.loads(line)
        if prior.get("candidate_id") == candidate.candidate_id:
            if prior != document:
                raise ValueError(f"candidate identity conflict: {candidate.candidate_id}")
            return
    with ledger.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
