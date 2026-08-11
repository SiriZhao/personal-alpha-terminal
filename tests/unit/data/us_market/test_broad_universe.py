from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentSecurityType,
    EligibilityRules,
    SecurityEligibilityObservation,
    dollar_volume_observation,
    evaluate_broad_universe,
    parse_symbol_directories,
)

DECISION = datetime(2026, 8, 12, 1, tzinfo=UTC)
UNIVERSE_DATE = date(2026, 8, 12)

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|\
Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N
ADR1|Example Plc American Depositary Shares|Q|N|N|100|N|N
WTEST|Example Corp Warrants|Q|N|N|100|N|N
File Creation Time: 0811202612:11|||||||
"""

OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
SPY|SPDR S&P 500 ETF Trust|A|SPY|Y|100|N|SPY
File Creation Time: 0811202612:11|||||||
"""


def _snapshot():
    return parse_symbol_directories(NASDAQ, OTHER, retrieved_at=DECISION)


def _observation(symbol: str, *, available_at: datetime = DECISION):
    record = next(item for item in _snapshot().records if item.symbol == symbol)
    return SecurityEligibilityObservation(
        security_id=record.security_id,
        symbol=symbol,
        as_of_date=UNIVERSE_DATE - timedelta(days=1),
        available_at=available_at,
        latest_price=100.0,
        observed_sessions=3,
        average_dollar_volume=2_000.0,
        median_dollar_volume=2_000.0,
        valid_bar_coverage=1.0,
        missing_ratio=0.0,
        corporate_action_integrity=True,
        feature_available=True,
    )


def _rules() -> EligibilityRules:
    return EligibilityRules(
        minimum_price=5.0,
        minimum_trading_sessions=3,
        minimum_average_dollar_volume=1_000.0,
        minimum_median_dollar_volume=1_000.0,
        minimum_valid_bar_coverage=0.9,
        maximum_missing_ratio=0.1,
    )


def test_security_master_classifies_and_segregates_equity_etf_and_adr() -> None:
    records = {item.symbol: item for item in _snapshot().records}

    assert records["AAPL"].security_type is CurrentSecurityType.COMMON_STOCK
    assert records["QQQ"].security_type is CurrentSecurityType.ETF
    assert records["ADR1"].security_type is CurrentSecurityType.ADR
    assert records["WTEST"].security_type is CurrentSecurityType.WARRANT
    assert records["IBM"].exchange == "XNYS"


def test_etf_adr_and_warrant_never_enter_default_equity_alpha_universe() -> None:
    result = evaluate_broad_universe(
        _snapshot(),
        tuple(_observation(symbol) for symbol in ("AAPL", "QQQ", "ADR1", "WTEST")),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )

    assert [item.symbol for item in result.factor_eligible] == ["AAPL"]
    assert "SECURITY_TYPE_ETF_NOT_ELIGIBLE" in result.exclusions[
        "NASDAQTRADER:XNAS:QQQ"
    ]


def test_future_directory_membership_cannot_change_past_universe() -> None:
    snapshot = _snapshot()
    future = replace(
        next(item for item in snapshot.records if item.symbol == "IBM"),
        symbol="FUTR",
        security_id="NASDAQTRADER:XNYS:FUTR",
        active_from=UNIVERSE_DATE + timedelta(days=1),
        effective_date=UNIVERSE_DATE + timedelta(days=1),
    )
    changed = replace(snapshot, records=(*snapshot.records, future))
    baseline = evaluate_broad_universe(
        snapshot,
        (_observation("AAPL"),),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )
    result = evaluate_broad_universe(
        changed,
        (_observation("AAPL"),),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )

    assert result.snapshot_hash == baseline.snapshot_hash
    assert result.factor_eligible == baseline.factor_eligible


def test_future_available_observation_is_rejected() -> None:
    result = evaluate_broad_universe(
        _snapshot(),
        (_observation("AAPL", available_at=DECISION + timedelta(seconds=1)),),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )

    assert not result.factor_eligible
    assert "FUTURE_DATA_NOT_ALLOWED" in result.exclusions[
        "NASDAQTRADER:XNAS:AAPL"
    ]


def test_adv_uses_only_sessions_strictly_before_universe_date() -> None:
    security = next(item for item in _snapshot().records if item.symbol == "AAPL")
    base_rows = tuple(
        (
            UNIVERSE_DATE - timedelta(days=offset),
            DECISION - timedelta(days=offset),
            10.0,
            100.0,
        )
        for offset in (3, 2, 1)
    )
    baseline = dollar_volume_observation(
        security,
        base_rows,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        expected_sessions=3,
        corporate_action_integrity=True,
        feature_available=True,
    )
    changed = dollar_volume_observation(
        security,
        (*base_rows, (UNIVERSE_DATE, DECISION, 1_000_000.0, 1_000_000.0)),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        expected_sessions=3,
        corporate_action_integrity=True,
        feature_available=True,
    )

    assert changed == baseline
    assert baseline.average_dollar_volume == pytest.approx(1_000.0)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"latest_price": 4.99}, "PRICE_BELOW_THRESHOLD_OR_MISSING"),
        ({"observed_sessions": 2}, "INSUFFICIENT_TRADING_HISTORY"),
        ({"valid_bar_coverage": 0.89}, "VALID_BAR_COVERAGE_INSUFFICIENT"),
        ({"average_dollar_volume": 999.0}, "ADV_BELOW_THRESHOLD_OR_MISSING"),
        ({"corporate_action_integrity": False}, "CORPORATE_ACTION_INTEGRITY_INCOMPLETE"),
    ],
)
def test_professional_eligibility_gates_fail_closed(
    change: dict[str, object], reason: str
) -> None:
    observation = replace(_observation("AAPL"), **change)
    result = evaluate_broad_universe(
        _snapshot(),
        (observation,),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )

    assert not result.factor_eligible
    assert reason in result.exclusions["NASDAQTRADER:XNAS:AAPL"]


def test_same_directory_and_observations_are_reproducible() -> None:
    first = evaluate_broad_universe(
        _snapshot(),
        (_observation("AAPL"), _observation("IBM")),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )
    second = evaluate_broad_universe(
        _snapshot(),
        (_observation("IBM"), _observation("AAPL")),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )

    assert first.snapshot_hash == second.snapshot_hash
    assert first.counts() == second.counts()


def test_later_invocation_with_identical_visible_pit_content_keeps_content_hash() -> None:
    snapshot = _snapshot()
    observation = _observation("AAPL")
    first = evaluate_broad_universe(
        snapshot,
        (observation,),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=_rules(),
    )
    second = evaluate_broad_universe(
        snapshot,
        (observation,),
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION + timedelta(minutes=5),
        rules=_rules(),
    )

    assert first.snapshot_hash == second.snapshot_hash


def test_current_directory_explicitly_disallows_historical_survivorship_claim() -> None:
    snapshot = _snapshot()

    assert not snapshot.historical_use_allowed
    assert not snapshot.capabilities.historical_membership
    assert not snapshot.capabilities.delistings
    assert not snapshot.capabilities.identifier_history
