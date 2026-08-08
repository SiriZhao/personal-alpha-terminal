from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from personal_alpha_terminal.quant_engine.risk.portfolio_risk import (
    PortfolioRiskMetrics,
    calculate_portfolio_risk,
)
from personal_alpha_terminal.terminal.cache import CacheLineage, DailyPriceCache
from personal_alpha_terminal.terminal.config import TerminalConfig
from personal_alpha_terminal.terminal.market_data_service import (
    MarketDataService,
    ProviderHealth,
)
from personal_alpha_terminal.terminal.market_sessions import (
    MarketSessionCalendar,
    MarketSessionState,
)
from personal_alpha_terminal.terminal.providers import DataProvider, build_provider
from personal_alpha_terminal.terminal.quality import (
    DataQualityReport,
    DataQualityValidator,
    DataSafetyStatus,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MarketOverview:
    symbol: str
    close: float | None
    daily_change: float | None
    latest_date: date | None


@dataclass(frozen=True, slots=True)
class QuantSignal:
    symbol: str
    score: float
    signal: str
    reason: str


@dataclass(frozen=True, slots=True)
class DailyAction:
    symbol: str
    action: str
    confidence: float | None
    current_allocation: float | None
    target_allocation: float | None
    suggested_change: float | None
    signal_summary: str
    probability: float | None
    risk: str
    data_quality: float
    execution_feasibility: str
    recommended_session: str
    estimated_cost_rate: float | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DailyAnalysis:
    generated_at: datetime
    data_quality: DataQualityReport
    frames: dict[str, pd.DataFrame]
    lineages: dict[str, CacheLineage]
    provider_errors: dict[str, str]
    provider_health: tuple[ProviderHealth, ...]
    market_session: MarketSessionState
    overview: tuple[MarketOverview, ...]
    regime: str
    regime_reason: str
    portfolio_risk: PortfolioRiskMetrics | None
    signals: tuple[QuantSignal, ...]
    actions: tuple[DailyAction, ...]
    model_status: str
    warnings: tuple[str, ...]


class DailyResearchPipeline:
    """Canonical real-data daily workflow; Quant code never calls a provider."""

    def __init__(
        self,
        config: TerminalConfig,
        *,
        primary: DataProvider | None = None,
        fallback: DataProvider | None = None,
        providers: tuple[DataProvider, ...] | None = None,
    ) -> None:
        self.config = config
        self.cache = DailyPriceCache(config.cache_dir)
        self.calendar = MarketSessionCalendar(
            nasdaq_23h_enabled=config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
        )
        if providers is None:
            if primary is not None or fallback is not None:
                providers = tuple(item for item in (primary, fallback) if item is not None)
            else:
                providers = tuple(
                    build_provider(
                        name,
                        timeout_seconds=config.timeout_seconds,
                        max_retries=config.max_retries,
                        retry_backoff_seconds=config.retry_backoff_seconds,
                        cache_dir=config.cache_dir / "providers" / name,
                    )
                    for name in config.provider_priority
                )
        self.market_data = MarketDataService(
            providers=providers,
            cache=self.cache,
            calendar=self.calendar,
        )
        self.validator = DataQualityValidator(
            safe_threshold=config.data_safe_threshold,
            watch_threshold=config.data_watch_threshold,
            maximum_provider_difference=config.maximum_provider_difference,
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        all_symbols = [
            *self.config.symbols,
            self.config.benchmark,
            self.config.nasdaq_benchmark,
            self.config.vix_symbol,
        ]
        return tuple(dict.fromkeys(symbol.upper() for symbol in all_symbols))

    def run(self, *, as_of: date | None = None, refresh: bool = True) -> DailyAnalysis:
        today = as_of or date.today()
        sync = self.market_data.sync(
            self.symbols,
            start=date.fromisoformat(self.config.history_start),
            end=today,
            refresh=refresh,
        )
        quality = self.validator.validate(
            sync.data,
            required_symbols=self.config.required_symbols,
            as_of=today,
            provider_disagreements=sync.provider_disagreements,
        )
        frames = {symbol: value[0] for symbol, value in sync.data.items()}
        score_by_symbol = {item.symbol: item.quality_score for item in quality.symbols}
        for symbol, frame in frames.items():
            frame["quality_score"] = score_by_symbol.get(symbol)
        lineages = {symbol: value[1] for symbol, value in sync.data.items()}
        return self._analyse(
            quality,
            frames,
            lineages,
            sync.errors,
            sync.provider_health,
        )

    def _analyse(
        self,
        quality: DataQualityReport,
        frames: dict[str, pd.DataFrame],
        lineages: dict[str, CacheLineage],
        errors: dict[str, str],
        provider_health: tuple[ProviderHealth, ...],
    ) -> DailyAnalysis:
        generated_at = datetime.now(UTC)
        session = self.calendar.classify(generated_at)
        overview = tuple(
            self._overview(symbol, frames.get(symbol))
            for symbol in (
                self.config.benchmark,
                self.config.nasdaq_benchmark,
                self.config.vix_symbol,
            )
        )
        regime, regime_reason = self._market_regime(frames)
        warnings = [
            "本终端仅提供量化研究和人工决策支持，不连接券商或自动下单。"
        ]
        if quality.safety_status is DataSafetyStatus.SAFE:
            warnings.append(
                "日线行情通过本地质量分门禁；PIT 股票池、公司行动与模型生产批准仍独立约束交易建议。"
            )
        elif quality.safety_status is DataSafetyStatus.DEGRADED:
            warnings.append("数据处于降级状态，仅允许 HOLD/WATCH，不允许产生可执行调仓。")
        else:
            warnings.append("关键数据未通过安全门禁，不生成可执行 BUY/SELL/ADD/REDUCE。")
        for symbol, message in sorted(errors.items()):
            logger.warning("Market data issue symbol=%s detail=%s", symbol, message)
            if "no cache exists" in message:
                public_message = "全部实时来源失败且无本地缓存；该标的已阻止。"
            elif "using cached data" in message:
                public_message = "实时来源失败；已使用缓存并继续接受时效门禁。"
            else:
                public_message = "行情不可用；技术详情已写入 data.log。"
            warnings.append(f"{symbol}: {public_message}")

        # Price-only indicators are not a production Alpha path. Production
        # actions must come from the validated Quant/Portfolio/Risk chain.
        actions = (
            DailyAction(
                symbol="--",
                action="NO ACTION",
                confidence=None,
                current_allocation=None,
                target_allocation=None,
                suggested_change=None,
                signal_summary="没有通过生产批准与数据安全门禁的量化候选",
                probability=None,
                risk="BLOCKED" if quality.status == "BLOCKED" else "RESEARCH_ONLY",
                data_quality=quality.minimum_quality_score,
                execution_feasibility="BLOCKED",
                recommended_session="REGULAR",
                estimated_cost_rate=None,
                reason_codes=(
                    "NO_PRODUCTION_APPROVED_ALPHA",
                    f"DATA_{quality.safety_status.value}",
                ),
            ),
        )
        warnings.append(
            "未发现 PRODUCTION_APPROVED Alpha；技术指标或 AI 解释不会直接生成仓位、BUY 或 SELL。"
        )
        return DailyAnalysis(
            generated_at=generated_at,
            data_quality=quality,
            frames=frames,
            lineages=lineages,
            provider_errors=errors,
            provider_health=provider_health,
            market_session=session,
            overview=overview,
            regime=regime,
            regime_reason=regime_reason,
            portfolio_risk=self._portfolio_risk(frames),
            signals=(),
            actions=actions,
            model_status="INSUFFICIENT_DATA",
            warnings=tuple(warnings),
        )

    @staticmethod
    def _overview(symbol: str, frame: pd.DataFrame | None) -> MarketOverview:
        if frame is None or len(frame) < 2:
            return MarketOverview(symbol, None, None, None)
        close = float(frame["close"].iloc[-1])
        prior = float(frame["close"].iloc[-2])
        latest_column = "trade_date" if "trade_date" in frame else "date"
        latest = pd.Timestamp(frame[latest_column].iloc[-1]).date()
        return MarketOverview(symbol, close, close / prior - 1 if prior else None, latest)

    def _market_regime(self, frames: dict[str, pd.DataFrame]) -> tuple[str, str]:
        spy = frames.get(self.config.benchmark)
        vix = frames.get(self.config.vix_symbol)
        if spy is None or len(spy) < 200:
            return "Waiting for Data", "SPY 历史不足 200 个交易日，市场状态评分不可用"
        close = spy["close"].astype(float)
        trend = close.iloc[-1] >= close.rolling(200).mean().iloc[-1]
        vix_level = float(vix["close"].iloc[-1]) if vix is not None and not vix.empty else None
        if not trend:
            return "Risk Off", "SPY 低于 200 日均线；这是未校准状态评分，不是概率"
        if vix_level is not None and vix_level >= 25:
            return "Neutral", "长期趋势向上但 VIX 较高；这是未校准状态评分"
        return "Risk On", "SPY 位于 200 日均线上方且 VIX 未触发高波动阈值；不是价格预测"

    def _portfolio_risk(self, frames: dict[str, pd.DataFrame]) -> PortfolioRiskMetrics | None:
        weights = {
            symbol: weight
            for symbol, weight in self.config.holdings.items()
            if symbol in frames and weight > 0
        }
        if not weights or self.config.benchmark not in frames:
            return None
        prices = {
            symbol: frames[symbol].set_index("date")["close"].astype(float)
            for symbol in weights
        }
        returns = pd.DataFrame(prices).pct_change().dropna(how="all")
        benchmark = (
            frames[self.config.benchmark].set_index("date")["close"].astype(float).pct_change()
        )
        try:
            return calculate_portfolio_risk(returns, weights, benchmark_returns=benchmark)
        except ValueError:
            return None
