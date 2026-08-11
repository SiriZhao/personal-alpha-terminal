from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from math import sqrt
from pathlib import Path
from typing import Any, cast

import exchange_calendars as xcals  # type: ignore[import-untyped]

from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import PortfolioConstraints
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
    USAdaptiveAlphaCoreV1Config,
)

MONEY = Decimal("0.000001")


class PaperDecisionChoice(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    SKIP = "SKIP"


class PaperSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("paper accounting values must be finite")
    return result


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY))


def _next_xnys_session(day: date) -> date:
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(day.isoformat(), direction="next")
    if session.date() == day:
        session = calendar.next_session(session)
    return cast(date, session.date())


def _xnys_session_open(day: date) -> datetime:
    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(day.isoformat(), direction="none")
    return cast(datetime, calendar.session_open(session).to_pydatetime()).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PaperSignalInput:
    ticker: str
    security_id: str
    composite: float
    expected_alpha: float
    rank: int
    factor_values: dict[str, float]
    reason: str = "DETERMINISTIC_DIAGNOSTIC_CANDIDATE"


@dataclass(frozen=True, slots=True)
class PaperExecutionBar:
    ticker: str
    session_date: date
    open_price: Decimal
    available_at: datetime
    average_daily_dollar_volume: Decimal
    source: str = "TEST_FIXTURE"
    data_hash: str = "TEST_FIXTURE"


class PaperTradingService:
    """Append-only paper ledger that never reads or writes the real portfolio DB."""

    def __init__(self, root: Path = Path("var/paper-trading")) -> None:
        self.root = root
        self.constraints = PortfolioConstraints()
        self.cost_config = TransactionCostConfig()
        self.cost_model = TransactionCostModel(self.cost_config)

    def initialize_portfolio(
        self,
        *,
        portfolio_id: str,
        cash: Decimal,
        currency: str = "USD",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = self._portfolio_id(portfolio_id)
        amount = _decimal(cash)
        if amount <= 0:
            raise ValueError("paper portfolio cash must be positive")
        if currency.upper() != "USD":
            raise ValueError("paper forward validation currently supports USD only")
        timestamp = created_at or _utc_now()
        if timestamp.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        payload: dict[str, Any] = {
            "schema_version": "paper-portfolio-v1",
            "portfolio_id": normalized,
            "mode": "PAPER",
            "currency": "USD",
            "initial_cash": _money(amount),
            "starting_nav": _money(amount),
            "positions": {},
            "auto_execution": False,
            "created_at": timestamp.astimezone(UTC).isoformat(),
            "paper_only": True,
            "real_ledger_database": "NEVER_ACCESSED",
        }
        folder = self._folder(normalized)
        folder.mkdir(parents=True, exist_ok=True)
        stored = self._write_immutable(folder / "portfolio.json", payload)
        self._event_dir(normalized, "fills").mkdir(parents=True, exist_ok=True)
        self._event_dir(normalized, "decisions").mkdir(parents=True, exist_ok=True)
        self._event_dir(normalized, "actions").mkdir(parents=True, exist_ok=True)
        self._event_dir(normalized, "signals").mkdir(parents=True, exist_ok=True)
        self._event_dir(normalized, "snapshots").mkdir(parents=True, exist_ok=True)
        return stored

    def freeze_experiment(
        self,
        *,
        portfolio_id: str,
        experiment_id: str,
        started_at: datetime | None = None,
    ) -> dict[str, Any]:
        self.portfolio(portfolio_id)
        strategy = USAdaptiveAlphaCoreV1()
        config = USAdaptiveAlphaCoreV1Config()
        timestamp = started_at or _utc_now()
        payload: dict[str, Any] = {
            "schema_version": "paper-experiment-v1",
            "paper_experiment_id": experiment_id.strip(),
            "portfolio_id": self._portfolio_id(portfolio_id),
            "mode": "PAPER_SHADOW_FORWARD_TEST",
            "strategy_id": strategy.model_id,
            "strategy_version": strategy.version,
            "parameter_hash": config.parameter_fingerprint,
            "strategy_parameters": asdict(config),
            "factor_definitions": ["momentum_12_1", "trend_slope", "low_volatility"],
            "factor_weights": {
                "momentum": config.momentum_coefficient,
                "trend": config.trend_coefficient,
                "low_volatility": config.low_volatility_coefficient,
                "quality": config.quality_coefficient,
            },
            "rebalance_convention": "decision_after_session_close_execute_next_XNYS_open",
            "signal_horizon_sessions": config.horizon_sessions,
            "portfolio_constraints": asdict(self.constraints),
            "cost_model": asdict(self.cost_config),
            "universe_rule": "daily_PIT_universe; benchmark_and_ETF_not_equity_ranked_when_typed",
            "started_at": timestamp.astimezone(UTC).isoformat(),
            "production_approved": False,
            "paper_only": True,
            "warning": "PAPER_ONLY; NOT_PRODUCTION_APPROVED; DO_NOT_USE_FOR_REAL_TRADING",
        }
        if not payload["paper_experiment_id"]:
            raise ValueError("paper experiment id is required")
        return self._write_immutable(
            self._event_dir(portfolio_id, "experiments") / f"{payload['paper_experiment_id']}.json",
            payload,
        )

    def portfolio(self, portfolio_id: str) -> dict[str, Any]:
        return self._read_verified(self._folder(portfolio_id) / "portfolio.json")

    def experiment(self, portfolio_id: str, experiment_id: str | None = None) -> dict[str, Any]:
        directory = self._event_dir(portfolio_id, "experiments")
        if experiment_id is not None:
            return self._read_verified(directory / f"{experiment_id}.json")
        experiments = sorted(
            (self._read_verified(path) for path in directory.glob("*.json")),
            key=lambda item: str(item["started_at"]),
        )
        if not experiments:
            raise ValueError(f"paper experiment not found for {portfolio_id}")
        return experiments[-1]

    def list_portfolios(self) -> tuple[dict[str, Any], ...]:
        if not self.root.exists():
            return ()
        return tuple(
            self._read_verified(path) for path in sorted(self.root.glob("*/portfolio.json"))
        )

    def record_signals(
        self,
        *,
        portfolio_id: str,
        experiment_id: str,
        as_of: datetime,
        cutoff: datetime,
        trade_date: date,
        data_hash: str,
        universe_version: str,
        signals: tuple[PaperSignalInput, ...],
        recorded_at: datetime | None = None,
    ) -> tuple[dict[str, Any], ...]:
        experiment = self._matching_experiment(portfolio_id, experiment_id)
        if as_of.tzinfo is None or cutoff.tzinfo is None:
            raise ValueError("paper signal timestamps must be timezone-aware")
        timestamp = recorded_at or _utc_now()
        if cutoff > as_of or as_of > timestamp:
            raise ValueError("future data cannot enter a paper decision")
        if trade_date != _next_xnys_session(as_of.date()):
            raise ValueError("paper trade_date must be the next valid XNYS session")
        results: list[dict[str, Any]] = []
        for signal in sorted(signals, key=lambda item: (item.rank, item.ticker)):
            identity = {
                "experiment": experiment_id,
                "as_of": as_of.isoformat(),
                "ticker": signal.ticker.upper(),
                "parameter_hash": experiment["parameter_hash"],
                "data_hash": data_hash,
            }
            payload: dict[str, Any] = {
                "schema_version": "paper-signal-v1",
                "signal_id": f"paper-signal-{_hash(identity)[:24]}",
                "paper_experiment_id": experiment_id,
                "portfolio_id": self._portfolio_id(portfolio_id),
                "as_of": as_of.astimezone(UTC).isoformat(),
                "cutoff": cutoff.astimezone(UTC).isoformat(),
                "trade_date": trade_date.isoformat(),
                "ticker": signal.ticker.upper(),
                "security_id": signal.security_id,
                "factor_values": signal.factor_values,
                "composite": signal.composite,
                "expected_alpha": signal.expected_alpha,
                "rank": signal.rank,
                "strategy_version": f"{experiment['strategy_id']}:{experiment['strategy_version']}",
                "parameter_hash": experiment["parameter_hash"],
                "data_hash": data_hash,
                "universe_version": universe_version,
                "reason": signal.reason,
                "signal_timestamp": timestamp.astimezone(UTC).isoformat(),
                "production_approved": False,
                "paper_only": True,
                "classification": "PAPER_SIGNAL",
                "warning": "PAPER_ONLY; NOT_PRODUCTION_APPROVED; DO_NOT_USE_FOR_REAL_TRADING",
            }
            results.append(
                self._write_immutable(
                    self._event_dir(portfolio_id, "signals") / f"{payload['signal_id']}.json",
                    payload,
                )
            )
        return tuple(results)

    def propose_actions(
        self,
        *,
        portfolio_id: str,
        experiment_id: str,
        signal_ids: tuple[str, ...],
        prices: dict[str, Decimal],
        sectors: dict[str, str],
        average_daily_dollar_volume: dict[str, Decimal],
        risk_validated: bool,
        decision_time: datetime,
    ) -> tuple[dict[str, Any], ...]:
        experiment = self._matching_experiment(portfolio_id, experiment_id)
        if not risk_validated:
            self._write_observation(
                portfolio_id,
                experiment_id,
                decision_time,
                "BLOCKED",
                ("PAPER_RISK_INPUT_NOT_VALIDATED",),
            )
            return ()
        signals = [self._read_event(portfolio_id, "signals", item) for item in signal_ids]
        if any(item["parameter_hash"] != experiment["parameter_hash"] for item in signals):
            raise ValueError("paper signal does not match frozen strategy parameters")
        if any(datetime.fromisoformat(str(item["cutoff"])) > decision_time for item in signals):
            raise ValueError("future paper signal supplied to decision")
        state = self.current_state(portfolio_id, prices)
        if state["nav"] is None:
            raise ValueError("all paper holdings require decision-time prices")
        nav = _decimal(state["nav"])
        holdings = cast(dict[str, str], state["positions"])
        positive = sorted(
            (item for item in signals if float(item["expected_alpha"]) > 0),
            key=lambda item: (int(item["rank"]), str(item["ticker"])),
        )
        maximum_names = max(
            1,
            int(self.constraints.maximum_gross_exposure / self.constraints.maximum_position_weight),
        )
        selected = positive[:maximum_names]
        target_weight = (
            min(
                self.constraints.maximum_position_weight,
                self.constraints.maximum_gross_exposure / len(selected),
            )
            if selected
            else 0.0
        )
        sector_weights: dict[str, float] = {}
        actions: list[dict[str, Any]] = []
        used_turnover = Decimal("0")
        for item in selected:
            ticker = str(item["ticker"])
            if ticker not in prices or ticker not in average_daily_dollar_volume:
                continue
            sector = sectors.get(ticker, "UNKNOWN")
            next_sector = sector_weights.get(sector, 0.0) + target_weight
            if next_sector > self.constraints.maximum_sector_weight + 1e-12:
                continue
            price = _decimal(prices[ticker])
            current_value = _decimal(holdings.get(ticker, "0")) * price
            desired_value = nav * _decimal(target_weight)
            delta = desired_value - current_value
            if delta <= 0 or delta < _decimal(self.constraints.minimum_trade_value):
                continue
            allowed_turnover = nav * _decimal(self.constraints.maximum_turnover) - used_turnover
            trade_value = min(delta, allowed_turnover)
            quantity = (trade_value / price).to_integral_value(rounding=ROUND_FLOOR)
            trade_value = quantity * price
            if quantity <= 0 or trade_value < _decimal(self.constraints.minimum_trade_value):
                continue
            self.cost_model.estimate(
                trade_value=float(trade_value),
                average_daily_dollar_volume=float(average_daily_dollar_volume[ticker]),
            )
            action_identity = {
                "signal": item["signal_id"],
                "nav": str(nav),
                "price": str(price),
            }
            action_id = f"paper-action-{_hash(action_identity)[:24]}"
            payload: dict[str, Any] = {
                "schema_version": "paper-action-v1",
                "action_id": action_id,
                "paper_experiment_id": experiment_id,
                "portfolio_id": self._portfolio_id(portfolio_id),
                "signal_id": item["signal_id"],
                "decision_time": decision_time.astimezone(UTC).isoformat(),
                "eligible_execution_date": item["trade_date"],
                "ticker": ticker,
                "security_id": item["security_id"],
                "side": PaperSide.BUY.value,
                "quantity": str(quantity),
                "reference_value": _money(trade_value),
                "target_weight": target_weight,
                "model_recommendation": "BUY",
                "user_paper_decision": "PENDING",
                "simulated_fill": "NOT_FILLED",
                "production_approved": False,
                "paper_only": True,
                "warning": "PAPER_ONLY; NOT_PRODUCTION_APPROVED; DO_NOT_USE_FOR_REAL_TRADING",
            }
            actions.append(
                self._write_immutable(
                    self._event_dir(portfolio_id, "actions") / f"{action_id}.json", payload
                )
            )
            sector_weights[sector] = next_sector
            used_turnover += trade_value
        selected_tickers = {str(item["ticker"]) for item in selected}
        signals_by_ticker = {str(item["ticker"]): item for item in signals}
        for ticker, held_text in sorted(holdings.items()):
            if (
                ticker in selected_tickers
                or ticker not in signals_by_ticker
                or ticker not in prices
            ):
                continue
            item = signals_by_ticker[ticker]
            if float(item["expected_alpha"]) > 0:
                continue
            price = _decimal(prices[ticker])
            held = _decimal(held_text)
            allowed_turnover = nav * _decimal(self.constraints.maximum_turnover) - used_turnover
            quantity = min(
                held,
                (allowed_turnover / price).to_integral_value(rounding=ROUND_FLOOR),
            )
            trade_value = quantity * price
            if quantity <= 0 or trade_value < _decimal(self.constraints.minimum_trade_value):
                continue
            self.cost_model.estimate(
                trade_value=float(trade_value),
                average_daily_dollar_volume=float(average_daily_dollar_volume[ticker]),
            )
            action_identity = {
                "signal": item["signal_id"],
                "nav": str(nav),
                "price": str(price),
                "side": PaperSide.SELL.value,
            }
            action_id = f"paper-action-{_hash(action_identity)[:24]}"
            payload = {
                "schema_version": "paper-action-v1",
                "action_id": action_id,
                "paper_experiment_id": experiment_id,
                "portfolio_id": self._portfolio_id(portfolio_id),
                "signal_id": item["signal_id"],
                "decision_time": decision_time.astimezone(UTC).isoformat(),
                "eligible_execution_date": item["trade_date"],
                "ticker": ticker,
                "security_id": item["security_id"],
                "side": PaperSide.SELL.value,
                "quantity": str(quantity),
                "reference_value": _money(trade_value),
                "target_weight": 0.0,
                "model_recommendation": "SELL",
                "user_paper_decision": "PENDING",
                "simulated_fill": "NOT_FILLED",
                "production_approved": False,
                "paper_only": True,
                "warning": "PAPER_ONLY; NOT_PRODUCTION_APPROVED; DO_NOT_USE_FOR_REAL_TRADING",
            }
            actions.append(
                self._write_immutable(
                    self._event_dir(portfolio_id, "actions") / f"{action_id}.json",
                    payload,
                )
            )
            used_turnover += trade_value
        return tuple(actions)

    def confirm_action(
        self,
        *,
        portfolio_id: str,
        action_id: str,
        choice: PaperDecisionChoice,
        decided_at: datetime | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        action = self._read_event(portfolio_id, "actions", action_id)
        timestamp = decided_at or _utc_now()
        identity = {"action_id": action_id, "choice": choice.value}
        decision_id = f"paper-decision-{_hash(identity)[:24]}"
        payload: dict[str, Any] = {
            "schema_version": "paper-decision-v1",
            "decision_id": decision_id,
            "portfolio_id": self._portfolio_id(portfolio_id),
            "paper_experiment_id": action["paper_experiment_id"],
            "action_id": action_id,
            "model_recommendation": action["model_recommendation"],
            "user_paper_decision": choice.value,
            "decided_at": timestamp.astimezone(UTC).isoformat(),
            "reason": reason,
            "paper_only": True,
        }
        existing = tuple(self._event_dir(portfolio_id, "decisions").glob("*.json"))
        for path in existing:
            item = self._read_verified(path)
            if item["decision_id"] == decision_id:
                return item
            if item["action_id"] == action_id and item["decision_id"] != decision_id:
                raise ValueError("paper action already has a different immutable decision")
        return self._write_immutable(
            self._event_dir(portfolio_id, "decisions") / f"{decision_id}.json", payload
        )

    def simulate_fill(
        self,
        *,
        portfolio_id: str,
        action_id: str,
        bar: PaperExecutionBar,
        fill_time: datetime,
    ) -> dict[str, Any]:
        action = self._read_event(portfolio_id, "actions", action_id)
        decision = self._decision_for_action(portfolio_id, action_id)
        if decision["user_paper_decision"] != PaperDecisionChoice.ACCEPT.value:
            raise ValueError("only an explicitly accepted paper action may fill")
        eligible = date.fromisoformat(str(action["eligible_execution_date"]))
        decision_time = datetime.fromisoformat(str(action["decision_time"]))
        if bar.ticker.upper() != action["ticker"] or bar.session_date != eligible:
            raise ValueError("fill must use the exact next-session open for the action")
        if fill_time.tzinfo is None or bar.available_at.tzinfo is None:
            raise ValueError("paper fill timestamps must be timezone-aware")
        eligible_open = _xnys_session_open(eligible)
        if fill_time <= decision_time or bar.available_at > fill_time:
            raise ValueError("pre-decision or unavailable execution prices cannot fill")
        if bar.available_at < eligible_open or fill_time < eligible_open:
            raise ValueError("next-session open cannot be used before it is available")
        if not bar.source.strip() or not bar.data_hash.strip():
            raise ValueError("paper execution price requires source and content hash")
        if bar.open_price <= 0:
            raise ValueError("a known positive next-session open is required")
        fill_id = f"paper-fill-{_hash({'action': action_id, 'session': eligible.isoformat()})[:24]}"
        path = self._event_dir(portfolio_id, "fills") / f"{fill_id}.json"
        if path.exists():
            return self._read_verified(path)
        quantity = _decimal(action["quantity"])
        reference_value = quantity * bar.open_price
        estimate = self.cost_model.estimate(
            trade_value=float(reference_value),
            average_daily_dollar_volume=float(bar.average_daily_dollar_volume),
        )
        price_cost = _decimal(estimate.spread + estimate.slippage + estimate.market_impact)
        side = PaperSide(str(action["side"]))
        price_adjustment = price_cost / quantity if quantity else Decimal("0")
        fill_price = (
            bar.open_price + price_adjustment
            if side is PaperSide.BUY
            else bar.open_price - price_adjustment
        )
        state = self.current_state(portfolio_id, {bar.ticker.upper(): bar.open_price})
        cash_before = _decimal(state["cash"])
        positions = cast(dict[str, str], state["positions"])
        held_before = _decimal(positions.get(bar.ticker.upper(), "0"))
        fees = _decimal(estimate.commission + estimate.regulatory_fee)
        if side is PaperSide.BUY:
            cash_after = cash_before - quantity * fill_price - fees
            held_after = held_before + quantity
            if cash_after < 0:
                raise ValueError("insufficient paper cash for accepted fill and costs")
        else:
            if quantity > held_before:
                raise ValueError("paper sell cannot exceed current holdings")
            cash_after = cash_before + quantity * fill_price - fees
            held_after = held_before - quantity
        payload: dict[str, Any] = {
            "schema_version": "paper-fill-v1",
            "fill_id": fill_id,
            "order_id": action_id,
            "paper_experiment_id": action["paper_experiment_id"],
            "portfolio_id": self._portfolio_id(portfolio_id),
            "decision_time": action["decision_time"],
            "eligible_execution_time": eligible_open.isoformat(),
            "fill_time": fill_time.astimezone(UTC).isoformat(),
            "ticker": action["ticker"],
            "side": side.value,
            "quantity": str(quantity),
            "execution_convention": "NEXT_VALID_XNYS_SESSION_RAW_OPEN_PLUS_COSTS",
            "execution_price_source": bar.source,
            "execution_data_hash": bar.data_hash,
            "reference_price": _money(bar.open_price),
            "fill_price": _money(fill_price),
            "spread_cost": _money(_decimal(estimate.spread)),
            "slippage": _money(_decimal(estimate.slippage)),
            "commission": _money(_decimal(estimate.commission)),
            "impact": _money(_decimal(estimate.market_impact)),
            "regulatory_fee": _money(_decimal(estimate.regulatory_fee)),
            "total_cost": _money(_decimal(estimate.total_cost)),
            "cash_before": _money(cash_before),
            "cash_after": _money(cash_after),
            "position_before": str(held_before),
            "position_after": str(held_after),
            "paper_only": True,
            "production_approved": False,
        }
        return self._write_immutable(path, payload)

    def current_state(
        self, portfolio_id: str, prices: dict[str, Decimal] | None = None
    ) -> dict[str, Any]:
        portfolio = self.portfolio(portfolio_id)
        cash = _decimal(portfolio["initial_cash"])
        positions: dict[str, Decimal] = {}
        total_cost = Decimal("0")
        fills = sorted(
            (
                self._read_verified(path)
                for path in self._event_dir(portfolio_id, "fills").glob("*.json")
            ),
            key=lambda item: str(item["fill_time"]),
        )
        for item in fills:
            ticker = str(item["ticker"])
            quantity = _decimal(item["quantity"])
            cash = _decimal(item["cash_after"])
            positions[ticker] = positions.get(ticker, Decimal("0")) + (
                quantity if item["side"] == PaperSide.BUY.value else -quantity
            )
            total_cost += _decimal(item["total_cost"])
        positions = {key: value for key, value in positions.items() if value != 0}
        marks = prices or {}
        invested = sum(
            (
                quantity * _decimal(marks[ticker])
                for ticker, quantity in positions.items()
                if ticker in marks
            ),
            Decimal("0"),
        )
        unmarked = sorted(set(positions) - set(marks))
        nav = cash + invested
        return {
            "portfolio_id": portfolio_id,
            "mode": "PAPER",
            "cash": _money(cash),
            "invested_value": _money(invested),
            "nav": None if unmarked else _money(nav),
            "positions": {key: str(value) for key, value in sorted(positions.items())},
            "unmarked_positions": unmarked,
            "transaction_costs": _money(total_cost),
            "cash_weight": float(cash / nav) if nav > 0 and not unmarked else None,
            "paper_only": True,
        }

    def mark_to_market(
        self,
        *,
        portfolio_id: str,
        observation_date: date,
        observed_at: datetime,
        prices: dict[str, Decimal],
        benchmark_prices: dict[str, Decimal],
    ) -> dict[str, Any]:
        if observed_at.tzinfo is None or observed_at.date() < observation_date:
            raise ValueError("mark prices must be available no earlier than their observation")
        if set(benchmark_prices) != {"SPY", "QQQ"}:
            raise ValueError("SPY and QQQ benchmark prices are both required")
        state = self.current_state(portfolio_id, prices)
        if state["unmarked_positions"]:
            raise ValueError("all paper holdings require same-date marks")
        previous = self._snapshots(portfolio_id)
        initial = _decimal(self.portfolio(portfolio_id)["starting_nav"])
        prior = previous[-1] if previous else None
        benchmark_nav: dict[str, str] = {}
        for ticker in ("SPY", "QQQ"):
            price = _decimal(benchmark_prices[ticker])
            if price <= 0:
                raise ValueError("benchmark prices must be positive")
            if prior is None:
                benchmark_nav[ticker] = _money(initial)
            else:
                prior_price = _decimal(cast(dict[str, str], prior["benchmark_prices"])[ticker])
                prior_nav = _decimal(cast(dict[str, str], prior["benchmark_nav"])[ticker])
                benchmark_nav[ticker] = _money(prior_nav * price / prior_price)
        nav = _decimal(state["nav"])
        prior_nav = _decimal(prior["ending_nav"]) if prior else initial
        high_water = max([initial, nav, *(_decimal(item["ending_nav"]) for item in previous)])
        payload: dict[str, Any] = {
            "schema_version": "paper-ledger-snapshot-v1",
            "portfolio_id": portfolio_id,
            "date": observation_date.isoformat(),
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "starting_nav": _money(prior_nav),
            "ending_nav": _money(nav),
            "cash": state["cash"],
            "invested_value": state["invested_value"],
            "positions": state["positions"],
            "weights": {
                ticker: float(_decimal(quantity) * _decimal(prices[ticker]) / nav)
                for ticker, quantity in cast(dict[str, str], state["positions"]).items()
            }
            if nav > 0
            else {},
            "daily_pnl": _money(nav - prior_nav),
            "cumulative_pnl": _money(nav - initial),
            "transaction_costs": state["transaction_costs"],
            "drawdown": float(nav / high_water - 1) if high_water else 0.0,
            "benchmark_prices": {
                key: _money(_decimal(value)) for key, value in benchmark_prices.items()
            },
            "benchmark_nav": benchmark_nav,
            "paper_only": True,
        }
        snapshot_identity = {
            "portfolio": portfolio_id,
            "date": observation_date.isoformat(),
        }
        snapshot_id = f"paper-snapshot-{_hash(snapshot_identity)[:24]}"
        payload["snapshot_id"] = snapshot_id
        return self._write_immutable(
            self._event_dir(portfolio_id, "snapshots") / f"{snapshot_id}.json", payload
        )

    def performance(self, portfolio_id: str) -> dict[str, Any]:
        snapshots = self._snapshots(portfolio_id)
        initial = _decimal(self.portfolio(portfolio_id)["starting_nav"])
        if not snapshots:
            return {
                "portfolio_id": portfolio_id,
                "sessions": 0,
                "nav": _money(initial),
                "total_return": 0.0,
                "SPY_return": 0.0,
                "QQQ_return": 0.0,
                "annualized_statistics": "INSUFFICIENT_SAMPLE",
                "paper_only": True,
            }
        navs = [_decimal(item["ending_nav"]) for item in snapshots]
        returns = [float(navs[index] / navs[index - 1] - 1) for index in range(1, len(navs))]
        volatility = None
        if len(returns) >= 2:
            mean = sum(returns) / len(returns)
            volatility = sqrt(sum((item - mean) ** 2 for item in returns) / (len(returns) - 1))
        final = snapshots[-1]
        benchmark_nav = cast(dict[str, str], final["benchmark_nav"])
        costs = _decimal(final["transaction_costs"])
        fill_count = len(tuple(self._event_dir(portfolio_id, "fills").glob("*.json")))
        total_return = float(navs[-1] / initial - 1)
        spy_return = float(_decimal(benchmark_nav["SPY"]) / initial - 1)
        qqq_return = float(_decimal(benchmark_nav["QQQ"]) / initial - 1)
        return {
            "portfolio_id": portfolio_id,
            "start_date": snapshots[0]["date"],
            "end_date": final["date"],
            "sessions": len(snapshots),
            "nav": final["ending_nav"],
            "total_return": total_return,
            "SPY_return": spy_return,
            "QQQ_return": qqq_return,
            "excess_vs_SPY": total_return - spy_return,
            "excess_vs_QQQ": total_return - qqq_return,
            "daily_volatility": volatility,
            "maximum_drawdown": min(float(item["drawdown"]) for item in snapshots),
            "transaction_costs": _money(costs),
            "number_trades": fill_count,
            "annualized_statistics": "INSUFFICIENT_SAMPLE" if len(snapshots) < 60 else "AVAILABLE",
            "paper_only": True,
        }

    def actions(self, portfolio_id: str) -> tuple[dict[str, Any], ...]:
        decisions = {
            str(item["action_id"]): item
            for item in (
                self._read_verified(path)
                for path in self._event_dir(portfolio_id, "decisions").glob("*.json")
            )
        }
        fills = {
            str(item["order_id"]): item
            for item in (
                self._read_verified(path)
                for path in self._event_dir(portfolio_id, "fills").glob("*.json")
            )
        }
        results: list[dict[str, Any]] = []
        for path in sorted(self._event_dir(portfolio_id, "actions").glob("*.json")):
            item = self._read_verified(path)
            action_id = str(item["action_id"])
            item["user_paper_decision"] = decisions.get(action_id, {}).get(
                "user_paper_decision", "PENDING"
            )
            item["simulated_fill"] = fills.get(action_id, {}).get("fill_id", "NOT_FILLED")
            results.append(item)
        return tuple(results)

    def _matching_experiment(self, portfolio_id: str, experiment_id: str) -> dict[str, Any]:
        experiment = self.experiment(portfolio_id, experiment_id)
        if experiment["paper_experiment_id"] != experiment_id:
            raise ValueError("paper experiment does not match immutable portfolio experiment")
        return experiment

    def _write_observation(
        self,
        portfolio_id: str,
        experiment_id: str,
        decision_time: datetime,
        status: str,
        blockers: tuple[str, ...],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "paper-observation-v1",
            "portfolio_id": portfolio_id,
            "paper_experiment_id": experiment_id,
            "decision_time": decision_time.astimezone(UTC).isoformat(),
            "status": status,
            "blockers": list(blockers),
            "paper_only": True,
        }
        observation_id = f"paper-observation-{_hash(payload)[:24]}"
        payload["observation_id"] = observation_id
        return self._write_immutable(
            self._event_dir(portfolio_id, "observations") / f"{observation_id}.json",
            payload,
        )

    def _decision_for_action(self, portfolio_id: str, action_id: str) -> dict[str, Any]:
        matches = [
            self._read_verified(path)
            for path in self._event_dir(portfolio_id, "decisions").glob("*.json")
            if self._read_verified(path)["action_id"] == action_id
        ]
        if len(matches) != 1:
            raise ValueError("paper action requires exactly one immutable user decision")
        return matches[0]

    def _snapshots(self, portfolio_id: str) -> list[dict[str, Any]]:
        return sorted(
            (
                self._read_verified(path)
                for path in self._event_dir(portfolio_id, "snapshots").glob("*.json")
            ),
            key=lambda item: str(item["date"]),
        )

    def _read_event(self, portfolio_id: str, category: str, event_id: str) -> dict[str, Any]:
        return self._read_verified(self._event_dir(portfolio_id, category) / f"{event_id}.json")

    def _event_dir(self, portfolio_id: str, category: str) -> Path:
        path = self._folder(portfolio_id) / category
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _folder(self, portfolio_id: str) -> Path:
        return self.root / self._portfolio_id(portfolio_id)

    @staticmethod
    def _portfolio_id(value: str) -> str:
        normalized = value.strip()
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not normalized or any(character not in allowed for character in normalized):
            raise ValueError(
                "paper portfolio id may contain only letters, numbers, dash and underscore"
            )
        return normalized

    @staticmethod
    def _write_immutable(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = {**payload, "artifact_hash": _hash(payload)}
        if path.exists():
            existing = PaperTradingService._read_verified(path)
            if existing != stored:
                raise ValueError(f"immutable paper artifact conflict: {path.name}")
            return existing
        temporary = path.with_suffix(".tmp")
        temporary.write_text(_canonical(stored) + "\n", encoding="utf-8")
        temporary.replace(path)
        return stored

    @staticmethod
    def _read_verified(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ValueError(f"paper artifact not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"paper artifact must be an object: {path}")
        payload = cast(dict[str, Any], value)
        artifact_hash = payload.pop("artifact_hash", None)
        if artifact_hash != _hash(payload):
            raise ValueError(f"paper artifact hash mismatch: {path}")
        return {**payload, "artifact_hash": artifact_hash}
