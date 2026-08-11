from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResearchAsset:
    ticker: str
    name: str
    exchange: str
    asset_type: str
    role: str
    required: bool = True

    @property
    def canonical_code(self) -> str:
        return f"US:{self.exchange}:{self.ticker}"


# Compatibility bootstrap/reference assets for incremental daily data only.
# BroadUSUniverseService, not this tuple, defines the production alpha cross-section.
MINIMUM_US_RESEARCH_UNIVERSE = (
    ResearchAsset("SPY", "SPDR S&P 500 ETF", "ARCX", "etf", "市场基准"),
    ResearchAsset("QQQ", "Invesco QQQ ETF", "XNAS", "etf", "大盘成长"),
    ResearchAsset("IWD", "iShares Russell 1000 Value ETF", "ARCX", "etf", "大盘价值"),
    ResearchAsset("IWM", "iShares Russell 2000 ETF", "ARCX", "etf", "小盘"),
    ResearchAsset("VTI", "Vanguard Total Stock Market ETF", "ARCX", "etf", "全市场"),
    ResearchAsset("TLT", "iShares 20+ Year Treasury Bond ETF", "XNAS", "etf", "长债"),
    ResearchAsset("GLD", "SPDR Gold Shares", "ARCX", "etf", "黄金"),
    ResearchAsset("SGOV", "iShares 0-3 Month Treasury Bond ETF", "ARCX", "etf", "现金代理"),
    ResearchAsset("^VIX", "CBOE Volatility Index", "XCBO", "index", "风险状态"),
    ResearchAsset("AAPL", "Apple", "XNAS", "stock", "截面因子"),
    ResearchAsset("MSFT", "Microsoft", "XNAS", "stock", "截面因子"),
    ResearchAsset("NVDA", "NVIDIA", "XNAS", "stock", "截面因子"),
    ResearchAsset("AMZN", "Amazon", "XNAS", "stock", "截面因子"),
    ResearchAsset("GOOGL", "Alphabet Class A", "XNAS", "stock", "截面因子"),
    ResearchAsset("META", "Meta Platforms", "XNAS", "stock", "截面因子"),
    ResearchAsset("JPM", "JPMorgan Chase", "XNYS", "stock", "截面因子", required=False),
    ResearchAsset("JNJ", "Johnson & Johnson", "XNYS", "stock", "截面因子", required=False),
    ResearchAsset("XOM", "Exxon Mobil", "XNYS", "stock", "截面因子", required=False),
)
