from personal_alpha_terminal.strategies.us_adaptive_alpha.service import (
    USAdaptiveAlphaService,
)


def test_empty_database_blocks_us_adaptive_alpha_and_disables_data_sleeves(
    session_factory,
) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as session:
        overview = USAdaptiveAlphaService(session).overview()

    assert overview.data_gate.status.value == "blocked"
    assert not overview.data_gate.allowed_for_position_range
    by_name = {item.name: item for item in overview.sleeves}
    assert by_name["quality_constrained_momentum"].status.value == "disabled"
    assert by_name["post_earnings_drift"].status.value == "disabled"
    assert by_name["defensive_allocation"].status.value == "active"
