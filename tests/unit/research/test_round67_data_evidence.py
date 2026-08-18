from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from personal_alpha_terminal.research import (
    EvidenceStatus,
    MembershipVintage,
    SymbolVintage,
    TradabilityObservation,
    create_locked_oos_manifest,
    default_inventory,
    evaluate_data_evidence,
    evaluate_tradability,
    membership_active_as_of,
    render_scorecard,
    resolve_symbol_vintage,
    seal_locked_oos_manifest,
    verify_locked_oos_manifest,
)


def test_default_inventory_is_machine_readable_and_blocks_promotion() -> None:
    inventory = default_inventory()
    result = evaluate_data_evidence(inventory)
    document = inventory.document()
    assert document["inventory_hash"] == inventory.inventory_hash
    assert len(document["fields"]) >= 18
    assert result.overall_status is EvidenceStatus.BLOCKED_DATA_QUALITY
    assert result.diagnostic_mode_allowed
    assert not result.promotion_allowed
    assert any("universe_membership" in blocker for blocker in result.blockers)


def test_locked_oos_is_immutable_single_evaluation_and_reproducible() -> None:
    created_at = datetime(2026, 8, 18, 1, tzinfo=UTC)
    kwargs = dict(
        dataset_fingerprint="dataset-hash",
        model_config_hash="model-hash",
        feature_schema_hash="schema-hash",
        train_start=date(2020, 1, 2),
        train_end=date(2024, 12, 31),
        evaluation_start=date(2025, 1, 2),
        evaluation_end=date(2026, 7, 31),
        created_at=created_at,
    )
    first = create_locked_oos_manifest(**kwargs)
    second = create_locked_oos_manifest(**kwargs)
    assert first.manifest_hash == second.manifest_hash
    assert verify_locked_oos_manifest(first) == (
        "LOCKED_OOS_NOT_EVALUATED_OR_SEALED",
        "LOCKED_OOS_EVALUATION_COUNT_NOT_ONE",
    )
    sealed = seal_locked_oos_manifest(
        first,
        evaluation_id="eval-1",
        dataset_fingerprint="dataset-hash",
    )
    assert verify_locked_oos_manifest(sealed) == ()
    with pytest.raises(ValueError, match="may run once"):
        seal_locked_oos_manifest(
            sealed,
            evaluation_id="eval-2",
            dataset_fingerprint="dataset-hash",
        )
    with pytest.raises(ValueError, match="post-hoc"):
        seal_locked_oos_manifest(
            create_locked_oos_manifest(**kwargs),
            evaluation_id="eval-1",
            dataset_fingerprint="dataset-hash",
            post_hoc_tuning=True,
        )


def _observation(**overrides: object) -> TradabilityObservation:
    base: dict[str, object] = {
        "permanent_security_id": "US:XNAS:AAA",
        "symbol_at_decision": "AAA",
        "symbol_at_execution": "AAA",
        "decision_session": date(2026, 8, 17),
        "decision_time": datetime(2026, 8, 17, 21, tzinfo=UTC),
        "information_available_at": datetime(2026, 8, 17, 20, 30, tzinfo=UTC),
        "execution_session": date(2026, 8, 18),
        "execution_time": datetime(2026, 8, 18, 13, 31, tzinfo=UTC),
        "execution_open": 100.0,
        "open_available_at": datetime(2026, 8, 18, 13, 31, tzinfo=UTC),
        "open_tradable": True,
        "halted": False,
        "volume": 1000.0,
        "quote_observed_at": datetime(2026, 8, 18, 13, 31, tzinfo=UTC),
        "benchmark_session": date(2026, 8, 18),
    }
    base.update(overrides)
    return TradabilityObservation(**base)


def test_tradability_accepts_next_session_and_rejects_holiday_and_bad_fill() -> None:
    calendar = (date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19))
    good = evaluate_tradability((_observation(),), verified_calendar=calendar)
    assert good.status is EvidenceStatus.PASS
    bad = evaluate_tradability(
        (
            _observation(
                execution_session=date(2026, 8, 17),
                execution_open=None,
                open_available_at=None,
                halted=True,
                volume=0.0,
                quote_observed_at=datetime(2026, 8, 15, tzinfo=UTC),
                symbol_at_execution="NEW",
                benchmark_session=date(2026, 8, 19),
            ),
        ),
        verified_calendar=calendar,
        stale_after=timedelta(hours=1),
    )
    assert bad.status is EvidenceStatus.BLOCKED_TRADABILITY
    assert any("MISSING_NEXT_OPEN" in item for item in bad.blockers)
    assert any("UNRECORDED_SYMBOL_TRANSITION" in item for item in bad.blockers)
    assert any("BENCHMARK_SESSION_MISMATCH" in item for item in bad.blockers)


def test_scorecard_is_concise_but_exposes_all_required_dimensions() -> None:
    scorecard = render_scorecard()
    for label in (
        "PIT integrity",
        "survivorship integrity",
        "OOS integrity",
        "price integrity",
        "benchmark integrity",
        "fundamental timestamp integrity",
        "news timestamp integrity",
        "tradability integrity",
        "corporate action integrity",
        "reproducibility",
    ):
        assert label in scorecard


def test_symbol_change_fixture_uses_permanent_identity_without_backfill() -> None:
    available = datetime(2020, 1, 1, tzinfo=UTC)
    securities = (
        SymbolVintage(
            permanent_security_id="PERM-1",
            ticker="OLD",
            valid_from=date(2010, 1, 1),
            valid_to=date(2019, 12, 31),
            available_at=available,
        ),
        SymbolVintage(
            permanent_security_id="PERM-1",
            ticker="NEW",
            valid_from=date(2020, 1, 1),
            valid_to=None,
            available_at=available,
        ),
    )
    assert resolve_symbol_vintage(
        securities,
        permanent_security_id="PERM-1",
        session=date(2019, 12, 31),
        decision_time=available,
    ) == "OLD"
    assert resolve_symbol_vintage(
        securities,
        permanent_security_id="PERM-1",
        session=date(2020, 1, 1),
        decision_time=available,
    ) == "NEW"


def test_delisting_and_membership_fixture_respects_effective_boundaries() -> None:
    cutoff = datetime(2020, 6, 30, 20, tzinfo=UTC)
    membership = MembershipVintage(
        permanent_security_id="PERM-DELISTED",
        effective_from=date(2020, 1, 2),
        effective_to=date(2020, 6, 30),
        available_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    security = SymbolVintage(
        permanent_security_id="PERM-DELISTED",
        ticker="FAIL",
        valid_from=date(2018, 1, 2),
        valid_to=date(2020, 6, 30),
        delisting_date=date(2020, 6, 30),
        available_at=cutoff,
    )
    assert membership_active_as_of(membership, session=date(2020, 6, 30), decision_time=cutoff)
    assert not membership_active_as_of(
        membership,
        session=date(2020, 7, 1),
        decision_time=cutoff,
    )
    assert security.delisting_date == date(2020, 6, 30)
    assert resolve_symbol_vintage(
        (security,),
        permanent_security_id="PERM-DELISTED",
        session=date(2020, 7, 1),
        decision_time=cutoff,
    ) is None
