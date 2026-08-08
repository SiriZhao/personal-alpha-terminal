from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from math import isfinite

import pandas as pd

from personal_alpha_terminal.terminal.cache import CacheLineage


class DataSafetyStatus(StrEnum):
    SAFE = "SAFE"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class QualityComponents:
    freshness: float
    completeness: float
    timestamp_integrity: float
    provider_agreement: float
    corporate_action_integrity: float
    outlier_integrity: float

    @property
    def score(self) -> float:
        weights = (0.20, 0.20, 0.15, 0.15, 0.15, 0.15)
        values = (
            self.freshness,
            self.completeness,
            self.timestamp_integrity,
            self.provider_agreement,
            self.corporate_action_integrity,
            self.outlier_integrity,
        )
        return round(sum(weight * value for weight, value in zip(weights, values, strict=True)), 2)


@dataclass(frozen=True, slots=True)
class SymbolQuality:
    symbol: str
    status: str
    latest_date: date | None
    missing_ratio: float
    duplicate_count: int
    anomaly_count: int
    continuity_gaps: int
    provider: str | None
    issues: tuple[str, ...]
    quality_score: float = 0.0
    components: QualityComponents | None = None
    safety_status: DataSafetyStatus = DataSafetyStatus.BLOCKED
    provider_disagreement: float | None = None


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    status: str
    symbols: tuple[SymbolQuality, ...]
    required_failures: tuple[str, ...]
    generated_on: date
    safety_status: DataSafetyStatus = DataSafetyStatus.BLOCKED
    minimum_quality_score: float = 0.0

    @property
    def coverage_ratio(self) -> float:
        if not self.symbols:
            return 0.0
        return sum(item.status != "FAILED" for item in self.symbols) / len(self.symbols)

    @property
    def permits_executable_actions(self) -> bool:
        return self.safety_status is DataSafetyStatus.SAFE


class DataSafetyGate:
    """Fail-closed gate between canonical market data and trading-style actions."""

    EXECUTABLE_ACTIONS = frozenset({"BUY", "ADD", "REDUCE", "SELL"})

    def __init__(self, *, safe_threshold: float = 80.0, watch_threshold: float = 65.0) -> None:
        if not 0 <= watch_threshold <= safe_threshold <= 100:
            raise ValueError("data safety thresholds must satisfy 0 <= watch <= safe <= 100")
        self.safe_threshold = safe_threshold
        self.watch_threshold = watch_threshold

    def classify(self, score: float, *, critical_issue: bool) -> DataSafetyStatus:
        if critical_issue or not isfinite(score) or score < self.watch_threshold:
            return DataSafetyStatus.BLOCKED
        if score < self.safe_threshold:
            return DataSafetyStatus.DEGRADED
        return DataSafetyStatus.SAFE

    def permits(self, action: str, status: DataSafetyStatus) -> bool:
        normalized = action.upper()
        if normalized in self.EXECUTABLE_ACTIONS:
            return status is DataSafetyStatus.SAFE
        return normalized in {"HOLD", "WATCH", "NO ACTION"}


class DataQualityValidator:
    """Canonical OHLCV checks with an explicit numeric score and fail-closed gate."""

    def __init__(
        self,
        *,
        max_stale_trading_days: int = 3,
        safe_threshold: float = 80.0,
        watch_threshold: float = 65.0,
        maximum_provider_difference: float = 0.02,
    ) -> None:
        self.max_stale_trading_days = max_stale_trading_days
        self.maximum_provider_difference = maximum_provider_difference
        self.gate = DataSafetyGate(
            safe_threshold=safe_threshold,
            watch_threshold=watch_threshold,
        )

    def validate(
        self,
        data: dict[str, tuple[pd.DataFrame, CacheLineage]],
        *,
        required_symbols: tuple[str, ...],
        as_of: date,
        provider_disagreements: dict[str, float | None] | None = None,
    ) -> DataQualityReport:
        disagreements = provider_disagreements or {}
        results: list[SymbolQuality] = []
        for symbol in sorted(set(data) | set(required_symbols)):
            item = data.get(symbol)
            if item is None:
                components = QualityComponents(0, 0, 0, 0, 0, 0)
                results.append(
                    SymbolQuality(
                        symbol,
                        "FAILED",
                        None,
                        1.0,
                        0,
                        0,
                        0,
                        None,
                        ("no canonical data",),
                        components=components,
                    )
                )
                continue
            frame, lineage = item
            results.append(
                self._validate_symbol(
                    symbol,
                    frame,
                    lineage,
                    as_of,
                    disagreements.get(symbol),
                )
            )
        required_failures = tuple(
            item.symbol
            for item in results
            if item.symbol in required_symbols
            and item.safety_status is DataSafetyStatus.BLOCKED
        )
        minimum = min((item.quality_score for item in results), default=0.0)
        if required_failures:
            safety = DataSafetyStatus.BLOCKED
        elif any(item.safety_status is DataSafetyStatus.BLOCKED for item in results):
            safety = DataSafetyStatus.DEGRADED
        elif any(item.safety_status is DataSafetyStatus.DEGRADED for item in results):
            safety = DataSafetyStatus.DEGRADED
        else:
            safety = DataSafetyStatus.SAFE
        status = {
            DataSafetyStatus.SAFE: "PASSED",
            DataSafetyStatus.DEGRADED: "DEGRADED",
            DataSafetyStatus.BLOCKED: "BLOCKED",
        }[safety]
        return DataQualityReport(status, tuple(results), required_failures, as_of, safety, minimum)

    def _validate_symbol(
        self,
        symbol: str,
        frame: pd.DataFrame,
        lineage: CacheLineage,
        as_of: date,
        provider_disagreement: float | None,
    ) -> SymbolQuality:
        required_columns = ("date", "open", "high", "low", "close", "volume")
        missing_columns = [column for column in required_columns if column not in frame]
        if missing_columns or frame.empty:
            components = QualityComponents(0, 0, 0, 0, 0, 0)
            return SymbolQuality(
                symbol,
                "FAILED",
                None,
                1.0,
                0,
                0,
                0,
                lineage.provider,
                tuple(["empty frame", *missing_columns]),
                components=components,
            )
        normalized = frame.copy()
        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
        duplicate_count = int(normalized.duplicated("date").sum())
        latest = normalized["date"].max().date() if normalized["date"].notna().any() else None
        missing_ratio = float(normalized[list(required_columns)].isna().mean().mean())
        invalid_envelope = (normalized["high"] < normalized[["open", "close"]].max(axis=1)) | (
            normalized["low"] > normalized[["open", "close"]].min(axis=1)
        )
        invalid_prices = (normalized[["open", "high", "low", "close"]] <= 0).any(axis=1)
        invalid_volume = normalized["volume"] < 0
        future_dates = normalized["date"].dt.date > as_of
        returns = normalized["close"].pct_change().abs()
        abnormal_return = returns > 0.80
        anomalies = int(
            (
                invalid_envelope
                | invalid_prices
                | invalid_volume
                | abnormal_return
                | future_dates
            ).sum()
        )
        ordered = normalized["date"].dropna().sort_values().drop_duplicates()
        weekday_gaps = 0
        if len(ordered) > 1:
            expected = pd.bdate_range(ordered.iloc[0], ordered.iloc[-1])
            weekday_gaps = max(0, len(expected.difference(pd.DatetimeIndex(ordered))))
        stale_days = 10_000 if latest is None else max(0, len(pd.bdate_range(latest, as_of)) - 1)
        issues: list[str] = []
        if missing_ratio > 0:
            issues.append(f"missing={missing_ratio:.2%}")
        if duplicate_count:
            issues.append(f"duplicates={duplicate_count}")
        if anomalies:
            issues.append(f"anomalies={anomalies}")
        if weekday_gaps:
            issues.append(f"weekday_gaps={weekday_gaps}")
        if stale_days > self.max_stale_trading_days:
            issues.append(f"stale_trading_days={stale_days}")
        if provider_disagreement is None:
            issues.append("second_source_unavailable")
        elif provider_disagreement > self.maximum_provider_difference:
            issues.append(f"provider_disagreement={provider_disagreement:.2%}")

        freshness = max(0.0, 100.0 - max(0, stale_days - self.max_stale_trading_days) * 20.0)
        completeness = max(0.0, 100.0 * (1.0 - min(1.0, missing_ratio * 5)))
        timestamp_integrity = 0.0 if latest is None or future_dates.any() else 100.0
        if provider_disagreement is None:
            agreement = 65.0
        else:
            agreement = max(0.0, 100.0 * (1.0 - provider_disagreement / 0.10))
        adjustment_policy = lineage.adjustment_policy.strip().lower()
        corporate_action_certified = "corporate_actions_certified" in adjustment_policy
        has_adjusted_snapshot = "adjusted" in adjustment_policy
        corporate_action = (
            100.0 if corporate_action_certified else 50.0 if has_adjusted_snapshot else 0.0
        )
        if not corporate_action_certified:
            issues.append("corporate_action_lineage_not_certified")
        outlier = max(0.0, 100.0 - anomalies * 30.0 - duplicate_count * 25.0)
        components = QualityComponents(
            freshness,
            completeness,
            timestamp_integrity,
            agreement,
            corporate_action,
            outlier,
        )
        score = components.score
        critical = (
            latest is None
            or missing_ratio > 0.10
            or duplicate_count > 0
            or anomalies > 0
            or stale_days > self.max_stale_trading_days
            or not corporate_action_certified
            or (
                provider_disagreement is not None
                and provider_disagreement > self.maximum_provider_difference
            )
        )
        safety = self.gate.classify(score, critical_issue=critical)
        status = {
            DataSafetyStatus.SAFE: "PASSED",
            DataSafetyStatus.DEGRADED: "WARNING",
            DataSafetyStatus.BLOCKED: "FAILED",
        }[safety]
        return SymbolQuality(
            symbol,
            status,
            latest,
            missing_ratio,
            duplicate_count,
            anomalies,
            weekday_gaps,
            lineage.provider,
            tuple(issues),
            score,
            components,
            safety,
            provider_disagreement,
        )
