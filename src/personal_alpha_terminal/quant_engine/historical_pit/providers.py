"""ROUND 7: unified historical PIT provider architecture.

Four provider boundaries keep strategy/research code independent of any single
vendor:

- HistoricalMarketDataProvider  -> raw OHLCV, delisting returns, PIT total-return
                                   vintages
- SecurityMasterProvider        -> permanent identifiers, symbol history, listing
                                   and delisting lifecycle
- CorporateActionProvider       -> PIT-aware corporate actions (economic effective
                                   date, announcement date, provider publication)
- HistoricalUniverseProvider    -> historical membership, universe(as_of_date)

A ResearchProviderRegistry composes concrete providers into a
ResearchProviderPipeline that yields a raw ResearchDatasetPackage.  Nothing in
strategy code ever imports a vendor adapter directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.research_dataset import (
    HistoricalSecurity,
    HistoricalUniverseMembership,
    ResearchCorporateAction,
    ResearchDatasetPackage,
    ResearchPrice,
    ResearchUseScope,
    SecurityType,
)


class HistoricalMarketDataProvider(Protocol):
    """Raw market data boundary: OHLCV, delisting returns and TR vintages."""

    provider_id: str
    provider_version: str

    def prices(self) -> tuple[ResearchPrice, ...]: ...

    def delisting_returns(self) -> tuple[ResearchCorporateAction, ...]: ...


class SecurityMasterProvider(Protocol):
    """Security master boundary: permanent identifiers and symbol history."""

    provider_id: str
    provider_version: str

    def securities(self) -> tuple[HistoricalSecurity, ...]: ...


class CorporateActionProvider(Protocol):
    """Corporate action boundary: PIT-aware actions (not current-adjusted)."""

    provider_id: str
    provider_version: str

    def corporate_actions(self) -> tuple[ResearchCorporateAction, ...]: ...


class HistoricalUniverseProvider(Protocol):
    """Historical membership boundary: universe(as_of_date), not current."""

    provider_id: str
    provider_version: str

    def memberships(self) -> tuple[HistoricalUniverseMembership, ...]: ...

    def universe_on(self, as_of: date) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ResearchProviderCapabilities:
    """Conservative capability claims a provider must back with evidence.

    These are the minimum requirements for HISTORICAL_PIT_CERTIFIED.  A
    provider that cannot claim delisting returns or historical membership is
    honestly classified HISTORICAL_PIT_LIMITED and is never padded.
    """

    provider_id: str
    provider_version: str
    raw_ohlcv: bool
    delisting_history: bool
    delisting_returns: bool
    historical_membership: bool
    identifier_history: bool
    permanent_identifiers: bool
    corporate_actions_pit: bool
    total_return_pit: bool
    exchange_calendar: bool

    def fingerprint(self) -> str:
        return fingerprint(
            {
                "provider_id": self.provider_id,
                "provider_version": self.provider_version,
                "raw_ohlcv": self.raw_ohlcv,
                "delisting_history": self.delisting_history,
                "delisting_returns": self.delisting_returns,
                "historical_membership": self.historical_membership,
                "identifier_history": self.identifier_history,
                "permanent_identifiers": self.permanent_identifiers,
                "corporate_actions_pit": self.corporate_actions_pit,
                "total_return_pit": self.total_return_pit,
                "exchange_calendar": self.exchange_calendar,
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """One composed provider pipeline bound to a single provider identity."""

    provider_id: str
    provider_version: str
    capabilities: ResearchProviderCapabilities
    market_data: HistoricalMarketDataProvider
    security_master: SecurityMasterProvider
    corporate_actions: CorporateActionProvider
    universe: HistoricalUniverseProvider

    def build_package(
        self,
        *,
        dataset_id: str,
        retrieved_at: datetime,
        as_of: date,
        cutoff: datetime,
    ) -> ResearchDatasetPackage:
        """Compose the four providers into an immutable raw research package.

        The package is produced in the RESEARCH_RAW_DATA domain.  It is never
        certified here; certification is a separate gate
        (historical_pit.certification).
        """
        if retrieved_at.tzinfo is None or cutoff.tzinfo is None:
            raise ValueError("provider package timestamps must be timezone-aware")
        if as_of > cutoff.date():
            raise ValueError("package as_of cannot follow cutoff")
        from personal_alpha_terminal.quant_engine.research_dataset import (
            generate_xnys_sessions,
        )

        securities = self.security_master.securities()
        memberships = self.universe.memberships()
        prices = self.market_data.prices()
        actions = self.corporate_actions.corporate_actions()
        benchmark_ids = {
            item.permanent_security_id
            for item in securities
            if item.security_type is SecurityType.BENCHMARK
        }
        calendar = generate_xnys_sessions(
            start=min(
                (item.observation_date for item in prices),
                default=as_of,
            ),
            end=as_of,
            available_at=retrieved_at,
        )
        benchmark_universe_id = (
            next(
                (
                    item.universe_id
                    for item in memberships
                    if item.universe_type is SecurityType.BENCHMARK
                ),
                None,
            )
            if benchmark_ids
            else None
        )
        return ResearchDatasetPackage(
            dataset_id=dataset_id,
            schema_version="historical-pit-provider-v1",
            provider=self.provider_id,
            source=f"provider-pipeline:{self.provider_id}",
            retrieved_at=retrieved_at,
            as_of=as_of,
            cutoff=cutoff,
            use_scope=ResearchUseScope.PRODUCTION_RESEARCH,
            securities=securities,
            memberships=memberships,
            prices=prices,
            corporate_actions=actions,
            calendar=calendar,
            provider_version=self.provider_version,
            acquisition_id=f"{self.provider_id}-{retrieved_at.strftime('%Y%m%dT%H%M%SZ')}",
            benchmark_universe_id=benchmark_universe_id,
        )


class ResearchProviderRegistry:
    """Registry of composed provider bundles; never exposes vendor adapters."""

    def __init__(self) -> None:
        self._bundles: dict[str, ProviderBundle] = {}

    def register(self, bundle: ProviderBundle) -> None:
        if bundle.provider_id in self._bundles:
            raise ValueError(f"provider already registered: {bundle.provider_id}")
        self._bundles[bundle.provider_id] = bundle

    def bundle(self, provider_id: str) -> ProviderBundle:
        try:
            return self._bundles[provider_id]
        except KeyError as error:
            raise ValueError(f"unknown research provider: {provider_id}") from error

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._bundles))

    def build_package(
        self,
        provider_id: str,
        *,
        dataset_id: str,
        retrieved_at: datetime,
        as_of: date,
        cutoff: datetime,
    ) -> ResearchDatasetPackage:
        return self.bundle(provider_id).build_package(
            dataset_id=dataset_id,
            retrieved_at=retrieved_at,
            as_of=as_of,
            cutoff=cutoff,
        )
