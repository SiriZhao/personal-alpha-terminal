"""ROUND25 PHASE 12: size / sector / ETF look-through honest closure.

Current market-cap evidence and PIT historical market-cap evidence are kept
strictly separate.  Current data may feed CURRENT_SIZE_DIAGNOSTIC only; it can
never be used for historical neutralization.  Sector coverage is validated
against the security master; missing data is SECTOR_EXPOSURE_NOT_VALIDATED.
ETF constituent look-through is UNAVAILABLE without a stable weights source,
so the correlation fallback remains the only honest overlap signal.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import Price, SecurityMaster


def build_exposure_closure(
    session: Session, *, as_of: datetime
) -> dict[str, object]:
    """Read-only evidence report; nothing is neutralized or assumed safe."""

    total = int(
        session.scalar(
            select(func.count()).select_from(SecurityMaster).where(
                SecurityMaster.market == "US"
            )
        )
        or 0
    )
    with_sector = int(
        session.scalar(
            select(func.count())
            .select_from(SecurityMaster)
            .where(
                SecurityMaster.market == "US",
                SecurityMaster.industry_id.is_not(None),
            )
        )
        or 0
    )
    with_prices = int(
        session.scalar(
            select(func.count(func.distinct(Price.stock_id))).where(
                Price.price_type == "unadjusted_ohlcv",
                Price.available_time <= as_of,
            )
        )
        or 0
    )
    sector_coverage = (with_sector / total) if total else 0.0
    price_coverage = (with_prices / total) if total else 0.0
    return {
        "size_exposure": {
            "status": "SIZE_EXPOSURE_UNAVAILABLE",
            "historical_pit_market_cap": "UNAVAILABLE",
            "current_market_cap_diagnostic": (
                "CURRENT_SIZE_DIAGNOSTIC"
                if with_prices
                else "UNAVAILABLE"
            ),
            "current_used_for_historical_neutralization": False,
            "note": (
                "current market-cap evidence (when present) is a diagnostic "
                "only and is never used for historical neutralization"
            ),
        },
        "sector_exposure": {
            "status": (
                "SECTOR_EXPOSURE_NOT_VALIDATED"
                if sector_coverage < 0.9
                else "SECTOR_COVERAGE_PARTIAL"
            ),
            "sector_coverage": round(sector_coverage, 6),
            "securities_with_sector": with_sector,
            "us_securities_total": total,
            "note": "industry linkage only; missing data is never treated as safe",
        },
        "etf_look_through": {
            "status": "ETF_LOOKTHROUGH_UNAVAILABLE",
            "constituent_weights_source": None,
            "holdings_as_of": None,
            "fallback": "CORRELATION_CLUSTERING_ONLY",
            "note": (
                "no stable, verifiable constituent-weight source is configured; "
                "ETF overlap continues to be reported via return correlation "
                "clustering only"
            ),
        },
        "price_coverage": {
            "status": "PARTIAL" if price_coverage < 1.0 else "FULL",
            "coverage": round(price_coverage, 6),
            "securities_with_prices": with_prices,
        },
    }
