"""ROUND 7: provider architecture tests."""
from __future__ import annotations

from datetime import UTC, date, datetime

from personal_alpha_terminal.quant_engine.historical_pit.providers import (
    ProviderBundle,
    ResearchProviderCapabilities,
    ResearchProviderRegistry,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchDatasetPackage,
)
from tests.unit.quant_engine.historical_pit.fixtures import build_certified_package


class _MarketData:
    provider_id = "licensed-historical"
    provider_version = "2.0"

    def __init__(self, package: ResearchDatasetPackage) -> None:
        self._package = package

    def prices(self):
        return self._package.prices

    def delisting_returns(self):
        return self._package.corporate_actions


class _SecurityMaster:
    provider_id = "licensed-historical"
    provider_version = "2.0"

    def __init__(self, package: ResearchDatasetPackage) -> None:
        self._package = package

    def securities(self):
        return self._package.securities


class _CorporateActions:
    provider_id = "licensed-historical"
    provider_version = "2.0"

    def __init__(self, package: ResearchDatasetPackage) -> None:
        self._package = package

    def corporate_actions(self):
        return self._package.corporate_actions


class _Universe:
    provider_id = "licensed-historical"
    provider_version = "2.0"

    def __init__(self, package: ResearchDatasetPackage) -> None:
        self._package = package

    def memberships(self):
        return self._package.memberships

    def universe_on(self, as_of: date) -> tuple[str, ...]:
        return tuple(
            item.permanent_security_id
            for item in self._package.memberships
            if item.effective_from <= as_of
            and (item.effective_to is None or as_of <= item.effective_to)
        )


def _bundle(package: ResearchDatasetPackage) -> ProviderBundle:
    capabilities = ResearchProviderCapabilities(
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
    return ProviderBundle(
        provider_id="licensed-historical",
        provider_version="2.0",
        capabilities=capabilities,
        market_data=_MarketData(package),
        security_master=_SecurityMaster(package),
        corporate_actions=_CorporateActions(package),
        universe=_Universe(package),
    )


def test_registry_composes_four_providers_into_raw_package() -> None:
    package = build_certified_package()
    registry = ResearchProviderRegistry()
    registry.register(_bundle(package))
    built = registry.build_package(
        "licensed-historical",
        dataset_id="provider-composed",
        retrieved_at=datetime(2024, 6, 1, 12, tzinfo=UTC),
        as_of=package.as_of,
        cutoff=package.cutoff,
    )
    assert isinstance(built, ResearchDatasetPackage)
    assert built.provider == "licensed-historical"
    assert len(built.securities) == len(package.securities)
    assert len(built.prices) == len(package.prices)
    assert len(built.memberships) == len(package.memberships)
    assert len(built.corporate_actions) == len(package.corporate_actions)
    assert built.benchmark_universe_id == "HIST-BENCH"


def test_registry_rejects_unknown_and_duplicate_provider() -> None:
    package = build_certified_package()
    registry = ResearchProviderRegistry()
    registry.register(_bundle(package))
    try:
        registry.build_package(
            "unknown",
            dataset_id="x",
            retrieved_at=datetime(2024, 6, 1, tzinfo=UTC),
            as_of=package.as_of,
            cutoff=package.cutoff,
        )
        raise AssertionError("expected unknown provider rejection")
    except ValueError as error:
        assert "unknown research provider" in str(error)
    try:
        registry.register(_bundle(package))
        raise AssertionError("expected duplicate provider rejection")
    except ValueError as error:
        assert "already registered" in str(error)


def test_capabilities_fingerprint_is_stable() -> None:
    capabilities = ResearchProviderCapabilities(
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
    first = capabilities.fingerprint()
    second = ResearchProviderCapabilities(
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
    ).fingerprint()
    assert first == second
    assert first != ResearchProviderCapabilities(
        provider_id="licensed-historical",
        provider_version="2.0",
        raw_ohlcv=True,
        delisting_history=False,
        delisting_returns=True,
        historical_membership=True,
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        exchange_calendar=True,
    ).fingerprint()
