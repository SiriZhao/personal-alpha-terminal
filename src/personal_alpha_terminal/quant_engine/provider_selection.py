"""Official-evidence provider capability claims for market-data selection.

The claims here are conservative.  A capability is ``UNKNOWN`` when official
documentation does not prove it; selection does not upgrade ``UNKNOWN`` to
``YES``.  Provider acceptance still requires a real licensed package.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import cast

from personal_alpha_terminal.quant_engine.historical_data_acquisition import CapabilityStatus


@dataclass(frozen=True, slots=True)
class MarketDataCapabilityClaim:
    provider_id: str
    product_plan: str
    capability: str
    status: CapabilityStatus
    official_url: str
    checked_at: date
    exact_official_statement: str
    confidence: str

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return cast(dict[str, object], json.loads(json.dumps(payload, default=str)))


def provider_capability_claims() -> tuple[MarketDataCapabilityClaim, ...]:
    """Return a machine-readable capability matrix grounded in official pages."""

    checked = date(2026, 8, 12)
    claims: list[MarketDataCapabilityClaim] = []

    def add(
        provider_id: str,
        product_plan: str,
        capability: str,
        status: CapabilityStatus,
        official_url: str,
        statement: str,
        confidence: str,
    ) -> None:
        claims.append(
            MarketDataCapabilityClaim(
                provider_id=provider_id,
                product_plan=product_plan,
                capability=capability,
                status=status,
                official_url=official_url,
                checked_at=checked,
                exact_official_statement=statement,
                confidence=confidence,
            )
        )

    crsp = "https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases"
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "permanent_security_id",
        CapabilityStatus.YES,
        crsp,
        "PERMNO is a proprietary, permanent identifier used to track US-listed equities over time.",
        "HIGH_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "delisting_lifecycle",
        CapabilityStatus.YES,
        crsp,
        (
            "Daily and monthly market data and corporate actions for over 36,000 "
            "active and inactive securities."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "delisting_return",
        CapabilityStatus.PARTIAL,
        "https://www.crsp.org/wp-content/uploads/guides/CRSP10_Year_US_Stock_Database_Guide.pdf",
        (
            "Delisting information is documented; exact terminal treatment "
            "depends on the licensed edition and contract."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "historical_membership",
        CapabilityStatus.PARTIAL,
        crsp,
        (
            "Active/inactive security population is available; project membership "
            "must be reconstructed and audited."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "pit_total_return_vintages",
        CapabilityStatus.PARTIAL,
        crsp,
        (
            "CRSP has return data; the exact PIT vintage contract must be "
            "confirmed from the licensed data dictionary."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "corporate_actions",
        CapabilityStatus.PARTIAL,
        crsp,
        (
            "Daily and monthly market data and corporate actions for over 36,000 "
            "active and inactive securities."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "pit_corporate_action_availability",
        CapabilityStatus.UNKNOWN,
        crsp,
        "The public product page does not prove PIT announcement availability or action revisions.",
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )
    add(
        "crsp_us_stock",
        "CRSP US Stock Databases",
        "benchmark_same_pit",
        CapabilityStatus.UNKNOWN,
        crsp,
        "The public product page does not prove SPY/QQQ benchmark PIT compatibility.",
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    norgate = "https://norgatedata.com/data-package-faq.php"
    norgate_packages = "https://norgatedata.com/stockmarketpackages.php"
    add(
        "norgate_data",
        "US Stocks Platinum",
        "permanent_security_id",
        CapabilityStatus.PARTIAL,
        norgate,
        (
            "assetid is static over the lifetime of a security in supported "
            "environments, including Python."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "delisting_lifecycle",
        CapabilityStatus.PARTIAL,
        norgate_packages,
        (
            "Platinum includes access to delisted securities and historical data "
            "back to 1990; exact completeness is not claimed."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "ticker_history",
        CapabilityStatus.NO,
        norgate,
        (
            "Do you provide prior symbols used by a security? No, only the current "
            "symbol is provided."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "listing_lifecycle",
        CapabilityStatus.PARTIAL,
        norgate,
        (
            "For US securities, Platinum provides a Major Exchange Listed timeseries "
            "showing major-exchange versus OTC trading, but not exact exchange names."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "delisting_return",
        CapabilityStatus.NO,
        norgate,
        "Norgate does not provide delisting-return information.",
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "historical_membership",
        CapabilityStatus.PARTIAL,
        norgate,
        (
            "Historical index membership can be queried as a true/false answer for "
            "any day through supported environments, but no constituent lists or "
            "announcement dates are provided."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "corporate_actions",
        CapabilityStatus.NO,
        norgate,
        (
            "Corporate actions are not provided directly; actions are incorporated "
            "into adjusted price data."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "pit_corporate_action_availability",
        CapabilityStatus.UNKNOWN,
        norgate,
        "No official statement proves PIT action availability or action revisions.",
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "pit_total_return_vintages",
        CapabilityStatus.NO,
        norgate,
        "Adjusted series are provided, not historical PIT total-return vintages.",
        "HIGH_OFFICIAL",
    )
    add(
        "norgate_data",
        "US Stocks Platinum",
        "benchmark_same_pit",
        CapabilityStatus.UNKNOWN,
        norgate,
        "No official statement proves SPY/QQQ benchmark PIT compatibility.",
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    massive = "https://massive.com/legal/market-data-terms-of-service"
    massive_tickers = "https://massive.com/docs/rest/stocks/tickers/all-tickers"
    add(
        "massive",
        "Advanced + strategy license",
        "license_scope",
        CapabilityStatus.REQUIRES_LICENSE,
        massive,
        (
            "Market-data terms distinguish display use and require a confirmed "
            "non-display/strategy license."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "massive",
        "Advanced + strategy license",
        "delisted_securities",
        CapabilityStatus.PARTIAL,
        massive_tickers,
        (
            "All Tickers exposes active status and delisted_utc; active=false means "
            "the asset has been delisted. Delisting returns are not proven."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "massive",
        "Advanced + strategy license",
        "permanent_security_id",
        CapabilityStatus.PARTIAL,
        massive_tickers,
        (
            "All Tickers documents CIK, composite_figi, and share_class_figi, but "
            "the permanent identity contract requires package audit."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "massive",
        "Advanced + strategy license",
        "historical_membership",
        CapabilityStatus.UNKNOWN,
        massive_tickers,
        (
            "The date query on All Tickers is not proof of PIT historical "
            "membership for a project-defined broad universe."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    sharadar = "https://data.nasdaq.com/databases/SF1"
    add(
        "nasdaq_data_link_sharadar",
        "Sharadar Equities/ETFs",
        "delisted_securities",
        CapabilityStatus.PARTIAL,
        sharadar,
        (
            "Sharadar-style products include delisted ticker coverage; exact plan "
            "and permanent identity must be confirmed."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "nasdaq_data_link_sharadar",
        "Sharadar Equities/ETFs",
        "historical_membership",
        CapabilityStatus.UNKNOWN,
        sharadar,
        (
            "Official public documentation does not prove PIT index membership "
            "for the project universe."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    add(
        "tiingo",
        "Individual EOD",
        "permanent_security_id",
        CapabilityStatus.PARTIAL,
        "https://www.tiingo.com/documentation/appendix/symbology",
        (
            "Tiingo documents permaTicker-style identity; complete lifecycle and "
            "PIT contract are not proven."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "tiingo",
        "Individual EOD",
        "historical_membership",
        CapabilityStatus.NO,
        "https://www.tiingo.com/documentation/end-of-day",
        "Public EOD documentation does not provide PIT broad-universe membership.",
        "HIGH_OFFICIAL",
    )

    add(
        "eodhd",
        "EOD Historical Data All World",
        "delisted_securities",
        CapabilityStatus.PARTIAL,
        "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
        (
            "Delisted company data is advertised; terminal returns, permanent "
            "identity, and PIT membership require package audit."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "eodhd",
        "EOD Historical Data All World",
        "ticker_history",
        CapabilityStatus.PARTIAL,
        "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
        (
            "Symbol Change History maps old symbols to new symbols over a date "
            "range; only US exchanges are currently supported."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "eodhd",
        "EOD Historical Data All World",
        "delisting_return",
        CapabilityStatus.UNKNOWN,
        "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
        (
            "Delisted EOD data is advertised, but no official terminal-return or "
            "consideration convention is documented."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )
    add(
        "eodhd",
        "EOD Historical Data All World",
        "historical_membership",
        CapabilityStatus.NO,
        "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
        "Official public documentation does not prove PIT broad-universe membership.",
        "HIGH_OFFICIAL",
    )
    add(
        "eodhd",
        "EOD Historical Data All World",
        "pit_corporate_action_availability",
        CapabilityStatus.UNKNOWN,
        "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
        (
            "Dividends and splits are advertised, but official documentation does "
            "not prove PIT announcement availability or revisions."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    add(
        "alpha_vantage",
        "Free key or premium",
        "delisted_securities",
        CapabilityStatus.PARTIAL,
        "https://www.alphavantage.co/documentation/",
        (
            "Listing status since 2010 is documented; complete delisting returns "
            "and PIT lifecycle are not proven."
        ),
        "MEDIUM_OFFICIAL",
    )
    add(
        "alpha_vantage",
        "Free key or premium",
        "historical_membership",
        CapabilityStatus.PARTIAL,
        "https://www.alphavantage.co/documentation/",
        (
            "Listing status time series is advertised since 2010, but project "
            "membership reconstruction must still be audited."
        ),
        "MEDIUM_OFFICIAL",
    )

    add(
        "twelve_data",
        "Basic or paid",
        "delisted_securities",
        CapabilityStatus.UNKNOWN,
        "https://twelvedata.com/pricing",
        "Official public pricing does not prove complete delisted coverage or delisting returns.",
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )
    add(
        "nasdaq_trader_symbol_directory",
        "Free current directory",
        "historical_universe",
        CapabilityStatus.NO,
        "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
        (
            "The directory is a current listing file and cannot be used to "
            "reconstruct historical membership."
        ),
        "HIGH_OFFICIAL",
    )

    add(
        "alpaca",
        "Market Data API",
        "corporate_actions",
        CapabilityStatus.PARTIAL,
        "https://docs.alpaca.markets/us/reference/CorporateActions-1",
        (
            "The endpoint supports splits, dividends, mergers, redemptions, name "
            "changes, worthless removals, and other action types."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "alpaca",
        "Market Data API",
        "pit_corporate_action_availability",
        CapabilityStatus.NO,
        "https://docs.alpaca.markets/us/reference/CorporateActions-1",
        (
            "Alpaca states there are no guarantees on the creation time of "
            "corporate actions and actions may not be available immediately after "
            "announcement."
        ),
        "HIGH_OFFICIAL",
    )
    add(
        "alpaca",
        "Market Data API",
        "delisted_securities",
        CapabilityStatus.UNKNOWN,
        "https://docs.alpaca.markets/us/reference/CorporateActions-1",
        (
            "Corporate action coverage is documented, but delisted lifecycle and "
            "terminal return coverage are not proven by this page."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )
    add(
        "alpaca",
        "Market Data API",
        "historical_membership",
        CapabilityStatus.UNKNOWN,
        "https://docs.alpaca.markets/us/reference/CorporateActions-1",
        (
            "No official statement proves PIT historical membership for a "
            "project-defined broad universe."
        ),
        "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION",
    )

    return tuple(claims)
