from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class QlibBackendStatus:
    available: bool
    runtime: str
    reason: str | None
    permitted_use: str = "factor research only; prediction and order generation are prohibited"


class QlibFactorResearchAdapter:
    """Feature-export boundary for an isolated Qlib research runtime."""

    def status(self) -> QlibBackendStatus:
        runtime = f"{sys.version_info.major}.{sys.version_info.minor}"
        if sys.version_info >= (3, 13):
            return QlibBackendStatus(
                False,
                runtime,
                "Qlib is isolated because the supported research runtime is Python 3.8-3.12",
            )
        if importlib.util.find_spec("qlib") is None:
            return QlibBackendStatus(False, runtime, "pyqlib is not installed in this runtime")
        return QlibBackendStatus(True, runtime, None)

    def build_feature_frame(self, observations: pd.DataFrame) -> pd.DataFrame:
        required = {"datetime", "instrument"}
        missing = required - set(observations.columns)
        if missing:
            raise ValueError(f"Qlib factor frame is missing columns: {sorted(missing)}")
        feature_columns = [column for column in observations.columns if column not in required]
        if not feature_columns:
            raise ValueError("Qlib factor frame requires at least one deterministic feature")
        frame = observations.copy()
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
        frame = frame.set_index(["datetime", "instrument"]).sort_index()
        if frame.index.has_duplicates:
            raise ValueError("Qlib factor frame cannot contain duplicate instrument timestamps")
        return frame[feature_columns]
