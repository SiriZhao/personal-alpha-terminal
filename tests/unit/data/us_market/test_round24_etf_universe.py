"""ROUND24 ETF universe evaluation tests (C2, C3, C7)."""
from __future__ import annotations

from datetime import UTC, date, datetime

from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentDirectorySnapshot,
    CurrentSecurityMasterRecord,
    CurrentSecurityType,
    SecurityEligibilityObservation,
    SurvivorshipStatus,
)
from personal_alpha_terminal.data.us_market.etf_universe import (
    EtfEligibilityRules,
    evaluate_etf_universe,
)
from personal_alpha_terminal.instruments.catalog import default_catalog
from personal_alpha_terminal.instruments.master import BenchmarkRole

DECISION = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
UNIVERSE_DATE = date(2026, 8, 13)


def _record(symbol: str, *, exchange: str = "XNAS") -> CurrentSecurityMasterRecord:
    return CurrentSecurityMasterRecord(
        security_id=f"NASDAQTRADER:{exchange}:{symbol}",
        symbol=symbol,
        company_name=f"{symbol} test",
        security_type=CurrentSecurityType.ETF,
        exchange=exchange,
        currency="USD",
        country="US",
        listing_date=date(2015, 1, 1),
        delisting_date=None,
        active_from=date(2015, 1, 1),
        active_to=None,
        is_common_stock=False,
        is_etf=True,
        is_adr=False,
        is_reit=False,
        is_preferred=False,
        is_warrant=False,
        is_unit=False,
        is_right=False,
        is_otc=False,
        sector=None,
        industry=None,
        test_issue=False,
        financial_status="N",
        source="test",
        effective_date=date(2026, 8, 13),
        available_at=DECISION,
    )


def _observation(
    record: CurrentSecurityMasterRecord,
    *,
    sessions: int = 400,
) -> SecurityEligibilityObservation:
    return SecurityEligibilityObservation(
        security_id=record.security_id,
        symbol=record.symbol,
        as_of_date=UNIVERSE_DATE,
        available_at=DECISION,
        latest_price=120.0,
        observed_sessions=sessions,
        average_dollar_volume=500_000_000.0,
        median_dollar_volume=450_000_000.0,
        valid_bar_coverage=0.99,
        missing_ratio=0.01,
        corporate_action_integrity=False,
        feature_available=True,
    )


def _snapshot(*records: CurrentSecurityMasterRecord) -> CurrentDirectorySnapshot:
    from personal_alpha_terminal.data.us_market.broad_universe import (
        SymbolDirectoryCapabilities,
    )

    return CurrentDirectorySnapshot(
        dataset_id="test-directory",
        provider="test",
        retrieved_at=DECISION,
        source_timestamp="test",
        records=records,
        content_hash="test",
        manifest_hash="test",
        survivorship_status=SurvivorshipStatus.UNVERIFIED,
        capabilities=SymbolDirectoryCapabilities(),
    )


def test_voo_qqq_tradable_with_dual_benchmark_role() -> None:
    catalog = default_catalog()
    records = (_record("VOO", exchange="ARCX"), _record("QQQ"), _record("TQQQ"))
    snapshot = _snapshot(*records)
    observations = tuple(
        _observation(item) for item in records if item.symbol in {"VOO", "QQQ", "TQQQ"}
    )
    eligibility = evaluate_etf_universe(
        snapshot,
        observations,
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
    )
    tradable = {item.symbol for item in eligibility.tradable_eligible}
    assert "VOO" in tradable
    assert "QQQ" in tradable
    roles = {item.symbol: item.benchmark_role for item in eligibility.benchmark_roles}
    assert roles.get("VOO") is BenchmarkRole.BOTH
    assert roles.get("QQQ") is BenchmarkRole.BOTH
    blocked = {item.symbol for item in eligibility.blocked_complex}
    assert "TQQQ" in blocked


def test_same_security_id_keeps_roles_separated() -> None:
    """security_id stays the same; BENCHMARK and TRADABLE roles coexist (C2)."""
    catalog = default_catalog()
    qqq = _record("QQQ")
    eligibility = evaluate_etf_universe(
        _snapshot(qqq),
        (_observation(qqq),),
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
    )
    classification = eligibility.tradable_eligible[0]
    assert classification.symbol == "QQQ"
    assert classification.benchmark_role is BenchmarkRole.BOTH
    assert classification.sleeve.value == "ETF_CORE"
    assert classification.benchmark_policy == "BENCHMARK_UNAVAILABLE_SELF"


def test_leveraged_and_inverse_blocked_by_default() -> None:
    catalog = default_catalog()
    records = tuple(_record(symbol) for symbol in ("TQQQ", "SQQQ", "UPRO", "SPXU", "UVXY"))
    eligibility = evaluate_etf_universe(
        _snapshot(*records),
        tuple(_observation(item) for item in records),
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
    )
    assert {item.symbol for item in eligibility.blocked_complex} == {
        "TQQQ", "SQQQ", "UPRO", "SPXU", "UVXY",
    }
    assert not eligibility.tradable_eligible


def test_uncatalogued_etf_research_only_not_tradable() -> None:
    catalog = default_catalog()
    unknown = _record("ZZZZ")
    eligibility = evaluate_etf_universe(
        _snapshot(unknown),
        (_observation(unknown),),
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
    )
    assert not eligibility.tradable_eligible
    assert "ZZZZ" in {item.symbol for item in eligibility.research_only}
    assert eligibility.exclusions[unknown.security_id] == ("UNCLASSIFIED_ETF",)


def test_future_observation_rejected() -> None:
    catalog = default_catalog()
    voo = _record("VOO", exchange="ARCX")
    observation = SecurityEligibilityObservation(
        security_id=voo.security_id,
        symbol="VOO",
        as_of_date=UNIVERSE_DATE,
        available_at=datetime(2026, 8, 15, tzinfo=UTC),
        latest_price=120.0,
        observed_sessions=400,
        average_dollar_volume=500_000_000.0,
        median_dollar_volume=450_000_000.0,
        valid_bar_coverage=0.99,
        missing_ratio=0.01,
        corporate_action_integrity=False,
        feature_available=True,
    )
    eligibility = evaluate_etf_universe(
        _snapshot(voo),
        (observation,),
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
    )
    assert not eligibility.tradable_eligible
    assert eligibility.exclusions[voo.security_id] == ("FUTURE_DATA_NOT_ALLOWED",)


def test_etf_min_price_and_liquidity_gates_apply() -> None:
    catalog = default_catalog()
    qqq = _record("QQQ")
    observation = SecurityEligibilityObservation(
        security_id=qqq.security_id,
        symbol="QQQ",
        as_of_date=UNIVERSE_DATE,
        available_at=DECISION,
        latest_price=3.0,
        observed_sessions=400,
        average_dollar_volume=1_000.0,
        median_dollar_volume=1_000.0,
        valid_bar_coverage=0.99,
        missing_ratio=0.01,
        corporate_action_integrity=False,
        feature_available=True,
    )
    eligibility = evaluate_etf_universe(
        _snapshot(qqq),
        (observation,),
        catalog,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=EtfEligibilityRules(minimum_price=10.0),
    )
    assert not eligibility.tradable_eligible
    assert "PRICE_BELOW_THRESHOLD_OR_MISSING" in eligibility.exclusions[qqq.security_id]
