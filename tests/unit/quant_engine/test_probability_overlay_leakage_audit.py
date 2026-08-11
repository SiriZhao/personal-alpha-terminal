"""Leakage-audit and honest-degradation tests for the probability overlay.

Part 3 requirements 1/2: the probability overlay must never modify the
deterministic base alpha when no locked-OOS calibration artifact exists, and
the existing probability machinery must remain leakage-free.  These tests pin
that contract so a future change cannot silently inject probabilities into
signal generation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
    USAdaptiveAlphaCoreV1Config,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    ProbabilityCalibrationIdentity,
    ValidationArtifactRegistry,
)

DECISION_TIME = datetime(2027, 8, 6, 22, 0, tzinfo=UTC)
LAST_SESSION = date(2027, 8, 6)
SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE")
DATA_VERSION = "audit-data-version"


def _price_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    sessions = pd.date_range(end=LAST_SESSION, periods=320, freq="B")
    rows: list[dict[str, object]] = []
    for index, symbol in enumerate(SYMBOLS):
        x = np.arange(len(sessions), dtype=float)
        close = 80 + index * 7 + x * (0.03 + index * 0.002) + np.sin(x / (9 + index))
        rows.extend(
            {
                "permanent_security_id": symbol,
                "ticker": symbol,
                "trade_date": session.date(),
                "available_time": datetime.combine(
                    session.date(), datetime.min.time(), tzinfo=UTC
                )
                + timedelta(hours=22),
                "close": float(value),
            }
            for session, value in zip(sessions, close, strict=True)
        )
    metadata = pd.DataFrame(
        {
            "permanent_security_id": SYMBOLS,
            "sector": ["Technology"] * 3 + ["Healthcare"] * 2,
            "market_cap": [10e9, 20e9, 30e9, 40e9, 50e9],
        }
    )
    return pd.DataFrame(rows), metadata


def _strategy() -> USAdaptiveAlphaCoreV1:
    return USAdaptiveAlphaCoreV1(USAdaptiveAlphaCoreV1Config())


def test_uncalibrated_alpha_is_deterministic_and_unchanged(tmp_path: Path) -> None:
    """No calibration artifact -> expected returns identical, confidence 0.

    This is the core Part 3 invariant: unverified probability must not alter
    the deterministic base alpha.
    """

    prices, metadata = _price_inputs()
    strategy = _strategy()
    fingerprint = strategy.config.parameter_fingerprint

    without = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=DATA_VERSION,
        approval=None,
        calibration=None,
    )
    empty_registry = ValidationArtifactRegistry(tmp_path / "empty-artifacts")
    matched = empty_registry.matching_probability_calibration(
        ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version=DATA_VERSION,
            strategy_parameter_hash=fingerprint,
        )
    )
    assert matched is None

    rerun = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=DATA_VERSION,
        approval=None,
        calibration=None,
    )
    assert tuple(item.expected_excess_return for item in without.signals) == tuple(
        item.expected_excess_return for item in rerun.signals
    )
    for signal in without.signals:
        assert signal.confidence == 0.0
        assert signal.confidence_calibrated is False
        assert signal.calibration_id is None


def test_calibration_overlay_changes_confidence_not_expected_return(
    tmp_path: Path,
) -> None:
    """A valid locked-OOS artifact may only gate confidence, never alpha."""

    prices, metadata = _price_inputs()
    strategy = _strategy()
    fingerprint = strategy.config.parameter_fingerprint
    config = EffectiveRuntimeConfig(report_dir=tmp_path / "reports")
    registry = ValidationArtifactRegistry(config.validation_artifact_dir)
    registry.produce_probability_calibration(
        calibration_id="audit-calibration",
        identity=ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version=DATA_VERSION,
            strategy_parameter_hash=fingerprint,
        ),
        method="isotonic",
        calibration_version="audit-v1",
        train_start=date(2024, 1, 1),
        train_end=date(2024, 12, 31),
        calibration_start=date(2025, 1, 1),
        calibration_end=date(2025, 12, 31),
        oos_start=date(2026, 1, 1),
        oos_end=date(2027, 12, 31),
        brier_score=0.2,
        log_loss=0.6,
        expected_calibration_error=0.03,
        sample_count=500,
        reliability_bins=((0.4, 0.41, 100), (0.6, 0.59, 100)),
        created_at=DECISION_TIME - timedelta(days=2),
    )
    calibration = registry.matching_probability_calibration(
        ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version=DATA_VERSION,
            strategy_parameter_hash=fingerprint,
        )
    )
    assert calibration is not None and calibration.locked_oos

    baseline = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=DATA_VERSION,
        approval=None,
        calibration=None,
    )
    calibrated = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=DATA_VERSION,
        approval=None,
        calibration=calibration,
    )
    assert tuple(item.expected_excess_return for item in baseline.signals) == tuple(
        item.expected_excess_return for item in calibrated.signals
    )
    assert tuple(item.raw_signal for item in baseline.signals) == tuple(
        item.raw_signal for item in calibrated.signals
    )
    for signal in calibrated.signals:
        assert signal.confidence_calibrated is True
        assert signal.calibration_id == "audit-calibration"


def test_mismatched_calibration_identity_is_ignored(tmp_path: Path) -> None:
    """A calibration for a different data version must not apply (PIT guard)."""

    prices, metadata = _price_inputs()
    strategy = _strategy()
    fingerprint = strategy.config.parameter_fingerprint
    config = EffectiveRuntimeConfig(report_dir=tmp_path / "reports")
    registry = ValidationArtifactRegistry(config.validation_artifact_dir)
    registry.produce_probability_calibration(
        calibration_id="wrong-version-calibration",
        identity=ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version="some-other-data-version",
            strategy_parameter_hash=fingerprint,
        ),
        method="isotonic",
        calibration_version="audit-v1",
        train_start=date(2024, 1, 1),
        train_end=date(2024, 12, 31),
        calibration_start=date(2025, 1, 1),
        calibration_end=date(2025, 12, 31),
        oos_start=date(2026, 1, 1),
        oos_end=date(2027, 12, 31),
        brier_score=0.2,
        log_loss=0.6,
        expected_calibration_error=0.03,
        sample_count=500,
        reliability_bins=((0.4, 0.41, 100), (0.6, 0.59, 100)),
        created_at=DECISION_TIME - timedelta(days=2),
    )
    matched = registry.matching_probability_calibration(
        ProbabilityCalibrationIdentity(
            alpha_model_version=f"{strategy.model_id}:{strategy.version}",
            alpha_data_version=DATA_VERSION,
            strategy_parameter_hash=fingerprint,
        )
    )
    assert matched is None
    result = strategy.generate(
        prices=prices,
        metadata=metadata,
        decision_time=DECISION_TIME,
        data_version=DATA_VERSION,
        approval=None,
        calibration=None,
    )
    assert all(item.confidence_calibrated is False for item in result.signals)


def test_calibration_windows_must_be_chronological_and_disjoint(
    tmp_path: Path,
) -> None:
    """Leakage guard: overlapping calibration/OOS windows are rejected."""

    config = EffectiveRuntimeConfig(report_dir=tmp_path / "reports")
    registry = ValidationArtifactRegistry(config.validation_artifact_dir)
    identity = ProbabilityCalibrationIdentity(
        alpha_model_version="USAdaptiveAlphaCoreV1:1.0.0",
        alpha_data_version=DATA_VERSION,
        strategy_parameter_hash="x" * 64,
    )
    try:
        registry.produce_probability_calibration(
            calibration_id="leaky-calibration",
            identity=identity,
            method="isotonic",
            calibration_version="audit-v1",
            train_start=date(2024, 1, 1),
            train_end=date(2025, 6, 30),
            calibration_start=date(2025, 1, 1),
            calibration_end=date(2025, 12, 31),
            oos_start=date(2025, 6, 1),
            oos_end=date(2027, 12, 31),
            brier_score=0.2,
            log_loss=0.6,
            expected_calibration_error=0.03,
            sample_count=500,
            reliability_bins=((0.4, 0.41, 100),),
            created_at=DECISION_TIME,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("overlapping calibration windows must be rejected")
