from datetime import UTC, date, datetime

from personal_alpha_terminal.backtest.manifest import BacktestRunManifest


def test_backtest_manifest_hash_is_reproducible_and_complete() -> None:
    manifest = BacktestRunManifest(
        code_version="git:abc",
        data_snapshot="data:1",
        universe_snapshot="universe:1",
        factor_version="factor:1",
        parameter_set={"lookback": 252},
        execution_model="next_tradable_open_conservative_v1",
        cost_model="us_daily_cost_v1",
        random_seed=41,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 1, 1),
        benchmark="SPY",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        result_hash="result:abc",
    )
    assert manifest.manifest_hash == manifest.manifest_hash
    assert len(manifest.manifest_hash) == 64
