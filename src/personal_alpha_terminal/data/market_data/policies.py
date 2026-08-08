from dataclasses import dataclass
from datetime import timedelta

from personal_alpha_terminal.data.market_data.schemas import Market


@dataclass(frozen=True, slots=True)
class MarketDataPolicy:
    market: Market
    primary_source: str
    timezone: str
    allowed_currencies: frozenset[str]
    daily_bar_publication_delay: timedelta
    raw_price_policy: str
    adjusted_price_policy: str
    symbol_policy: str
    trading_calendar_policy: str
    corporate_action_risks: tuple[str, ...]


MARKET_DATA_POLICIES: dict[Market, MarketDataPolicy] = {
    "A": MarketDataPolicy(
        market="A",
        primary_source="akshare",
        timezone="Asia/Shanghai",
        allowed_currencies=frozenset({"CNY"}),
        daily_bar_publication_delay=timedelta(minutes=30),
        raw_price_policy="unadjusted exchange OHLCV",
        adjusted_price_policy="AKShare qfq close; never mix raw/qfq dates",
        symbol_policy="six digits with explicit SH/SZ/BJ exchange in stock master",
        trading_calendar_policy="verified mainland exchange session calendar required",
        corporate_action_risks=(
            "qfq history can be revised after dividends and splits",
            "ST, IPO and limit-up/limit-down rules require separate execution controls",
        ),
    ),
    "HK": MarketDataPolicy(
        market="HK",
        primary_source="yahoo_finance",
        timezone="Asia/Hong_Kong",
        allowed_currencies=frozenset({"HKD", "CNY", "USD"}),
        daily_bar_publication_delay=timedelta(minutes=30),
        raw_price_policy="Yahoo unadjusted OHLCV",
        adjusted_price_policy="Yahoo adjusted close with explicit raw close retained",
        symbol_policy="numeric HK code normalized to four digits plus .HK",
        trading_calendar_policy=(
            "verified HKEX session calendar required; timestamp uses the "
            "latest 16:10 closing-auction endpoint"
        ),
        corporate_action_risks=(
            "board-lot size and auction liquidity are not represented by daily bars",
            "provider corporate-action history can be revised",
        ),
    ),
    "US": MarketDataPolicy(
        market="US",
        primary_source="yahoo_finance",
        timezone="America/New_York",
        allowed_currencies=frozenset({"USD"}),
        daily_bar_publication_delay=timedelta(minutes=30),
        raw_price_policy="Yahoo unadjusted OHLCV",
        adjusted_price_policy="Yahoo adjusted close with explicit raw close retained",
        symbol_policy="exchange ticker preserved; stock master owns ticker changes",
        trading_calendar_policy="verified US primary-listing session calendar required",
        corporate_action_risks=(
            "splits and cash dividends can revise adjusted history",
            "ADR ratio changes, foreign holidays and depositary fees need separate review",
        ),
    ),
}


def policy_for_market(market: str) -> MarketDataPolicy:
    if market not in MARKET_DATA_POLICIES:
        raise ValueError(f"unsupported market-data policy: {market}")
    return MARKET_DATA_POLICIES[market]
