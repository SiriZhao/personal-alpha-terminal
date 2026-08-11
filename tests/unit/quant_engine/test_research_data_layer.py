from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from personal_alpha_terminal.quant_engine.alpha_research import StrategyCandidate
from personal_alpha_terminal.quant_engine.alpha_research_workflow import (
    run_alpha_research_capability_audit,
)
from personal_alpha_terminal.quant_engine.backtest.production import (
    CorporateAction,
    CorporateActionType,
)
from personal_alpha_terminal.quant_engine.research_data import (
    HistoricalMembership,
    ResearchDataCapabilities,
    ResearchDataInventory,
    ResearchDatasetState,
    audit_research_inventory,
    eligible_members,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _inventory() -> ResearchDataInventory:
    return ResearchDataInventory(
        dataset_id="live-current-universe",
        as_of=date(2026, 8, 10),
        cutoff=NOW,
        source="current config",
        provider="live adapter",
        raw_price_rows=9000,
        security_count=18,
        universe_snapshot_count=2,
        membership_rows=36,
        delisted_security_count=0,
        identifier_history_rows=0,
        corporate_action_rows=3,
        total_return_version_rows=162,
        latest_universe_version="live-universe",
        latest_live_data_version="live-data",
        capabilities=ResearchDataCapabilities(
            historical_membership_complete=False,
            delistings_complete=False,
            identifier_history_complete=False,
            corporate_actions_pit_complete=False,
            total_return_pit_complete=False,
            raw_ohlcv_complete=True,
            exchange_calendar_complete=True,
            current_constituent_snapshot_only=True,
        ),
    )


def test_current_universe_cannot_certify_historical_backtest() -> None:
    manifest = audit_research_inventory(_inventory())
    assert manifest.certification_state is ResearchDatasetState.NOT_CERTIFIABLE
    assert "CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED" in manifest.blockers
    assert manifest.content_hash is None


def test_future_membership_is_not_visible_and_delisted_member_survives_until_exit() -> None:
    known = HistoricalMembership(
        "US:XNYS:OLD", "stock", date(2020, 1, 1), date(2024, 6, 30),
        datetime(2019, 12, 20, tzinfo=UTC), "index history", "licensed import"
    )
    future = HistoricalMembership(
        "US:XNAS:FUTURE", "stock", date(2024, 1, 1), None,
        datetime(2025, 1, 1, tzinfo=UTC), "late backfill", "import"
    )
    members = eligible_members(
        (known, future), session=date(2024, 3, 1),
        decision_time=datetime(2024, 3, 1, 23, tzinfo=UTC)
    )
    assert members == ("US:XNYS:OLD",)
    assert eligible_members(
        (known,), session=date(2024, 7, 1),
        decision_time=datetime(2024, 7, 1, 23, tzinfo=UTC)
    ) == ()


def test_future_corporate_action_revision_is_rejected() -> None:
    with pytest.raises(ValueError, match="available by its effective date"):
        CorporateAction(
            1, CorporateActionType.SPLIT, date(2025, 1, 2), date(2024, 12, 1),
            datetime(2025, 1, 3, tzinfo=UTC), ratio=2.0, source="fixture"
        )


def test_locked_oos_cannot_select_strategy_candidate() -> None:
    with pytest.raises(ValueError, match="locked OOS"):
        StrategyCandidate(
            "strategy", "1", "params", "data", "manifest", "LOCKED_OOS",
            "oos", "DIAGNOSTIC_ONLY", NOW
        )


def test_inventory_change_alters_manifest_hash_and_is_not_silently_ignored() -> None:
    first = audit_research_inventory(_inventory())
    second = audit_research_inventory(replace(_inventory(), raw_price_rows=9001))
    assert first.inventory_hash != second.inventory_hash
    assert first.manifest_hash != second.manifest_hash


def test_identical_uncertifiable_inputs_produce_identical_e2e_result(tmp_path) -> None:
    first = run_alpha_research_capability_audit(
        _inventory(), output_root=tmp_path, evaluated_at=NOW
    )
    second = run_alpha_research_capability_audit(
        _inventory(), output_root=tmp_path, evaluated_at=NOW
    )
    assert first.result_hash == second.result_hash
    assert first.certification.artifact_id == second.certification.artifact_id
    assert first.certification.status.value == "NOT_CERTIFIABLE"
