"""ROUND 8: shadow production hook in the real daily workflow.

A registered challenger in SHADOW mode records what it would recommend in the
shadow ledger, while the official recommendation, target and ledger stay
untouched.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.models import (
    ManualExecutionFill,
    PortfolioTransaction,
)
from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    ExperimentStatus,
    ResearchExperiment,
    ResearchRegistry,
    ShadowLedger,
)
from tests.integration.test_round6_live_portfolio_lifecycle import (
    _positions,
    _seed,
)


def _register_challenger(config: EffectiveRuntimeConfig) -> None:
    registry = ResearchRegistry(config.shadow_registry_path)
    experiment = ResearchExperiment(
        experiment_id="challenger-a-exp-1",
        strategy_id="challenger-a",
        strategy_version="1.0",
        hypothesis="reweight volatility higher, momentum lower",
        factors=("momentum_12_1", "trend_slope", "low_volatility"),
        parameters={
            "momentum_coefficient": 0.002,
            "trend_coefficient": 0.003,
            "low_volatility_coefficient": 0.008,
        },
        universe_version="universe-v1",
        horizon=21,
        benchmark="SPY",
        cost_model_version="cost-v1",
        train_start=date(2025, 1, 2),
        train_end=date(2025, 12, 31),
        validation_start=date(2026, 1, 2),
        validation_end=date(2026, 6, 30),
        oos_start=date(2026, 7, 1),
        oos_end=date(2026, 12, 31),
        results={"oos_net_alpha": 0.0},
        status=ExperimentStatus.RESEARCH_ONLY,
        created_at=datetime(2026, 8, 1, tzinfo=__import__("datetime").timezone.utc),
    )
    registry.append(experiment)


def test_shadow_hook_records_challenger_without_affecting_production(tmp_path: Path) -> None:
    engine, session, portfolio_id, base_config = _seed(tmp_path, empty=True)
    try:
        config = replace(
            base_config,
            shadow_challenger_id="challenger-a",
            shadow_registry_path=tmp_path / "registry.jsonl",
            shadow_ledger_path=tmp_path / "shadow.jsonl",
        )
        _register_challenger(config)
        # re-issue policy for the modified config identity
        from personal_alpha_terminal.application.operational_readiness import (
            DEFAULT_ALLOWED_RESEARCH_STATES,
            OperationalPolicyDecision,
            OperationalPolicyStore,
            build_operational_identity,
            issue_operational_policy,
        )
        from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
            USAdaptiveAlphaCoreV1,
        )

        strategy = USAdaptiveAlphaCoreV1(config.strategy)
        policy = issue_operational_policy(
            identity=build_operational_identity(config, strategy),
            decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
            research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
            issued_by="USER:test:round8",
            reason="isolated round8 shadow acceptance",
            created_at=datetime(2027, 8, 1, tzinfo=__import__("datetime").timezone.utc),
        )
        OperationalPolicyStore(config.operational_policy_path).save(policy, force=True)
        session.flush()

        ProductionDailyWorkflow(session, config).run(
            portfolio_id=portfolio_id,
            decision_time=datetime(2027, 8, 6, 22, tzinfo=__import__("datetime").timezone.utc),
        )
        ledger = ShadowLedger(config.shadow_ledger_path)
        predictions, _outcomes = ledger.load()
        assert predictions, "shadow ledger should contain challenger predictions"
        symbols = {item.symbol for item in predictions.values()}
        assert symbols, "shadow predictions must have symbols"
        # Official output is untouched: no fills, no transactions from shadow.
        assert session.scalar(select(ManualExecutionFill)) is None
        assert session.scalar(select(PortfolioTransaction)) is None
        assert _positions(session, portfolio_id) == {}
    finally:
        engine.dispose()
