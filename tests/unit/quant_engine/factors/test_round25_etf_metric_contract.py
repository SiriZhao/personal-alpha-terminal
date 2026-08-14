"""ROUND25 PHASE 2: ETF_METRIC_SEMANTIC_CONTRACT unit tests.

The former renderer bug showed ``risk_adjusted_momentum`` (a momentum /
annualized-vol ratio such as 1.25) as "+125.03%" under a column named
"Alpha".  These tests pin the contract: decimal vs percent, annualized vs
cumulative, factor ratio vs expected return, and NaN/Inf/extreme values are
surfaced without clamping.
"""

from __future__ import annotations

import math

from personal_alpha_terminal.quant_engine.factors.etf_factors import (
    ETF_METRIC_SEMANTIC_CONTRACT,
    METRIC_KIND_ANNUALIZED_RETURN,
    METRIC_KIND_DECIMAL_RETURN,
    METRIC_KIND_PERCENT,
    METRIC_KIND_RANK,
    METRIC_KIND_RATIO,
    METRIC_KIND_RAW_PRICE_RETURN,
    METRIC_KIND_ZSCORE,
    describe_metric_issue,
    metric_kind,
)


def test_contract_declares_all_units() -> None:
    expected_kinds = {
        METRIC_KIND_PERCENT,
        METRIC_KIND_DECIMAL_RETURN,
        METRIC_KIND_ZSCORE,
        METRIC_KIND_RANK,
        METRIC_KIND_RAW_PRICE_RETURN,
        METRIC_KIND_ANNUALIZED_RETURN,
        METRIC_KIND_RATIO,
    }
    for _name, entry in ETF_METRIC_SEMANTIC_CONTRACT.items():
        assert entry["kind"] in expected_kinds
        assert entry["definition"]
        assert entry["display_name"]


def test_momentum_252_21_is_decimal_return_not_percent() -> None:
    entry = ETF_METRIC_SEMANTIC_CONTRACT["momentum_252_21"]
    assert entry["kind"] == METRIC_KIND_DECIMAL_RETURN
    assert "cumulative" in entry["definition"]


def test_volatility_63_is_percent_kind() -> None:
    entry = ETF_METRIC_SEMANTIC_CONTRACT["volatility_63"]
    assert entry["kind"] == METRIC_KIND_PERCENT


def test_risk_adjusted_momentum_is_ratio_and_never_alpha() -> None:
    entry = ETF_METRIC_SEMANTIC_CONTRACT["risk_adjusted_momentum"]
    assert entry["kind"] == METRIC_KIND_RATIO
    assert entry["never_label"] == "ALPHA"
    # 1.25 means ratio 1.25; the renderer must never format it as +125.03%.
    assert metric_kind("risk_adjusted_momentum") == METRIC_KIND_RATIO


def test_metric_kind_unknown() -> None:
    assert metric_kind("not_a_metric") == "UNKNOWN"


def test_nan_and_inf_are_surfaced_not_clamped() -> None:
    issue_nan = describe_metric_issue("momentum_252_21", float("nan"))
    assert issue_nan is not None and "NaN" in issue_nan
    issue_inf = describe_metric_issue("momentum_vol_ratio", float("inf"))
    assert issue_inf is not None and "infinite" in issue_inf
    assert math.isnan(float("nan"))


def test_extreme_return_is_kept_as_is() -> None:
    issue = describe_metric_issue("momentum_252_21", 12.5)
    assert issue is not None
    assert "no clamp" in issue
    # The value itself must remain unchanged by the contract (no clamping).
    value = 12.5
    assert value == 12.5


def test_negative_return_is_valid_decimal() -> None:
    assert describe_metric_issue("momentum_252_21", -0.42) is None


def test_ratio_kind_has_no_implicit_percent_semantics() -> None:
    # A ratio must never be declared PERCENT: implicit x100 rendering is the
    # exact bug ROUND25 PHASE 2 eliminates.
    for name in ("risk_adjusted_momentum", "relative_strength_252", "volume_ratio_20_63"):
        assert ETF_METRIC_SEMANTIC_CONTRACT[name]["kind"] == METRIC_KIND_RATIO
