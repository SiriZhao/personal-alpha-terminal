import pytest

from personal_alpha_terminal.alpha_discovery.walk_forward import walk_forward_validate
from tests.unit.test_alpha_factor_selector import _config, _panel


def test_walk_forward_uses_ordered_non_overlapping_oos_folds() -> None:
    result = walk_forward_validate(
        _panel(),
        ("momentum_1m",),
        _config(),
        train_window_dates=15,
        test_window_dates=5,
        minimum_folds=3,
    )

    assert result.status == "stable"
    assert len(result.folds) == 6
    assert result.mean_out_of_sample_ic == pytest.approx(1)
    for fold, following in zip(result.folds, result.folds[1:], strict=False):
        assert max(fold.train_dates) < min(fold.test_dates)
        assert max(fold.test_dates) < min(following.test_dates)


def test_walk_forward_detects_out_of_sample_factor_failure() -> None:
    result = walk_forward_validate(
        _panel(reverse_after=25),
        ("momentum_1m",),
        _config(),
        train_window_dates=15,
        test_window_dates=5,
        minimum_folds=3,
    )

    assert result.status == "unstable"
    assert result.confirmed_fold_ratio < 2 / 3


def test_walk_forward_rejects_overlapping_test_windows() -> None:
    with pytest.raises(ValueError, match="overlapping"):
        walk_forward_validate(
            _panel(),
            ("momentum_1m",),
            _config(),
            train_window_dates=15,
            test_window_dates=5,
            step_dates=2,
        )
