from datetime import date, timedelta

from personal_alpha_terminal.alpha_discovery.factor_selector import (
    chronological_split,
    discover_factor_combinations,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryConfig,
    FactorDefinition,
    FactorObservation,
    FactorPanel,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


def _panel(*, reverse_after: int | None = None, shared_boundary: bool = False) -> FactorPanel:
    definition = FactorDefinition(
        name="momentum_1m",
        category="momentum",
        direction="high",
        scope="cross_sectional",
        description="Synthetic momentum.",
        formula="rank",
    )
    observations: list[FactorObservation] = []
    for date_index in range(45):
        as_of_date = date(2020, 1, 1) + timedelta(days=date_index * 10)
        for asset_index in range(12):
            expected_rank = (
                11 - asset_index
                if reverse_after is not None and date_index >= reverse_after
                else asset_index
            )
            observations.append(
                FactorObservation(
                    as_of_date=as_of_date,
                    forward_end_date=as_of_date + timedelta(days=10 if shared_boundary else 5),
                    instrument=GraphInstrument(
                        id=asset_index,
                        key=f"stock:{asset_index}",
                        symbol=f"S{asset_index}",
                        name=f"S{asset_index}",
                        market="US",
                        asset_type="stock",
                        industry=None,
                    ),
                    factor_values={"momentum_1m": float(asset_index)},
                    forward_return=expected_rank / 100,
                )
            )
    return FactorPanel(
        market="US",
        horizon_days=5,
        definitions=(definition,),
        observations=tuple(observations),
        data_fingerprint="selector-test",
    )


def _config() -> AlphaDiscoveryConfig:
    return AlphaDiscoveryConfig(
        horizon_days=5,
        rebalance_interval=10,
        minimum_cross_section=10,
        minimum_dates_per_split=5,
        train_fraction=0.50,
        validation_fraction=0.25,
        fdr_alpha=0.10,
        minimum_abs_directional_ic=0.02,
        maximum_combination_size=1,
    )


def test_selector_freezes_on_validation_then_confirms_locked_test() -> None:
    result = discover_factor_combinations(_panel(), _config())

    assert result.tested_factor_count == 1
    assert result.tested_combination_count == 1
    assert len(result.combinations) == 1
    combination = result.combinations[0]
    assert combination.factors == ("momentum_1m",)
    assert combination.status == "test_confirmed"
    assert combination.train.directional_mean_ic == 1
    assert combination.validation.directional_mean_ic == 1
    assert combination.test.directional_mean_ic == 1


def test_selector_does_not_advance_training_only_relationship() -> None:
    result = discover_factor_combinations(
        _panel(reverse_after=22),
        _config(),
    )

    assert result.tested_combination_count == 1
    assert result.combinations == ()


def test_split_purges_labels_that_touch_the_next_partition() -> None:
    split = chronological_split(_panel(shared_boundary=True), _config())

    assert len(split.purged_dates) == 2
    assert split.train_dates[-1] < split.validation_dates[0]
    assert split.validation_dates[-1] < split.test_dates[0]
