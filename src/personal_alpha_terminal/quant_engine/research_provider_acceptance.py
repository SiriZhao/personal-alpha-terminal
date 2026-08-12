"""Provider-neutral historical research provider acceptance audit.

The acceptance audit verifies that a provider contract, its licensing terms,
and the actual row-level research package together meet the survivorship-safe
PIT research boundary.  It does not replace row certification; it consumes the
normalized research manifest and adds provider-specific checks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetManifestV2,
    ResearchDatasetPackage,
    ResearchUseScope,
    SecurityType,
    certify_research_package,
)


class ProviderAcceptanceStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class ProviderContract:
    provider_id: str
    provider_version: str
    provider_security_id_scheme: str
    permanent_identifiers: bool
    delisting_history: bool
    delisting_returns: bool
    historical_membership: bool
    corporate_actions_pit: bool
    total_return_pit: bool
    benchmark_same_pit: bool
    license_scope: str
    local_research_use_allowed: bool
    derived_research_allowed: bool
    schema_mapping_version: str
    source_identity: str
    known_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.provider_id,
                self.provider_version,
                self.provider_security_id_scheme,
                self.license_scope,
                self.schema_mapping_version,
                self.source_identity,
            )
        ):
            raise ValueError("provider contract identity is incomplete")

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True, slots=True)
class ProviderAcceptanceEvidence:
    acceptance_id: str
    status: ProviderAcceptanceStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    contract: ProviderContract
    manifest: ResearchDatasetManifestV2
    content_hash: str
    evaluated_at: datetime

    def document(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "acceptance_id": self.acceptance_id,
            "status": self.status.value,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "contract": self.contract.document(),
            "manifest": self.manifest.document(),
            "content_hash": self.content_hash,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
        return cast(dict[str, object], json.loads(json.dumps(payload, default=str, sort_keys=True)))


class HistoricalResearchDataProvider(Protocol):
    """Provider-neutral adapter boundary for licensed research packages."""

    provider_id: str
    provider_version: str
    contract: ProviderContract

    def load(self, source: Path) -> ResearchDatasetPackage: ...


def accept_research_provider(
    package: ResearchDatasetPackage,
    contract: ProviderContract,
    *,
    required_start: date | None = None,
    required_end: date | None = None,
    evaluated_at: datetime | None = None,
) -> ProviderAcceptanceEvidence:
    """Run row certification plus provider-level acceptance checks.

    A TEST_FIXTURE package is intentionally never accepted for production
    research, even when its row certification state is CERTIFIED.
    """

    now = evaluated_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("acceptance evaluated_at must be timezone-aware")
    manifest = certify_research_package(
        package,
        required_start=required_start,
        required_end=required_end,
    )
    blockers: list[str] = []
    warnings: list[str] = list(contract.known_limitations)

    if package.use_scope is not ResearchUseScope.PRODUCTION_RESEARCH:
        blockers.append("TEST_FIXTURE_IS_NOT_PRODUCTION_RESEARCH")
    if package.provider != contract.provider_id:
        blockers.append("PROVIDER_ID_MISMATCH")
    if not contract.local_research_use_allowed or not contract.derived_research_allowed:
        blockers.append("LICENSE_DOES_NOT_ALLOW_LOCAL_DERIVED_RESEARCH")
    if not contract.delisting_history:
        blockers.append("DELISTING_HISTORY_NOT_CLAIMED")
    if not contract.delisting_returns:
        blockers.append("DELISTING_RETURNS_NOT_CLAIMED")
    if not contract.historical_membership:
        blockers.append("HISTORICAL_MEMBERSHIP_NOT_CLAIMED")
    if not contract.corporate_actions_pit:
        blockers.append("CORPORATE_ACTIONS_PIT_NOT_CLAIMED")
    if not contract.total_return_pit:
        blockers.append("TOTAL_RETURN_PIT_NOT_CLAIMED")
    if not contract.benchmark_same_pit:
        blockers.append("BENCHMARK_PIT_NOT_CLAIMED")

    if manifest.certification_state is not ResearchDatasetState.CERTIFIED:
        blockers.extend(manifest.blockers)

    if contract.permanent_identifiers:
        missing_identifiers = tuple(
            item.permanent_security_id
            for item in package.securities
            if not item.provider_security_id and not item.cusip and not item.figi
        )
        if missing_identifiers:
            blockers.append("PROVIDER_PERMANENT_IDENTIFIERS_MISSING")
    if contract.delisting_history:
        if manifest.delisted_count == 0:
            warnings.append("NO_DELISTED_CASES_OBSERVED")
        elif not _delisted_lifecycle_complete(package):
            blockers.append("DELISTED_LIFECYCLE_INCOMPLETE")
    if contract.delisting_returns and not _delisting_returns_complete(package):
        blockers.append("DELISTING_RETURN_EVIDENCE_INCOMPLETE")
    if contract.historical_membership and manifest.membership_count == 0:
        blockers.append("HISTORICAL_MEMBERSHIP_MISSING")
    if contract.corporate_actions_pit and manifest.corporate_action_count == 0:
        blockers.append("CORPORATE_ACTION_PIT_EVIDENCE_MISSING")
    if contract.total_return_pit and not manifest.total_return_certified:
        blockers.append("TOTAL_RETURN_PIT_EVIDENCE_INCOMPLETE")
    if contract.benchmark_same_pit:
        benchmark_blockers = _benchmark_checks(package, required_start, required_end)
        blockers.extend(benchmark_blockers)

    status = (
        ProviderAcceptanceStatus.NOT_CERTIFIABLE
        if blockers
        else ProviderAcceptanceStatus.PASS_WITH_LIMITATIONS
        if warnings
        else ProviderAcceptanceStatus.PASS
    )
    identity = fingerprint(
        {
            "contract": contract.document(),
            "manifest": manifest.document(),
            "blockers": tuple(sorted(set(blockers))),
            "warnings": tuple(sorted(set(warnings))),
        }
    )
    return ProviderAcceptanceEvidence(
        acceptance_id=f"provider-acceptance-{identity}",
        status=status,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        contract=contract,
        manifest=manifest,
        content_hash=manifest.content_hash,
        evaluated_at=now,
    )


def persist_provider_acceptance(
    evidence: ProviderAcceptanceEvidence,
    root: Path,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{evidence.acceptance_id}.json"
    rendered = json.dumps(
        evidence.document(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable provider acceptance: {target}")
    target.write_text(rendered, encoding="utf-8")
    return target


def _delisted_lifecycle_complete(package: ResearchDatasetPackage) -> bool:
    delisted = {
        item.permanent_security_id
        for item in package.securities
        if item.delisting_date is not None
    }
    terminal_types = {"DELISTING", "MERGER", "ACQUISITION"}
    for security_id in delisted:
        actions = tuple(
            item
            for item in package.corporate_actions
            if item.permanent_security_id == security_id
            and item.action_type in terminal_types
        )
        if not actions:
            return False
    return True


def _delisting_returns_complete(package: ResearchDatasetPackage) -> bool:
    terminal_types = {"DELISTING", "MERGER", "ACQUISITION"}
    for item in package.corporate_actions:
        if item.action_type in terminal_types and item.terminal_return is None:
            return False
    return True


def _benchmark_checks(
    package: ResearchDatasetPackage,
    required_start: date | None,
    required_end: date | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    benchmark = {
        item.ticker: item.permanent_security_id
        for item in package.securities
        if item.security_type is SecurityType.BENCHMARK
        and item.ticker in {"SPY", "QQQ"}
    }
    if set(benchmark) != {"SPY", "QQQ"}:
        return ("BENCHMARK_SYMBOLS_INCOMPLETE",)
    for symbol, security_id in sorted(benchmark.items()):
        prices = tuple(
            item
            for item in package.prices
            if item.permanent_security_id == security_id
        )
        if not prices:
            blockers.append(f"BENCHMARK_PRICE_MISSING:{symbol}")
            continue
        start = min(item.observation_date for item in prices)
        end = max(item.observation_date for item in prices)
        if required_start is not None and start > required_start:
            blockers.append(f"BENCHMARK_START_COVERAGE_INCOMPLETE:{symbol}")
        if required_end is not None and end < required_end:
            blockers.append(f"BENCHMARK_END_COVERAGE_INCOMPLETE:{symbol}")
    if not package.benchmark_universe_id:
        blockers.append("BENCHMARK_UNIVERSE_IDENTITY_MISSING")
    return tuple(dict.fromkeys(blockers))
