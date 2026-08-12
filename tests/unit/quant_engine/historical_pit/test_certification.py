"""ROUND 7: survivorship classification and certification verdict tests."""
from __future__ import annotations

from dataclasses import replace

from personal_alpha_terminal.quant_engine.historical_pit.certification import (
    HistoricalPitVerdict,
    SurvivorshipClassification,
    certify_historical_pit,
    classify_survivorship,
)
from personal_alpha_terminal.quant_engine.historical_pit.providers import (
    ResearchProviderCapabilities,
)
from personal_alpha_terminal.quant_engine.historical_pit.versioning import (
    build_version,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchUseScope,
    certify_research_package,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderContract,
)
from tests.unit.quant_engine.historical_pit.fixtures import build_certified_package


def _capabilities(**overrides) -> ResearchProviderCapabilities:
    values = dict(
        provider_id="licensed-historical",
        provider_version="2.0",
        raw_ohlcv=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        exchange_calendar=True,
    )
    values.update(overrides)
    return ResearchProviderCapabilities(**values)


def _contract() -> ProviderContract:
    return ProviderContract(
        provider_id="licensed-historical",
        provider_version="2.0",
        provider_security_id_scheme="PROVIDER_PERMANENT_ID",
        permanent_identifiers=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        benchmark_same_pit=True,
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        schema_mapping_version="historical-pit-provider-v1",
        source_identity="licensed-historical:2.0",
    )


def test_full_certified_package_is_survivorship_safe() -> None:
    package = build_certified_package()
    evidence = classify_survivorship(package, _capabilities())
    assert evidence.classification is SurvivorshipClassification.SURVIVORSHIP_SAFE
    assert evidence.delisted_retained >= 1
    assert evidence.delisting_returns_present >= 1
    assert evidence.historical_membership_rows >= 6
    assert evidence.reasons == ()


def test_missing_delisting_returns_is_survivorship_limited() -> None:
    package = build_certified_package()
    capabilities = _capabilities(delisting_returns=False)
    evidence = classify_survivorship(package, capabilities)
    assert evidence.classification is SurvivorshipClassification.SURVIVORSHIP_LIMITED
    assert "DELISTING_RETURNS_NOT_CLAIMED" in evidence.reasons


def test_missing_historical_membership_is_survivorship_limited() -> None:
    package = build_certified_package()
    capabilities = _capabilities(historical_membership=False)
    evidence = classify_survivorship(package, capabilities)
    assert evidence.classification is SurvivorshipClassification.SURVIVORSHIP_LIMITED
    assert "HISTORICAL_MEMBERSHIP_NOT_CLAIMED" in evidence.reasons


def test_current_snapshot_membership_is_rejected_for_survivorship() -> None:
    package = build_certified_package()
    memberships = tuple(
        replace(item, membership_source_type="CURRENT_SNAPSHOT")
        for item in package.memberships
    )
    evidence = classify_survivorship(replace(package, memberships=memberships), _capabilities())
    assert evidence.classification is not SurvivorshipClassification.SURVIVORSHIP_SAFE
    assert "CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED" in evidence.reasons


def test_certify_historical_pit_verdict_certified_when_all_gates_pass() -> None:
    package = build_certified_package()
    # Certification requires PRODUCTION_RESEARCH scope.
    package = replace(package, use_scope=ResearchUseScope.PRODUCTION_RESEARCH)
    manifest = certify_research_package(package)
    version = build_version(package, manifest)
    certification = certify_historical_pit(
        package,
        _contract(),
        _capabilities(),
        version,
    )
    assert certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED
    assert certification.blockers == ()


def test_certify_historical_pit_verdict_limited_when_provider_lacks_capability() -> None:
    package = build_certified_package()
    package = replace(package, use_scope=ResearchUseScope.PRODUCTION_RESEARCH)
    manifest = certify_research_package(package)
    version = build_version(package, manifest)
    certification = certify_historical_pit(
        package,
        _contract(),
        _capabilities(delisting_returns=False, historical_membership=False),
        version,
    )
    assert certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_LIMITED
    assert "DELISTING_RETURNS_NOT_CLAIMED" in certification.blockers
    assert "HISTORICAL_MEMBERSHIP_NOT_CLAIMED" in certification.blockers
