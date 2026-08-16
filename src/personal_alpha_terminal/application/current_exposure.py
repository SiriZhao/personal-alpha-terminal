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

import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import or_, select
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


def acquire_current_size_observations(
    *, symbols: tuple[str, ...], as_of: datetime
) -> tuple[tuple[CurrentCompanySizeObservation, ...], dict[str, object]]:
    """Acquire current-only market-cap evidence without touching PIT tables.

    Provider-reported cap is preferred.  We intentionally do not infer shares
    from volume or backfill an unknown value.  Every successful observation is
    labelled CURRENT_ONLY and is limited to next-trade operational risk.
    """
    started = perf_counter()
    observations: list[CurrentCompanySizeObservation] = []
    failures: dict[str, str] = {}
    acquired_at = datetime.now(UTC)
    try:
        import yfinance as yf
    except ImportError:
        return (), {"provider": "YAHOO_FINANCE", "status": "UNAVAILABLE", "reason": "IMPORT_ERROR"}
    for symbol in symbols:
        try:
            fast_info: Any = yf.Ticker(symbol).fast_info
            # yfinance fast_info is a provider payload rather than our own
            # schema.  It currently exposes camelCase keys, while older
            # provider versions used snake_case.  Accept both explicitly;
            # no value is inferred when neither is present.
            market_cap_raw = fast_info.get("marketCap", fast_info.get("market_cap"))
            price_raw = fast_info.get("lastPrice", fast_info.get("last_price"))
            shares_raw = fast_info.get("shares")
            market_cap = (
                float(market_cap_raw)
                if market_cap_raw and float(market_cap_raw) > 0
                else None
            )
            price = float(price_raw) if price_raw and float(price_raw) > 0 else None
            shares = float(shares_raw) if shares_raw and float(shares_raw) > 0 else None
            calculation = "PROVIDER_REPORTED_MARKET_CAP"
            if market_cap is None and shares is not None and price is not None:
                market_cap = shares * price
                calculation = "VERIFIED_CURRENT_SHARES_X_CURRENT_PRICE"
            elif market_cap is None:
                calculation = "UNKNOWN"
            observations.append(
                CurrentCompanySizeObservation(
                    ticker=symbol,
                    issuer_id=None,
                    shares_outstanding=shares,
                    shares_timestamp=acquired_at.isoformat() if shares is not None else None,
                    shares_source="YAHOO_FAST_INFO_CURRENT" if shares is not None else None,
                    decision_price=price,
                    price_timestamp=acquired_at.isoformat() if price is not None else None,
                    price_source="YAHOO_FAST_INFO_CURRENT" if price is not None else None,
                    market_cap=market_cap,
                    market_cap_calculation=calculation,
                    acquired_at=acquired_at.isoformat(),
                    available_at=acquired_at.isoformat(),
                    source_quality="CURRENT_ONLY",
                )
            )
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
            failures[symbol] = type(error).__name__
    return tuple(observations), {
        "provider": "YAHOO_FINANCE",
        "status": "CURRENT_ONLY",
        "requested": len(symbols),
        "returned": len(observations),
        "failures": failures,
        "wall_seconds": round(perf_counter() - started, 4),
        "decision_time_boundary": as_of.isoformat(),
    }


def acquire_current_sec_sic(
    *, symbols: tuple[str, ...], security_types: dict[str, str]
) -> tuple[dict[str, str | None], dict[str, object]]:
    """Fetch current SEC SIC classifications for US common stocks only.

    ETFs, funds and non-US/ADR-like symbols without an unambiguous SEC ticker
    identity remain UNKNOWN.  This is current operational classification, not
    historical sector membership.
    """
    started = perf_counter()
    result: dict[str, str | None] = {symbol: None for symbol in symbols}
    statuses: dict[str, str] = {}
    try:
        request = urllib.request.Request(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "personal-alpha-terminal/1.0 contact local"},
        )
        with urllib.request.urlopen(request, timeout=15.0) as response:  # noqa: S310
            directory = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return result, {"provider": "SEC", "status": "UNAVAILABLE", "reason": type(error).__name__}
    ticker_to_cik = {
        str(row.get("ticker", "")).upper(): int(row["cik_str"])
        for row in directory.values()
        if isinstance(row, dict) and row.get("ticker") and row.get("cik_str")
    }
    for symbol in symbols:
        if security_types.get(symbol) != "stock":
            statuses[symbol] = "NON_OPERATING_SECURITY_UNKNOWN"
            continue
        cik = ticker_to_cik.get(symbol.upper())
        if cik is None:
            statuses[symbol] = "SEC_IDENTITY_UNAVAILABLE"
            continue
        try:
            request = urllib.request.Request(
                f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                headers={"User-Agent": "personal-alpha-terminal/1.0 contact local"},
            )
            with urllib.request.urlopen(request, timeout=15.0) as response:  # noqa: S310
                submission = json.loads(response.read().decode("utf-8"))
            sic = submission.get("sic")
            result[symbol] = str(sic) if isinstance(sic, int | str) and str(sic).isdigit() else None
            statuses[symbol] = "SEC_SIC_CURRENT_ONLY" if result[symbol] else "SEC_SIC_UNAVAILABLE"
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            statuses[symbol] = type(error).__name__.upper()
    return result, {
        "provider": "SEC",
        "status": "CURRENT_ONLY",
        "requested": len(symbols),
        "classified": sum(value is not None for value in result.values()),
        "symbol_status": statuses,
        "wall_seconds": round(perf_counter() - started, 4),
    }


def build_current_size_exposure(
    session: Session,
    *,
    as_of: datetime,
    target_symbols: tuple[str, ...] = (),
    current_observations: tuple[CurrentCompanySizeObservation, ...] = (),
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
    provenance: dict[str, dict[str, object]] = {}
    for observation in current_observations:
        if observation.market_cap is not None and observation.market_cap > 0:
            covered[observation.ticker] = observation.market_cap
        provenance[observation.ticker] = observation.document()
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
            max(bucket_weights, key=lambda key: bucket_weights[key])
            if bucket_weights
            else "UNKNOWN"
        ),
        "portfolio_weighted_market_cap": weighted_cap,
        "smallest_holding_market_cap": min(caps) if caps else None,
        "source": "UniverseMembership.market_cap (PIT-visible membership evidence)",
        "market_cap_observations": provenance,
        "current_only_observations": len(current_observations),
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
