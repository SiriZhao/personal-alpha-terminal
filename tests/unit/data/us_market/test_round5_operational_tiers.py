"""ROUND 5: two-tier PIT separation and current-operational quarantine tests."""
from __future__ import annotations

from datetime import UTC, date, datetime

from personal_alpha_terminal.data.us_market.broad_universe import (
    BroadUniverseEligibility,
    EligibilityRules,
    PitQualification,
    SecurityEligibilityObservation,
    evaluate_broad_universe,
    parse_symbol_directories,
)

DECISION = datetime(2026, 8, 12, 21, tzinfo=UTC)
UNIVERSE_DATE = date(2026, 8, 12)

NASDAQ = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
    "Round Lot Size|ETF|NextShares\n"
    "AAA|AAA Holdings Common Stock|Q|N|N|100|N|N\n"
    "BBB|BBB Corp Common Stock|Q|N|N|100|N|N\n"
    "CCC|CCC Industries Common Stock|Q|N|N|100|N|N\n"
    "DDD|DDD Group Common Stock|Q|N|N|100|N|N\n"
    "File Creation Time: 0812202612:00|||||||\n"
)
OTHER = (
    "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
    "File Creation Time: 0812202612:00|||||||\n"
)


def _observation(
    symbol: str,
    *,
    corporate_action_integrity: bool = False,
    sessions: int = 300,
    price: float = 50.0,
    adv: float = 30_000_000.0,
) -> SecurityEligibilityObservation:
    return SecurityEligibilityObservation(
        security_id=f"NASDAQTRADER:XNAS:{symbol}",
        symbol=symbol,
        as_of_date=UNIVERSE_DATE,
        available_at=DECISION - __import__("datetime").timedelta(hours=1),
        latest_price=price,
        observed_sessions=sessions,
        average_dollar_volume=adv,
        median_dollar_volume=adv,
        valid_bar_coverage=1.0,
        missing_ratio=0.0,
        corporate_action_integrity=corporate_action_integrity,
        feature_available=True,
    )


def _eligibility(
    *,
    require_pit_total_return: bool,
    quarantined: frozenset[str] = frozenset(),
) -> BroadUniverseEligibility:
    snapshot = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=DECISION)
    observations = tuple(_observation(symbol) for symbol in ("AAA", "BBB", "CCC", "DDD"))
    return evaluate_broad_universe(
        snapshot,
        observations,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=EligibilityRules(
            minimum_trading_sessions=50,
            require_pit_total_return=require_pit_total_return,
        ),
        quarantined=quarantined,
    )


def test_operational_tier_is_not_collapsed_by_degraded_historical_certification() -> None:
    strict = _eligibility(require_pit_total_return=True)
    operational = _eligibility(require_pit_total_return=False)

    # The strict certified tier is empty (no certified PIT total-return ledger),
    # but the CURRENT_OPERATIONAL_PIT tier still contains all current securities.
    assert strict.qualification is PitQualification.HISTORICAL_RESEARCH_PIT
    assert operational.qualification is PitQualification.CURRENT_OPERATIONAL_PIT
    assert strict.pit_status == "HISTORICAL_RESEARCH_PIT"
    assert operational.pit_status == "CURRENT_OPERATIONAL_PIT"
    assert len(strict.factor_eligible) == 0
    assert len(operational.factor_eligible) == 4


def test_current_operational_tier_keeps_all_data_gates() -> None:
    operational = _eligibility(require_pit_total_return=False)
    # All four pass the current identity/price/history/liquidity/factor gates.
    assert [item.symbol for item in operational.factor_eligible] == [
        "AAA",
        "BBB",
        "CCC",
        "DDD",
    ]


def test_current_operational_tier_still_enforces_current_data_rules() -> None:
    snapshot = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=DECISION)
    observations = (
        _observation("AAA"),
        _observation("BBB", sessions=10),  # insufficient history
        _observation("CCC", price=1.0),  # below price threshold
        _observation("DDD", adv=100_000.0),  # below liquidity threshold
    )
    eligibility = evaluate_broad_universe(
        snapshot,
        observations,
        universe_date=UNIVERSE_DATE,
        decision_time=DECISION,
        rules=EligibilityRules(
            minimum_trading_sessions=50,
            require_pit_total_return=False,
        ),
    )
    assert [item.symbol for item in eligibility.factor_eligible] == ["AAA"]
    assert "INSUFFICIENT_TRADING_HISTORY" in eligibility.exclusions["NASDAQTRADER:XNAS:BBB"]
    assert "PRICE_BELOW_THRESHOLD_OR_MISSING" in eligibility.exclusions[
        "NASDAQTRADER:XNAS:CCC"
    ]
    assert "ADV_BELOW_THRESHOLD_OR_MISSING" in eligibility.exclusions[
        "NASDAQTRADER:XNAS:DDD"
    ]


def test_quarantined_security_is_excluded_from_current_operational_universe() -> None:
    operational = _eligibility(
        require_pit_total_return=False,
        quarantined=frozenset({"NASDAQTRADER:XNAS:CCC"}),
    )
    symbols = [item.symbol for item in operational.factor_eligible]
    assert "CCC" not in symbols
    assert "QUARANTINED" in operational.exclusions["NASDAQTRADER:XNAS:CCC"]


def test_universe_funnel_and_identity_are_deterministic() -> None:
    first = _eligibility(require_pit_total_return=False)
    second = _eligibility(require_pit_total_return=False)
    assert first.snapshot_hash == second.snapshot_hash
    assert first.rules_fingerprint == second.rules_fingerprint
    assert first.factor_eligible == second.factor_eligible
