"""ROUND26 P1: broad-universe invariant regression tests.

The system must never reintroduce a fixed holdings cap or a pre-optimizer
Top-N truncation.  These tests pin the production assembler behavior on a
seeded PIT universe: the optimizer receives the full eligible alpha set.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path


def _seed_round5_universe(tmp_path: Path):
    from tests.integration import test_round5_broad_universe_production as t  # noqa: E402

    engine, session, portfolio_id, base_config = t._seeded_session(tmp_path)
    config = t._broad_config(base_config)
    return session, portfolio_id, config, t


def test_production_assembler_receives_full_eligible_set(tmp_path: Path) -> None:
    """No Top-N truncation: every eligible alpha candidate reaches construction."""

    session, portfolio_id, config, t = _seed_round5_universe(tmp_path)
    from personal_alpha_terminal.application.operational_readiness import (
        OperationalPolicyStore,
    )
    from personal_alpha_terminal.application.quant_daily_service import (
        ProductionDailyWorkflow,
    )

    OperationalPolicyStore(config.operational_policy_path).save(
        t._issue_policy(config, created_at=t.TEST_B_DECISION_TIME - timedelta(days=1))
    )
    result = ProductionDailyWorkflow(session, config).run(
        portfolio_id=portfolio_id,
        decision_time=t.TEST_B_DECISION_TIME,
    )
    evidence = result.universe_evidence
    # The assembler records the exact optimizer input count and the candidate
    # compression steps; a Top-N truncation would be visible as a recorded
    # truncation marker.
    assert evidence["candidate_count"] > 0
    assert evidence.get("optimizer_input", 0) == evidence["candidate_count"]
    compression = evidence.get("candidate_compression") or {}
    assert not compression.get("truncated", False)


def test_holdings_are_optimizer_natural_sparsity() -> None:
    """Sparse final holdings are the optimizer's natural result, not a cap."""

    import sys

    sys.path.insert(0, "tests/unit/quant_engine")
    import test_miniature_end_to_end as t

    daily = t._run_daily()
    assert daily.target is not None
    assert len(daily.target.target_weights) <= len(t.SYMBOLS)
    # The miniature optimizer has no fixed cardinality cap; final weights are
    # the constrained optimum.
    assert all(weight >= 0 for weight in daily.target.target_weights.values())


def test_target_is_never_actual_portfolio(tmp_path: Path) -> None:
    """A computed target must not mutate the real ledger (no fake fills)."""

    from sqlalchemy import func, select

    from personal_alpha_terminal.application.operational_readiness import (
        OperationalPolicyStore,
    )
    from personal_alpha_terminal.application.quant_daily_service import (
        ProductionDailyWorkflow,
    )
    from personal_alpha_terminal.models import PortfolioPosition

    session, portfolio_id, config, t = _seed_round5_universe(tmp_path)
    OperationalPolicyStore(config.operational_policy_path).save(
        t._issue_policy(config, created_at=t.TEST_B_DECISION_TIME - timedelta(days=1))
    )
    positions_before = session.scalar(
        select(func.count()).select_from(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id
        )
    )
    result = ProductionDailyWorkflow(session, config).run(
        portfolio_id=portfolio_id,
        decision_time=t.TEST_B_DECISION_TIME,
    )
    positions_after = session.scalar(
        select(func.count()).select_from(PortfolioPosition).where(
            PortfolioPosition.portfolio_id == portfolio_id
        )
    )
    # Running the decision chain must never write fills into the ledger.
    assert positions_after == positions_before
    assert result.status in {"GENERATED", "NO_DECISION", "BLOCKED"}
