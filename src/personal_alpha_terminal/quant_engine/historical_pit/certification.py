"""ROUND 7: historical PIT certification framework and final verdict.

The verdict is evidence-driven and never padded:

- HISTORICAL_PIT_CERTIFIED  -> full survivorship-safe PIT research eligibility
- HISTORICAL_PIT_LIMITED    -> a provider lacks delisting returns and/or
                               historical membership (or another blocker)

The framework combines row certification (certify_research_package), provider
acceptance (accept_research_provider), and survivorship classification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.historical_pit.identifiers import (
    IdentifierRegistryResult,
    build_instrument_registry,
)
from personal_alpha_terminal.quant_engine.historical_pit.providers import (
    ResearchProviderCapabilities,
)
from personal_alpha_terminal.quant_engine.historical_pit.versioning import (
    ResearchDatasetVersion,
)
from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetPackage,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderAcceptanceEvidence,
    ProviderContract,
    accept_research_provider,
)


class SurvivorshipClassification(StrEnum):
    SURVIVORSHIP_SAFE = "SURVIVORSHIP_SAFE"
    SURVIVORSHIP_LIMITED = "SURVIVORSHIP_LIMITED"
    SURVIVORSHIP_UNVERIFIED = "SURVIVORSHIP_UNVERIFIED"


class HistoricalPitVerdict(StrEnum):
    HISTORICAL_PIT_CERTIFIED = "HISTORICAL_PIT_CERTIFIED"
    HISTORICAL_PIT_LIMITED = "HISTORICAL_PIT_LIMITED"


@dataclass(frozen=True, slots=True)
class SurvivorshipEvidence:
    classification: SurvivorshipClassification
    reasons: tuple[str, ...]
    delisted_retained: int
    delisting_returns_present: int
    historical_membership_rows: int
    identifier_registry: IdentifierRegistryResult

    def document(self) -> dict[str, object]:
        return {
            "classification": self.classification.value,
            "reasons": list(self.reasons),
            "delisted_retained": self.delisted_retained,
            "delisting_returns_present": self.delisting_returns_present,
            "historical_membership_rows": self.historical_membership_rows,
            "identifier_registry": self.identifier_registry.document(),
        }


@dataclass(frozen=True, slots=True)
class HistoricalPitCertification:
    verdict: HistoricalPitVerdict
    survivorship: SurvivorshipEvidence
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    provider_id: str
    provider_version: str
    certification_state: ResearchDatasetState
    version: ResearchDatasetVersion
    acceptance: ProviderAcceptanceEvidence | None
    content_hash: str
    evaluated_at: datetime

    def document(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "verdict": self.verdict.value,
            "survivorship": self.survivorship.document(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "certification_state": self.certification_state.value,
            "version": self.version.document(),
            "acceptance": self.acceptance.document() if self.acceptance is not None else None,
            "content_hash": self.content_hash,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
        return cast(dict[str, Any], __import__("json").loads(
            __import__("json").dumps(payload, default=str, sort_keys=True)
        ))

    @property
    def certification_hash(self) -> str:
        return fingerprint(self.document())


def classify_survivorship(
    package: ResearchDatasetPackage,
    capabilities: ResearchProviderCapabilities,
) -> SurvivorshipEvidence:
    """Classify survivorship strictly from provider evidence.

    SURVIVORSHIP_SAFE requires delisted securities retained, historical
    membership (not a current snapshot), delisting returns for terminal events,
    and permanent identifiers with ticker history.
    """
    reasons: list[str] = []
    delisted = {item.permanent_security_id for item in package.securities if item.delisting_date}
    registry = build_instrument_registry(package.securities)
    terminal_types = {"DELISTING", "MERGER", "ACQUISITION"}
    delisting_returns_present = 0
    for action in package.corporate_actions:
        if action.action_type in terminal_types and action.terminal_return is not None:
            delisting_returns_present += 1
    historical_membership_rows = sum(
        1
        for item in package.memberships
        if item.membership_source_type.upper() != "CURRENT_SNAPSHOT"
    )

    if not capabilities.delisting_history:
        reasons.append("DELISTING_HISTORY_NOT_CLAIMED")
    if not capabilities.delisting_returns:
        reasons.append("DELISTING_RETURNS_NOT_CLAIMED")
    if not capabilities.historical_membership:
        reasons.append("HISTORICAL_MEMBERSHIP_NOT_CLAIMED")
    if not capabilities.permanent_identifiers:
        reasons.append("PERMANENT_IDENTIFIERS_NOT_CLAIMED")
    if not capabilities.identifier_history:
        reasons.append("IDENTIFIER_HISTORY_NOT_CLAIMED")
    if not package.securities:
        reasons.append("SECURITY_MASTER_EMPTY")
    if registry.blockers:
        reasons.extend(registry.blockers)
    if delisted and delisting_returns_present < len(delisted):
        reasons.append(
            "DELISTING_RETURN_EVIDENCE_INCOMPLETE"
            f":{delisting_returns_present}/{len(delisted)}"
        )
    if historical_membership_rows == 0:
        reasons.append("HISTORICAL_MEMBERSHIP_MISSING")
    if any(
        item.membership_source_type.upper() == "CURRENT_SNAPSHOT"
        for item in package.memberships
    ):
        reasons.append("CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED")

    classification = (
        SurvivorshipClassification.SURVIVORSHIP_SAFE
        if not reasons
        else SurvivorshipClassification.SURVIVORSHIP_LIMITED
        if package.securities
        else SurvivorshipClassification.SURVIVORSHIP_UNVERIFIED
    )
    return SurvivorshipEvidence(
        classification=classification,
        reasons=tuple(sorted(set(reasons))),
        delisted_retained=len(delisted),
        delisting_returns_present=delisting_returns_present,
        historical_membership_rows=historical_membership_rows,
        identifier_registry=registry,
    )


def certify_historical_pit(
    package: ResearchDatasetPackage,
    contract: ProviderContract,
    capabilities: ResearchProviderCapabilities,
    version: ResearchDatasetVersion,
    *,
    required_start: date | None = None,
    required_end: date | None = None,
    evaluated_at: datetime | None = None,
) -> HistoricalPitCertification:
    """Combine row certification, provider acceptance and survivorship evidence.

    The verdict is HISTORICAL_PIT_CERTIFIED only when every gate passes.  Any
    blocker (including a missing delisting-return or historical-membership
    claim) yields HISTORICAL_PIT_LIMITED.  No evidence is inferred or padded.
    """
    from datetime import UTC

    now = evaluated_at or datetime.now(UTC)
    acceptance = accept_research_provider(
        package,
        contract,
        required_start=required_start,
        required_end=required_end,
        evaluated_at=now,
    )
    blockers: list[str] = []
    warnings: list[str] = list(acceptance.warnings)
    if acceptance.status.value != "PASS":
        blockers.extend(acceptance.blockers)
    survivorship = classify_survivorship(package, capabilities)
    if survivorship.classification is not SurvivorshipClassification.SURVIVORSHIP_SAFE:
        blockers.extend(survivorship.reasons)
    if version.certification_state is not ResearchDatasetState.CERTIFIED:
        blockers.append("DATASET_NOT_CERTIFIED")
    verdict = (
        HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED
        if not blockers
        else HistoricalPitVerdict.HISTORICAL_PIT_LIMITED
    )
    return HistoricalPitCertification(
        verdict=verdict,
        survivorship=survivorship,
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(set(warnings))),
        provider_id=package.provider,
        provider_version=package.provider_version,
        certification_state=acceptance.manifest.certification_state,
        version=version,
        acceptance=acceptance,
        content_hash=package.content_hash,
        evaluated_at=now,
    )
