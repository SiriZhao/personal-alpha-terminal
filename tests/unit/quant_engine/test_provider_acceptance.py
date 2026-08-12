from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import (
    AdjustmentKind,
    HistoricalSecurity,
    HistoricalUniverseMembership,
    ResearchCorporateAction,
    ResearchDatasetPackage,
    ResearchPrice,
    ResearchUseScope,
    SecurityType,
    certify_research_package,
    generate_xnys_sessions,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderAcceptanceStatus,
    ProviderContract,
    accept_research_provider,
)

CUTOFF = datetime(2024, 1, 6, tzinfo=UTC)


def _price(
    security_id: str,
    ticker: str,
    session: object,
    index: int,
    *,
    total_return: float | None = None,
) -> ResearchPrice:
    date_value = session.session_date
    available = datetime.combine(date_value, datetime.min.time(), tzinfo=UTC).replace(hour=22)
    return ResearchPrice(
        security_id,
        ticker,
        date_value,
        available,
        "XNYS",
        100 + index,
        102 + index,
        99 + index,
        101 + index,
        1_000_000,
        AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE,
        total_return if total_return is not None else 1000 + index,
        available,
        f"tr-{ticker}-{date_value.isoformat()}",
        "licensed provider",
        "test-provider",
    )


def _production_package() -> ResearchDatasetPackage:
    securities = (
        HistoricalSecurity(
            "SEC-A",
            "A",
            date(2024, 1, 1),
            None,
            "XNYS",
            date(2024, 1, 1),
            None,
            "UNKNOWN",
            SecurityType.US_EQUITY,
            datetime(2023, 12, 20, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            cusip="CUSIP-A",
            figi="FIGI-A",
            provider_security_id="PROV-A",
            company_id="CO-A",
            company_name="Company A",
        ),
        HistoricalSecurity(
            "SEC-B",
            "B",
            date(2024, 1, 1),
            None,
            "XNYS",
            date(2024, 1, 1),
            None,
            "UNKNOWN",
            SecurityType.US_EQUITY,
            datetime(2023, 12, 20, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            provider_security_id="PROV-B",
            company_id="CO-B",
            company_name="Company B",
        ),
        HistoricalSecurity(
            "SEC-DEAD",
            "DEAD",
            date(2024, 1, 1),
            date(2024, 1, 3),
            "XNYS",
            date(2024, 1, 1),
            date(2024, 1, 3),
            "BANKRUPTCY",
            SecurityType.US_EQUITY,
            datetime(2023, 12, 20, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            provider_security_id="PROV-DEAD",
            company_id="CO-DEAD",
            company_name="Company Dead",
        ),
        HistoricalSecurity(
            "BENCH-SPY",
            "SPY",
            date(2024, 1, 1),
            None,
            "ARCX",
            date(2024, 1, 1),
            None,
            "UNKNOWN",
            SecurityType.BENCHMARK,
            datetime(2023, 12, 20, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            provider_security_id="PROV-SPY",
            company_id="CO-SPY",
            company_name="SPDR S&P 500 ETF Trust",
        ),
        HistoricalSecurity(
            "BENCH-QQQ",
            "QQQ",
            date(2024, 1, 1),
            None,
            "XNAS",
            date(2024, 1, 1),
            None,
            "UNKNOWN",
            SecurityType.BENCHMARK,
            datetime(2023, 12, 20, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            provider_security_id="PROV-QQQ",
            company_id="CO-QQQ",
            company_name="Invesco QQQ Trust",
        ),
    )
    memberships = (
        HistoricalUniverseMembership(
            "SEC-A",
            "US-EQUITY",
            SecurityType.US_EQUITY,
            date(2024, 1, 2),
            None,
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC),
            "HISTORICAL_TIMELINE",
            "licensed provider",
            "test-provider",
        ),
        HistoricalUniverseMembership(
            "SEC-B",
            "US-EQUITY",
            SecurityType.US_EQUITY,
            date(2024, 1, 2),
            None,
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC),
            "HISTORICAL_TIMELINE",
            "licensed provider",
            "test-provider",
        ),
        HistoricalUniverseMembership(
            "SEC-DEAD",
            "US-EQUITY",
            SecurityType.US_EQUITY,
            date(2024, 1, 2),
            date(2024, 1, 3),
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC),
            "HISTORICAL_TIMELINE",
            "licensed provider",
            "test-provider",
        ),
        HistoricalUniverseMembership(
            "BENCH-SPY",
            "BENCHMARK-US",
            SecurityType.BENCHMARK,
            date(2024, 1, 2),
            None,
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC),
            "HISTORICAL_TIMELINE",
            "licensed provider",
            "test-provider",
        ),
        HistoricalUniverseMembership(
            "BENCH-QQQ",
            "BENCHMARK-US",
            SecurityType.BENCHMARK,
            date(2024, 1, 2),
            None,
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC),
            "HISTORICAL_TIMELINE",
            "licensed provider",
            "test-provider",
        ),
    )
    sessions = generate_xnys_sessions(date(2024, 1, 2), date(2024, 1, 5), available_at=CUTOFF)
    prices: list[ResearchPrice] = []
    for index, session in enumerate(sessions):
        for security_id, ticker in (
            ("SEC-A", "A"),
            ("SEC-B", "B"),
            ("BENCH-SPY", "SPY"),
            ("BENCH-QQQ", "QQQ"),
        ):
            prices.append(_price(security_id, ticker, session, index))
        if session.session_date <= date(2024, 1, 3):
            prices.append(_price("SEC-DEAD", "DEAD", session, index))
    actions = (
        ResearchCorporateAction(
            "SEC-A",
            "CASH_DIVIDEND",
            date(2024, 1, 4),
            date(2024, 1, 3),
            datetime(2024, 1, 3, 12, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            cash_amount=0.25,
            revision_id="div-r1",
        ),
        ResearchCorporateAction(
            "SEC-DEAD",
            "DELISTING",
            date(2024, 1, 3),
            date(2024, 1, 2),
            datetime(2024, 1, 2, 12, tzinfo=UTC),
            "licensed provider",
            "test-provider",
            terminal_return=-0.50,
            terminal_price=5.0,
            revision_id="delist-r1",
        ),
    )
    return ResearchDatasetPackage(
        "historical-provider-test",
        "research-package-v1",
        "test-provider",
        "licensed provider",
        CUTOFF,
        date(2024, 1, 5),
        CUTOFF,
        ResearchUseScope.PRODUCTION_RESEARCH,
        securities,
        memberships,
        tuple(prices),
        actions,
        sessions,
        provider_version="test-v1",
        acquisition_id="test-acquisition-1",
        license_scope="PRODUCTION_TEST_LICENSE",
        benchmark_universe_id="BENCHMARK-US",
    )


def _contract(
    *,
    provider_id: str = "test-provider",
    local_research_use_allowed: bool = True,
    derived_research_allowed: bool = True,
    known_limitations: tuple[str, ...] = (),
) -> ProviderContract:
    return ProviderContract(
        provider_id=provider_id,
        provider_version="test-v1",
        provider_security_id_scheme="provider-id",
        permanent_identifiers=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        benchmark_same_pit=True,
        license_scope="PRODUCTION_TEST_LICENSE",
        local_research_use_allowed=local_research_use_allowed,
        derived_research_allowed=derived_research_allowed,
        schema_mapping_version="test-schema-v1",
        source_identity="licensed test provider",
        known_limitations=known_limitations,
    )


def test_complete_production_package_passes_acceptance() -> None:
    result = accept_research_provider(
        _production_package(),
        _contract(),
        evaluated_at=CUTOFF,
    )
    assert result.status is ProviderAcceptanceStatus.PASS
    assert result.blockers == ()
    assert result.manifest.certification_state is ResearchDatasetState.CERTIFIED
    assert result.manifest.production_eligible is True
    assert result.manifest.delisted_count == 1
    assert result.manifest.active_security_count == 4
    assert result.manifest.provider_version == "test-v1"
    assert result.manifest.acquisition_id == "test-acquisition-1"
    assert result.manifest.benchmark_universe_id == "BENCHMARK-US"
    assert result.manifest.coverage_hash
    assert result.manifest.corporate_action_identity


def test_provider_limitations_produce_pass_with_limitations() -> None:
    result = accept_research_provider(
        _production_package(),
        _contract(known_limitations=("provider-coverage-unknown",)),
        evaluated_at=CUTOFF,
    )
    assert result.status is ProviderAcceptanceStatus.PASS_WITH_LIMITATIONS
    assert "provider-coverage-unknown" in result.warnings


def test_test_fixture_never_passes_provider_acceptance() -> None:
    package = replace(
        _production_package(),
        use_scope=ResearchUseScope.TEST_FIXTURE,
    )
    result = accept_research_provider(package, _contract(), evaluated_at=CUTOFF)
    assert result.status is ProviderAcceptanceStatus.NOT_CERTIFIABLE
    assert "TEST_FIXTURE_IS_NOT_PRODUCTION_RESEARCH" in result.blockers


def test_provider_identity_and_license_mismatch_fail_closed() -> None:
    wrong_provider = accept_research_provider(
        _production_package(),
        _contract(provider_id="other-provider"),
        evaluated_at=CUTOFF,
    )
    assert wrong_provider.status is ProviderAcceptanceStatus.NOT_CERTIFIABLE
    assert "PROVIDER_ID_MISMATCH" in wrong_provider.blockers
    no_license = accept_research_provider(
        _production_package(),
        _contract(local_research_use_allowed=False),
        evaluated_at=CUTOFF,
    )
    assert "LICENSE_DOES_NOT_ALLOW_LOCAL_DERIVED_RESEARCH" in no_license.blockers


def test_required_research_coverage_fails_closed() -> None:
    result = accept_research_provider(
        _production_package(),
        _contract(),
        required_start=date(2023, 1, 1),
        required_end=date(2024, 1, 5),
        evaluated_at=CUTOFF,
    )
    assert result.status is ProviderAcceptanceStatus.NOT_CERTIFIABLE
    assert "STRATEGY_PERIOD_START_COVERAGE_INCOMPLETE" in result.blockers


def test_missing_benchmark_fails_acceptance() -> None:
    package = _production_package()
    without_benchmark = replace(
        package,
        securities=tuple(
            item for item in package.securities if item.security_type is not SecurityType.BENCHMARK
        ),
        memberships=tuple(
            item
            for item in package.memberships
            if item.universe_type is not SecurityType.BENCHMARK
        ),
        prices=tuple(
            item
            for item in package.prices
            if item.permanent_security_id not in {"BENCH-SPY", "BENCH-QQQ"}
        ),
    )
    result = accept_research_provider(without_benchmark, _contract(), evaluated_at=CUTOFF)
    assert result.status is ProviderAcceptanceStatus.NOT_CERTIFIABLE
    assert "BENCHMARK_SYMBOLS_INCOMPLETE" in result.blockers


def test_manifest_metadata_identity_is_reproducible() -> None:
    first = certify_research_package(_production_package())
    second = certify_research_package(_production_package())
    assert first.manifest_hash == second.manifest_hash
    assert first.content_hash == second.content_hash
    assert first.corporate_action_identity == second.corporate_action_identity
