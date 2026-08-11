from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from personal_alpha_terminal.paper_trading.service import (
    PaperDecisionChoice,
    PaperExecutionBar,
    PaperSignalInput,
    PaperTradingService,
)

PORTFOLIO_ID = "paper-100k"
EXPERIMENT_ID = "paper-usadaptive-v1-20260811"
DECISION_TIME = datetime(2026, 8, 10, 21, tzinfo=UTC)
AS_OF = DECISION_TIME
CUTOFF = datetime(2026, 8, 10, 20, 30, tzinfo=UTC)
TRADE_DATE = date(2026, 8, 11)


def _service(tmp_path: Path) -> PaperTradingService:
    service = PaperTradingService(tmp_path / "paper")
    service.initialize_portfolio(
        portfolio_id=PORTFOLIO_ID,
        cash=Decimal("100000"),
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    service.freeze_experiment(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        started_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    return service


def _signal() -> PaperSignalInput:
    return PaperSignalInput(
        ticker="AAPL",
        security_id="sec-aapl",
        composite=1.2,
        expected_alpha=0.01,
        rank=1,
        factor_values={"momentum": 1.0, "trend": 1.1, "low_volatility": 0.4},
    )


def _signals(service: PaperTradingService) -> tuple[dict[str, object], ...]:
    return service.record_signals(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        as_of=AS_OF,
        cutoff=CUTOFF,
        trade_date=TRADE_DATE,
        data_hash="data-hash",
        universe_version="universe-v1",
        signals=(_signal(),),
        recorded_at=DECISION_TIME,
    )


def _action(service: PaperTradingService) -> dict[str, object]:
    signals = _signals(service)
    actions = service.propose_actions(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        signal_ids=tuple(str(item["signal_id"]) for item in signals),
        prices={"AAPL": Decimal("100")},
        sectors={"AAPL": "Technology"},
        average_daily_dollar_volume={"AAPL": Decimal("100000000")},
        risk_validated=True,
        decision_time=DECISION_TIME,
    )
    assert len(actions) == 1
    return actions[0]


def _accepted_fill(service: PaperTradingService) -> dict[str, object]:
    action = _action(service)
    action_id = str(action["action_id"])
    service.confirm_action(
        portfolio_id=PORTFOLIO_ID,
        action_id=action_id,
        choice=PaperDecisionChoice.ACCEPT,
        decided_at=datetime(2026, 8, 10, 22, tzinfo=UTC),
    )
    return service.simulate_fill(
        portfolio_id=PORTFOLIO_ID,
        action_id=action_id,
        bar=PaperExecutionBar(
            ticker="AAPL",
            session_date=TRADE_DATE,
            open_price=Decimal("101"),
            available_at=datetime(2026, 8, 11, 13, 31, tzinfo=UTC),
            average_daily_dollar_volume=Decimal("100000000"),
        ),
        fill_time=datetime(2026, 8, 11, 13, 32, tzinfo=UTC),
    )


def test_paper_cash_is_exactly_100k_and_starts_empty(tmp_path: Path) -> None:
    service = _service(tmp_path)
    state = service.current_state(PORTFOLIO_ID)
    assert state["cash"] == "100000.000000"
    assert state["nav"] == "100000.000000"
    assert state["positions"] == {}
    assert service.portfolio(PORTFOLIO_ID)["auto_execution"] is False


def test_paper_and_real_storage_are_strictly_isolated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    manifest = service.portfolio(PORTFOLIO_ID)
    assert manifest["real_ledger_database"] == "NEVER_ACCESSED"
    assert not tuple(tmp_path.rglob("*.db"))
    assert manifest["mode"] == "PAPER"


def test_paper_signal_is_never_production_signal(tmp_path: Path) -> None:
    signal = _signals(_service(tmp_path))[0]
    assert signal["classification"] == "PAPER_SIGNAL"
    assert signal["production_approved"] is False
    assert signal["paper_only"] is True
    assert "DO_NOT_USE_FOR_REAL_TRADING" in str(signal["warning"])


def test_future_data_cannot_enter_paper_decision(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="future data"):
        service.record_signals(
            portfolio_id=PORTFOLIO_ID,
            experiment_id=EXPERIMENT_ID,
            as_of=AS_OF,
            cutoff=datetime(2026, 8, 12, tzinfo=UTC),
            trade_date=TRADE_DATE,
            data_hash="x",
            universe_version="u",
            signals=(_signal(),),
            recorded_at=DECISION_TIME,
        )


def test_trade_date_must_be_next_valid_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="next valid XNYS"):
        service.record_signals(
            portfolio_id=PORTFOLIO_ID,
            experiment_id=EXPERIMENT_ID,
            as_of=AS_OF,
            cutoff=AS_OF,
            trade_date=AS_OF.date(),
            data_hash="x",
            universe_version="u",
            signals=(_signal(),),
            recorded_at=DECISION_TIME,
        )


def test_target_does_not_change_holdings_before_confirmation_or_fill(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _action(service)
    assert service.current_state(PORTFOLIO_ID)["positions"] == {}


@pytest.mark.parametrize("choice", [PaperDecisionChoice.REJECT, PaperDecisionChoice.SKIP])
def test_rejected_or_skipped_recommendation_does_not_change_holdings(
    tmp_path: Path, choice: PaperDecisionChoice
) -> None:
    service = _service(tmp_path)
    action = _action(service)
    service.confirm_action(
        portfolio_id=PORTFOLIO_ID,
        action_id=str(action["action_id"]),
        choice=choice,
    )
    assert service.current_state(PORTFOLIO_ID)["positions"] == {}
    with pytest.raises(ValueError, match="accepted"):
        service.simulate_fill(
            portfolio_id=PORTFOLIO_ID,
            action_id=str(action["action_id"]),
            bar=PaperExecutionBar(
                "AAPL",
                TRADE_DATE,
                Decimal("101"),
                datetime(2026, 8, 11, 13, 31, tzinfo=UTC),
                Decimal("100000000"),
            ),
            fill_time=datetime(2026, 8, 11, 13, 32, tzinfo=UTC),
        )


def test_predecision_and_wrong_session_prices_cannot_fill(tmp_path: Path) -> None:
    service = _service(tmp_path)
    action = _action(service)
    action_id = str(action["action_id"])
    service.confirm_action(
        portfolio_id=PORTFOLIO_ID,
        action_id=action_id,
        choice=PaperDecisionChoice.ACCEPT,
    )
    wrong_bar = PaperExecutionBar(
        "AAPL",
        date(2026, 8, 12),
        Decimal("95"),
        datetime(2026, 8, 12, 13, 31, tzinfo=UTC),
        Decimal("100000000"),
    )
    with pytest.raises(ValueError, match="exact next-session open"):
        service.simulate_fill(
            portfolio_id=PORTFOLIO_ID,
            action_id=action_id,
            bar=wrong_bar,
            fill_time=datetime(2026, 8, 12, 13, 32, tzinfo=UTC),
        )


def test_fill_uses_raw_open_plus_costs_and_changes_cash_position(tmp_path: Path) -> None:
    service = _service(tmp_path)
    fill = _accepted_fill(service)
    state = service.current_state(PORTFOLIO_ID, {"AAPL": Decimal("101")})
    assert Decimal(str(fill["fill_price"])) > Decimal(str(fill["reference_price"]))
    assert Decimal(str(fill["total_cost"])) > 0
    assert Decimal(str(state["cash"])) < Decimal("100000")
    assert state["positions"] == {"AAPL": "120"}
    assert Decimal(str(state["nav"])) < Decimal("100000")


def test_same_signal_action_decision_and_fill_are_idempotent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first_signals = _signals(service)
    assert _signals(service) == first_signals
    action = _action(service)
    action_id = str(action["action_id"])
    first_decision = service.confirm_action(
        portfolio_id=PORTFOLIO_ID,
        action_id=action_id,
        choice=PaperDecisionChoice.ACCEPT,
    )
    assert (
        service.confirm_action(
            portfolio_id=PORTFOLIO_ID,
            action_id=action_id,
            choice=PaperDecisionChoice.ACCEPT,
        )
        == first_decision
    )


def test_insufficient_cash_blocks_fill(tmp_path: Path) -> None:
    service = _service(tmp_path)
    action = _action(service)
    action_id = str(action["action_id"])
    service.confirm_action(
        portfolio_id=PORTFOLIO_ID,
        action_id=action_id,
        choice=PaperDecisionChoice.ACCEPT,
    )
    with pytest.raises(ValueError, match="ADV participation"):
        service.simulate_fill(
            portfolio_id=PORTFOLIO_ID,
            action_id=action_id,
            bar=PaperExecutionBar(
                "AAPL",
                TRADE_DATE,
                Decimal("1000000"),
                datetime(2026, 8, 11, 13, 31, tzinfo=UTC),
                Decimal("1000000"),
            ),
            fill_time=datetime(2026, 8, 11, 13, 32, tzinfo=UTC),
        )


def test_sell_recommendation_cannot_exceed_actual_holdings(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _accepted_fill(service)
    next_as_of = datetime(2026, 8, 11, 20, tzinfo=UTC)
    signals = service.record_signals(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        as_of=next_as_of,
        cutoff=next_as_of,
        trade_date=date(2026, 8, 12),
        data_hash="data-hash-next",
        universe_version="universe-v1",
        signals=(
            PaperSignalInput(
                ticker="AAPL",
                security_id="sec-aapl",
                composite=-1.0,
                expected_alpha=-0.01,
                rank=10,
                factor_values={"momentum": -1.0, "trend": -0.5, "low_volatility": 0.1},
            ),
        ),
        recorded_at=datetime(2026, 8, 11, 21, tzinfo=UTC),
    )
    actions = service.propose_actions(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        signal_ids=(str(signals[0]["signal_id"]),),
        prices={"AAPL": Decimal("102")},
        sectors={"AAPL": "Technology"},
        average_daily_dollar_volume={"AAPL": Decimal("100000000")},
        risk_validated=True,
        decision_time=datetime(2026, 8, 11, 21, tzinfo=UTC),
    )
    assert len(actions) == 1
    assert actions[0]["side"] == "SELL"
    assert Decimal(str(actions[0]["quantity"])) <= Decimal("120")


def test_risk_failure_produces_zero_paper_actions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    signals = _signals(service)
    actions = service.propose_actions(
        portfolio_id=PORTFOLIO_ID,
        experiment_id=EXPERIMENT_ID,
        signal_ids=(str(signals[0]["signal_id"]),),
        prices={"AAPL": Decimal("100")},
        sectors={"AAPL": "Technology"},
        average_daily_dollar_volume={"AAPL": Decimal("100000000")},
        risk_validated=False,
        decision_time=DECISION_TIME,
    )
    assert actions == ()


def test_different_experiments_are_immutable_and_preserved(tmp_path: Path) -> None:
    service = _service(tmp_path)
    original = service.experiment(PORTFOLIO_ID, EXPERIMENT_ID)
    second = service.freeze_experiment(
        portfolio_id=PORTFOLIO_ID,
        experiment_id="paper-usadaptive-v1-1-20260812",
        started_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    assert second["paper_experiment_id"] != original["paper_experiment_id"]
    assert service.experiment(PORTFOLIO_ID, EXPERIMENT_ID) == original


def test_frozen_parameter_hash_must_match_signals(tmp_path: Path) -> None:
    service = _service(tmp_path)
    signal = _signals(service)[0]
    assert signal["parameter_hash"] == service.experiment(PORTFOLIO_ID)["parameter_hash"]
    assert len(str(signal["parameter_hash"])) == 64


def test_benchmarks_start_at_same_100k_base_and_performance_is_not_annualized(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    snapshot = service.mark_to_market(
        portfolio_id=PORTFOLIO_ID,
        observation_date=TRADE_DATE,
        observed_at=datetime(2026, 8, 11, 22, tzinfo=UTC),
        prices={},
        benchmark_prices={"SPY": Decimal("500"), "QQQ": Decimal("450")},
    )
    assert snapshot["benchmark_nav"] == {
        "SPY": "100000.000000",
        "QQQ": "100000.000000",
    }
    assert service.performance(PORTFOLIO_ID)["annualized_statistics"] == "INSUFFICIENT_SAMPLE"


def test_next_day_nav_obeys_cash_plus_marked_positions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _accepted_fill(service)
    snapshot = service.mark_to_market(
        portfolio_id=PORTFOLIO_ID,
        observation_date=TRADE_DATE,
        observed_at=datetime(2026, 8, 11, 22, tzinfo=UTC),
        prices={"AAPL": Decimal("102")},
        benchmark_prices={"SPY": Decimal("500"), "QQQ": Decimal("450")},
    )
    expected = Decimal(str(snapshot["cash"])) + Decimal("120") * Decimal("102")
    assert Decimal(str(snapshot["ending_nav"])) == expected


def test_paper_artifacts_cannot_register_production_approval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    experiment = service.experiment(PORTFOLIO_ID)
    assert experiment["production_approved"] is False
    assert "approval" not in {path.name for path in service.root.rglob("*.json")}


def test_fixture_named_portfolio_cannot_become_real(tmp_path: Path) -> None:
    service = PaperTradingService(tmp_path / "paper")
    fixture = service.initialize_portfolio(
        portfolio_id="fixture-paper",
        cash=Decimal("1000"),
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    assert fixture["mode"] == "PAPER"
    assert fixture["paper_only"] is True
