"""CLI handlers for ROUND 8 Alpha Engine 2.0 champion/challenger research."""
from __future__ import annotations

import json
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    ExperimentStatus,
    PromotionPolicy,
    PromotionVerdict,
    ResearchExperiment,
    ResearchRegistry,
    ShadowLedger,
    ShadowOutcome,
    StrategyMetrics,
    evaluate_promotion,
    evaluate_shadow_comparison,
)
from personal_alpha_terminal.quant_engine.alpha_engine2.factor_research import (
    factor_catalog,
)

console = Console()


def round8_research_command(args: Namespace) -> int:
    config = _config(args)
    action = str(args.round8_action)
    if action == "status":
        return _status(config)
    if action == "shadow-report":
        return _shadow_report(config)
    if action == "shadow-append-outcome":
        return _shadow_append_outcome(config, args)
    if action == "register-experiment":
        return _register_experiment(config, args)
    if action == "promotion-evaluate":
        return _promotion_evaluate(args)
    console.print(f"Unknown round8 action: {action}")
    return 2


def _config(args: Namespace) -> EffectiveRuntimeConfig:
    from personal_alpha_terminal.terminal.config import load_config

    return load_config(args.config)


def _status(config: EffectiveRuntimeConfig) -> int:
    registry = ResearchRegistry(config.shadow_registry_path)
    summary = registry.summary()
    console.print("[bold]ROUND 8 - ALPHA ENGINE 2.0 STATUS[/bold]")
    console.print(f"Research registry: {config.shadow_registry_path.resolve()}")
    console.print(f"Experiments recorded: {summary.get('total', 0)}")
    for status in ("PROMOTED", "REJECTED", "RESEARCH_ONLY", "NOT_CERTIFIABLE"):
        console.print(f"  {status}: {summary.get(status, 0)}")
    console.print(f"Shadow ledger: {config.shadow_ledger_path.resolve()}")
    console.print(f"Shadow challenger configured: {config.shadow_challenger_id or '(none)'}")
    console.print("Champion: Classical Quant Core (USAdaptiveAlphaCoreV1)")
    console.print(
        "Challengers default to SHADOW/RESEARCH_ONLY; "
        "none enter production automatically."
    )
    if config.shadow_challenger_id:
        ledger = ShadowLedger(config.shadow_ledger_path)
        predictions, outcomes = ledger.load()
        console.print(
            f"Shadow predictions: {len(predictions)}   Outcomes: {len(outcomes)}"
        )
    table = Table(title="Research Factor Catalog (research-only)")
    table.add_column("Factor")
    table.add_column("Rationale")
    table.add_column("PIT requirement")
    table.add_column("Direction")
    for item in factor_catalog():
        table.add_row(item["name"], item["rationale"], item["pit"], item["direction"])
    console.print(table)
    return 0


def _shadow_report(config: EffectiveRuntimeConfig) -> int:
    ledger = ShadowLedger(config.shadow_ledger_path)
    predictions, outcomes = ledger.load()
    console.print("[bold]SHADOW PRODUCTION LEDGER[/bold]")
    console.print(f"Path: {config.shadow_ledger_path.resolve()}")
    console.print(f"Predictions: {len(predictions)}   Outcomes: {len(outcomes)}")
    if not predictions:
        console.print("No shadow predictions recorded yet.")
        return 0
    if config.shadow_challenger_id:
        comparison = evaluate_shadow_comparison(
            ledger, challenger_id=config.shadow_challenger_id
        )
        mae = (
            f"{comparison.mean_abs_error:.6f}"
            if comparison.mean_abs_error is not None
            else "--"
        )
        agreement = (
            f"{comparison.direction_agreement:.3f}"
            if comparison.direction_agreement is not None
            else "--"
        )
        console.print(
            f"Challenger {comparison.challenger_id}: predictions "
            f"{comparison.prediction_count}, outcomes {comparison.outcome_count}, "
            f"MAE {mae}, direction agreement {agreement}, promoted {comparison.promoted}"
        )
    table = Table(title="Shadow Predictions")
    table.add_column("Shadow ID")
    table.add_column("Challenger")
    table.add_column("Symbol")
    table.add_column("Rank")
    table.add_column("Alpha")
    table.add_column("Recommendation")
    for item in sorted(predictions.values(), key=lambda p: (p.challenger_id, p.rank)):
        table.add_row(
            item.shadow_id,
            item.challenger_id,
            item.symbol,
            str(item.rank),
            f"{item.expected_alpha:+.4f}",
            item.recommendation,
        )
    console.print(table)
    return 0


def _shadow_append_outcome(config: EffectiveRuntimeConfig, args: Namespace) -> int:
    ledger = ShadowLedger(config.shadow_ledger_path)
    outcome = ShadowOutcome(
        shadow_id=str(args.shadow_id),
        observed_at=datetime.fromisoformat(str(args.observed_at)),
        realized_return=float(args.realized_return),
        outcome_source=str(args.source),
        horizon=str(args.horizon),
    )
    ledger.append_outcome(outcome)
    console.print(
        f"Appended shadow outcome for {outcome.shadow_id} "
        f"(realized {outcome.realized_return:+.4f})"
    )
    return 0


def _register_experiment(config: EffectiveRuntimeConfig, args: Namespace) -> int:
    registry = ResearchRegistry(config.shadow_registry_path)
    experiment = ResearchExperiment(
        experiment_id=str(args.experiment_id),
        strategy_id=str(args.strategy_id),
        strategy_version=str(args.strategy_version),
        hypothesis=str(args.hypothesis),
        factors=tuple(item.strip() for item in str(args.factors).split(",") if item.strip()),
        parameters=json.loads(args.parameters),
        universe_version=str(args.universe_version),
        horizon=int(args.horizon),
        benchmark=str(args.benchmark),
        cost_model_version=str(args.cost_model_version),
        train_start=date.fromisoformat(str(args.train_start)),
        train_end=date.fromisoformat(str(args.train_end)),
        validation_start=date.fromisoformat(str(args.validation_start)),
        validation_end=date.fromisoformat(str(args.validation_end)),
        oos_start=date.fromisoformat(str(args.oos_start)),
        oos_end=date.fromisoformat(str(args.oos_end)),
        results=json.loads(args.results),
        status=ExperimentStatus(str(args.status).upper()),
        rejection_reason=str(args.rejection_reason or ""),
        created_at=datetime.now(),
    )
    registry.append(experiment)
    console.print(
        f"Registered experiment {experiment.experiment_id} for {experiment.strategy_id} "
        f"status={experiment.status.value}"
    )
    return 0


def _promotion_evaluate(args: Namespace) -> int:
    payload = json.loads(Path(str(args.metrics)).read_text(encoding="utf-8"))
    champion = StrategyMetrics(**payload["champion"])
    challenger = StrategyMetrics(**payload["challenger"])
    policy = PromotionPolicy(**payload.get("policy", {}))
    evaluation = evaluate_promotion(
        challenger_id=str(args.challenger_id),
        champion=champion,
        challenger=challenger,
        policy=policy,
    )
    console.print(json.dumps(evaluation.document(), ensure_ascii=False, indent=2, sort_keys=True))
    console.print(f"Verdict: {evaluation.verdict.value}")
    if evaluation.verdict is PromotionVerdict.CLASSICAL_CHAMPION_RETAINED:
        console.print("Champion retained; challenger stays SHADOW/RESEARCH_ONLY.")
    return 0
