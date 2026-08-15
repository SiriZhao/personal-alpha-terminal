"""ROUND26 P0: CURRENT OPERATIONAL size / sector exposure.

Current operational exposure is strictly separated from HISTORICAL_PIT
exposure.  Current data may protect the next trading day (risk gates); it is
never written into historical PIT tables and never used for historical
neutralization.

Size evidence carries full provenance (shares outstanding x price with
timestamps and sources).  Sector evidence uses a deterministic, versioned
SEC SIC -> normalized-sector mapping; unknown classifications stay UNKNOWN
and are never silently reclassified.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import or_
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import SecurityMaster, UniverseMembership

SIZE_RISK_DEGRADED = "SIZE_RISK_DEGRADED"
SIZE_RISK_PASS = "SIZE_RISK_PASS"
SECTOR_RISK_DEGRADED = "SECTOR_RISK_DEGRADED"
SECTOR_RISK_PASS = "SECTOR_RISK_PASS"

SIZE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("MICRO", 0.0, 300_000_000.0),
    ("SMALL", 300_000_000.0, 2_000_000_000.0),
    ("MID", 2_000_000_000.0, 10_000_000_000.0),
    ("LARGE", 10_000_000_000.0, 200_000_000_000.0),
    ("MEGA", 200_000_000_000.0, float("inf")),
)


def size_bucket(market_cap: float | None) -> str:
    if market_cap is None or market_cap <= 0:
        return "UNKNOWN"
    for name, lower, upper in SIZE_BUCKETS:
        if lower <= market_cap < upper:
            return name
    return "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CurrentCompanySizeObservation:
    ticker: str
    issuer_id: str | None
    shares_outstanding: float | None
    shares_timestamp: str | None
    shares_source: str | None
    decision_price: float | None
    price_timestamp: str | None
    price_source: str | None
    market_cap: float | None
    market_cap_calculation: str
    acquired_at: str
    available_at: str
    source_quality: str

    def document(self) -> dict[str, object]:
        return asdict(self)


def build_current_size_exposure(
    session: Session,
    *,
    as_of: datetime,
    target_symbols: tuple[str, ...] = (),
) -> dict[str, object]:
    """Read current operational size evidence with honest coverage."""

    membership_rows = session.execute(
        select(
            SecurityMaster.symbol,
            UniverseMembership.market_cap,
        )
        .join(UniverseMembership, UniverseMembership.stock_id == SecurityMaster.id)
        .where(
            UniverseMembership.effective_from <= as_of.date(),
            or_(
                UniverseMembership.effective_to.is_(None),
                UniverseMembership.effective_to >= as_of.date(),
            ),
            UniverseMembership.available_time <= as_of,
        )
    ).all()
    covered: dict[str, float] = {}
    for symbol, market_cap in membership_rows:
        if market_cap is not None and float(market_cap) > 0:
            covered[str(symbol)] = float(market_cap)
    target_weights: dict[str, float] = {}
    if target_symbols:
        weight = 1.0 / len(target_symbols) if target_symbols else 0.0
        target_weights = {symbol: weight for symbol in target_symbols}
    bucket_weights: dict[str, float] = {}
    for symbol, weight in target_weights.items():
        bucket = size_bucket(covered.get(symbol))
        bucket_weights[bucket] = bucket_weights.get(bucket, 0.0) + weight
    covered_weight = sum(
        weight for symbol, weight in target_weights.items() if symbol in covered
    )
    unknown_weight = 1.0 - covered_weight
    coverage = len(covered) / len(target_symbols) if target_symbols else 0.0
    status = SIZE_RISK_PASS if coverage >= 0.9 else SIZE_RISK_DEGRADED
    if not target_symbols:
        status = SIZE_RISK_DEGRADED
    small_micro = bucket_weights.get("SMALL", 0.0) + bucket_weights.get("MICRO", 0.0)
    caps = [value for value in covered.values()]
    weighted_cap = (
        sum(target_weights.get(symbol, 0.0) * market_cap for symbol, market_cap in covered.items())
        if covered
        else None
    )
    return {
        "exposure_kind": "CURRENT_OPERATIONAL",
        "historical_pit_boundary": "CURRENT DATA NEVER WRITTEN TO HISTORICAL PIT TABLES",
        "status": status,
        "size_coverage": round(coverage, 6),
        "securities_with_market_cap": len(covered),
        "portfolio_symbols": len(target_symbols),
        "portfolio_unknown_size_weight": round(unknown_weight, 6),
        "portfolio_small_micro_exposure": round(small_micro, 6),
        "bucket_weights": {key: round(value, 6) for key, value in sorted(bucket_weights.items())},
        "largest_size_bucket": (
            max(bucket_weights, key=bucket_weights.get) if bucket_weights else "UNKNOWN"
        ),
        "portfolio_weighted_market_cap": weighted_cap,
        "smallest_holding_market_cap": min(caps) if caps else None,
        "source": "UniverseMembership.market_cap (PIT-visible membership evidence)",
        "missing_never_assumed_large_cap": True,
    }


# Deterministic, versioned SEC SIC -> normalized sector mapping.
# Only top-level SIC divisions are mapped; anything unmapped stays UNKNOWN.
SIC_SECTOR_MAPPING_VERSION = "sec-sic-divisions-v1"


def sic_to_sector(sic_code: str | None) -> str:
    if not sic_code or not str(sic_code).strip().isdigit():
        return "UNKNOWN"
    code = int(str(sic_code).strip())
    if 100 <= code <= 999:
        return "AGRICULTURE_MINING_CONSTRUCTION"
    if 1000 <= code <= 1499:
        return "MINING"
    if 1500 <= code <= 1799:
        return "CONSTRUCTION"
    if 2000 <= code <= 3999:
        return "MANUFACTURING"
    if 4000 <= code <= 4999:
        return "TRANSPORT_UTILITIES"
    if 5000 <= code <= 5199:
        return "WHOLESALE_TRADE"
    if 5200 <= code <= 5999:
        return "RETAIL_TRADE"
    if 6000 <= code <= 6799:
        return "FINANCE_INSURANCE_REAL_ESTATE"
    if 7000 <= code <= 8999:
        return "SERVICES"
    if 9100 <= code <= 9729:
        return "PUBLIC_ADMINISTRATION"
    return "UNKNOWN"


def build_current_sector_exposure(
    *,
    sector_rows: dict[str, str | None],
    target_symbols: tuple[str, ...] = (),
    classification_source: str = "SEC_SIC",
) -> dict[str, object]:
    """Sector exposure from normalized, source-attributed classifications."""

    normalized: dict[str, str] = {}
    for symbol, raw in sector_rows.items():
        normalized[symbol] = (
            sic_to_sector(raw) if classification_source == "SEC_SIC" else str(raw or "UNKNOWN")
        )
    if not target_symbols:
        return {
            "exposure_kind": "CURRENT_OPERATIONAL",
            "classification_source": classification_source,
            "mapping_version": SIC_SECTOR_MAPPING_VERSION,
            "status": SECTOR_RISK_DEGRADED,
            "sector_coverage": 0.0,
            "portfolio_unknown_sector_weight": 1.0,
            "note": "no formal target symbols; exposure unavailable, not assumed safe",
        }
    weights = {symbol: 1.0 / len(target_symbols) for symbol in target_symbols}
    sector_weights: dict[str, float] = {}
    for symbol, weight in weights.items():
        sector = normalized.get(symbol, "UNKNOWN")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
    covered_weight = sum(
        weight
        for symbol, weight in weights.items()
        if normalized.get(symbol) not in (None, "UNKNOWN")
    )
    coverage = len(
        [symbol for symbol in target_symbols if normalized.get(symbol) not in (None, "UNKNOWN")]
    ) / len(target_symbols)
    status = SECTOR_RISK_PASS if coverage >= 0.9 else SECTOR_RISK_DEGRADED
    ranked = sorted(sector_weights.items(), key=lambda item: -item[1])
    hhi = sum(value * value for value in sector_weights.values())
    return {
        "exposure_kind": "CURRENT_OPERATIONAL",
        "classification_source": classification_source,
        "mapping_version": SIC_SECTOR_MAPPING_VERSION,
        "status": status,
        "sector_coverage": round(coverage, 6),
        "portfolio_unknown_sector_weight": round(sector_weights.get("UNKNOWN", 0.0), 6),
        "top_sector": ranked[0][0] if ranked else "UNKNOWN",
        "top_3_sectors": [name for name, _weight in ranked[:3]],
        "sector_hhi": round(hhi, 6),
        "sector_weights": {key: round(value, 6) for key, value in sorted(sector_weights.items())},
        "missing_never_assumed_safe": True,
    }
