"""ROUND 14: PIT feature/outcome-separated research dataset (SHADOW only).

This module reads the immutable Round 13 research feature artifacts and joins
them to price data using the same exchange-session clock used by event study.
It never reads an outcome whose market session close is later than the dataset
cutoff. The output is a research artifact, not a production feature.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, cast

import pandas as pd

from personal_alpha_terminal.intelligence.time import EventTradingClock

DATASET_SCHEMA_VERSION = "round14-feature-outcome-v1"
PRODUCTION_INFLUENCE = 0.0
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
RESEARCH_STATUS = "RESEARCH_LIMITED_SURVIVORSHIP"


@dataclass(frozen=True, slots=True)
class FeatureOutcomeRecord:
    dataset_id: str
    issuer_id: str
    ticker_asof: str | None
    feature_name: str
    feature_value: float
    feature_as_of: datetime
    horizon: int
    baseline_session: str | None
    outcome_session: str | None
    outcome_available_at: datetime | None
    asset_return: float | None
    benchmark_return: float | None
    abnormal_return: float | None
    status: str
    price_semantics: str


@dataclass(frozen=True, slots=True)
class FeatureOutcomeDataset:
    dataset_id: str
    feature_dataset_id: str
    as_of: datetime
    benchmark: str
    status: str
    production_influence: float
    schema_version: str
    outcome_rows: tuple[FeatureOutcomeRecord, ...]
    dataset_hash: str

    def document(self) -> dict[str, Any]:
        return _dataset_document(
            self.dataset_id,
            self.feature_dataset_id,
            self.as_of,
            self.benchmark,
            self.status,
            self.outcome_rows,
            self.dataset_hash,
        )


def build_outcomes(
    feature_document: dict[str, Any],
    *,
    dataset_id: str | None = None,
    prices_by_symbol: dict[str, pd.Series],
    benchmark_symbol: str,
    cutoff: datetime,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    clock: EventTradingClock | None = None,
) -> FeatureOutcomeDataset:
    """Join research features to realized outcomes at a PIT cutoff."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("outcome cutoff must be timezone-aware")
    if not horizons or any(value < 1 for value in horizons):
        raise ValueError("outcome horizons must be positive")
    if benchmark_symbol not in prices_by_symbol:
        raise ValueError(f"benchmark price series is missing: {benchmark_symbol}")

    feature_dataset_id = str(feature_document.get("dataset_id") or "UNKNOWN")
    dataset_id = dataset_id or feature_dataset_id
    benchmark = _validated_series(prices_by_symbol[benchmark_symbol], benchmark_symbol)
    resolved_clock = clock or EventTradingClock()
    rows: list[FeatureOutcomeRecord] = []

    for row in _feature_rows(feature_document.get("features")):
        issuer_id = str(row.get("issuer_id") or "")
        ticker = row.get("ticker_asof")
        features = _feature_values(row.get("llm_shadow_features"))
        feature_as_of = _feature_as_of(row)
        if feature_as_of is None:
            rows.extend(
                _status_record(
                    dataset_id, issuer_id, ticker, name, value, None, 0, None, None, None,
                    "NO_FEATURE_TIMESTAMP", "no_timestamp",
                )
                for name, value in features
            )
            continue
        if ticker is None or ticker not in prices_by_symbol:
            rows.extend(
                _status_record(
                    dataset_id, issuer_id, ticker, name, value, feature_as_of, 0, None, None, None,
                    "NO_PRICE_SERIES", "adjusted_close_else_close",
                )
                for name, value in features
            )
            continue

        asset = _validated_series(prices_by_symbol[ticker], ticker)
        common = asset.index.intersection(benchmark.index).sort_values()
        mapping = resolved_clock.map(feature_as_of)
        baseline = mapping.last_completed_session
        if baseline is None or baseline not in common:
            rows.extend(
                _status_record(
                    dataset_id, issuer_id, ticker, name, value, feature_as_of, 0, None, None, None,
                    "NO_BASELINE_SESSION", "adjusted_close_else_close",
                )
                for name, value in features
            )
            continue

        baseline_index = int(common.get_loc(baseline))
        for name, value in sorted(features):
            for horizon in horizons:
                terminal_index = baseline_index + horizon
                if terminal_index >= len(common):
                    rows.append(
                        _status_record(
                            dataset_id, issuer_id, ticker, name, value, feature_as_of, horizon,
                            str(baseline), None, None, "RIGHT_CENSORED",
                            "adjusted_close_else_close",
                        )
                    )
                    continue
                outcome_session = common[terminal_index]
                outcome_available_at = resolved_clock.session_close(outcome_session)
                start_asset = float(asset.loc[baseline])
                end_asset = float(asset.loc[outcome_session])
                start_benchmark = float(benchmark.loc[baseline])
                end_benchmark = float(benchmark.loc[outcome_session])
                values = (start_asset, end_asset, start_benchmark, end_benchmark)
                if outcome_available_at > cutoff:
                    rows.append(
                        _status_record(
                            dataset_id, issuer_id, ticker, name, value, feature_as_of, horizon,
                            str(baseline), str(outcome_session), outcome_available_at,
                            "OUTCOME_PENDING", "adjusted_close_else_close",
                        )
                    )
                    continue
                if any(not isfinite(item) or item <= 0 for item in values):
                    rows.append(
                        _status_record(
                            dataset_id, issuer_id, ticker, name, value, feature_as_of, horizon,
                            str(baseline), str(outcome_session), outcome_available_at,
                            "NO_VALID_OUTCOME_PRICE", "adjusted_close_else_close",
                        )
                    )
                    continue
                asset_return = end_asset / start_asset - 1.0
                benchmark_return = end_benchmark / start_benchmark - 1.0
                rows.append(
                    FeatureOutcomeRecord(
                        dataset_id=dataset_id,
                        issuer_id=issuer_id,
                        ticker_asof=ticker,
                        feature_name=name,
                        feature_value=value,
                        feature_as_of=feature_as_of,
                        horizon=horizon,
                        baseline_session=str(baseline),
                        outcome_session=str(outcome_session),
                        outcome_available_at=outcome_available_at,
                        asset_return=asset_return,
                        benchmark_return=benchmark_return,
                        abnormal_return=asset_return - benchmark_return,
                        status="OUTCOME_READY",
                        price_semantics="adjusted_close_else_close",
                    )
                )

    outcome_rows = tuple(rows)
    identity = _dataset_document(
        dataset_id, feature_dataset_id, cutoff, benchmark_symbol, RESEARCH_STATUS,
        outcome_rows, "",
    )
    dataset_hash = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return FeatureOutcomeDataset(
        dataset_id=dataset_id,
        feature_dataset_id=feature_dataset_id,
        as_of=cutoff,
        benchmark=benchmark_symbol,
        status=RESEARCH_STATUS,
        production_influence=PRODUCTION_INFLUENCE,
        schema_version=DATASET_SCHEMA_VERSION,
        outcome_rows=outcome_rows,
        dataset_hash=dataset_hash,
    )


def write_outcome_dataset(path: Path, dataset: FeatureOutcomeDataset) -> None:
    rendered = json.dumps(dataset.document(), ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable outcome dataset: {path}")
    path.write_text(rendered, encoding="utf-8")


def _dataset_document(
    dataset_id: str,
    feature_dataset_id: str,
    as_of: datetime,
    benchmark: str,
    status: str,
    outcome_rows: tuple[FeatureOutcomeRecord, ...],
    dataset_hash: str,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "feature_dataset_id": feature_dataset_id,
        "as_of": as_of.isoformat(),
        "benchmark": benchmark,
        "status": status,
        "production_influence": PRODUCTION_INFLUENCE,
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_hash": dataset_hash,
        "future_outcomes_read_during_build": False,
        "outcome_rows": [_json_record(item) for item in outcome_rows],
    }


def _json_record(record: FeatureOutcomeRecord) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(asdict(record), default=str, sort_keys=True)))


def _feature_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _feature_values(value: object) -> list[tuple[str, float]]:
    if not isinstance(value, dict):
        return []
    return [(str(name), _float(item)) for name, item in value.items()]


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _feature_as_of(row: dict[str, Any]) -> datetime | None:
    events = row.get("event_features")
    if isinstance(events, list):
        timestamps: list[datetime] = []
        for item in events:
            if not isinstance(item, dict) or not item.get("available_at"):
                continue
            parsed = datetime.fromisoformat(str(item["available_at"]).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                continue
            timestamps.append(parsed)
        if timestamps:
            return max(timestamps)
    decision = row.get("decision_date")
    if decision:
        parsed_date = date.fromisoformat(str(decision)[:10])
        return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)
    return None


def _status_record(
    dataset_id: str,
    issuer_id: str,
    ticker: str | None,
    feature_name: str,
    feature_value: float,
    feature_as_of: datetime | None,
    horizon: int,
    baseline_session: str | None,
    outcome_session: str | None,
    outcome_available_at: datetime | None,
    status: str,
    price_semantics: str,
) -> FeatureOutcomeRecord:
    if feature_as_of is None:
        feature_as_of = datetime(1970, 1, 1, tzinfo=UTC)
    return FeatureOutcomeRecord(
        dataset_id=dataset_id,
        issuer_id=issuer_id,
        ticker_asof=ticker,
        feature_name=feature_name,
        feature_value=feature_value,
        feature_as_of=feature_as_of,
        horizon=horizon,
        baseline_session=baseline_session,
        outcome_session=outcome_session,
        outcome_available_at=outcome_available_at,
        asset_return=None,
        benchmark_return=None,
        abnormal_return=None,
        status=status,
        price_semantics=price_semantics,
    )


def _validated_series(series: pd.Series, label: str) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean = clean[clean > 0]
    if clean.empty:
        raise ValueError(f"price series is empty or invalid: {label}")
    clean = clean.sort_index()
    if clean.index.has_duplicates:
        raise ValueError(f"price series has duplicate sessions: {label}")
    return clean
