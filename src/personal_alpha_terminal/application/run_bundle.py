"""ROUND32 P0: immutable production run bundle with content-addressed storage.

Every formal daily run from ROUND32 onward persists every optimizer input so
that the exact formal target portfolio can be deterministically re-derived
later from data that was visible at the original PIT cutoff.

Design rules (binding):

* Immutability -- blobs are content-addressed by SHA-256 and never overwritten.
  The run manifest is written exactly once (``SEALED``); a second finalize
  with identical content is idempotent, anything else fails.
* No future rehydration -- replay reads ONLY persisted blobs.  It never calls
  a data provider, never downloads current prices, and never fills a missing
  input.  A missing input yields ``REPLAY_NOT_POSSIBLE_MISSING_ORIGINAL_INPUT``.
* Idempotency -- replay never appends predictions or outcomes.  Each replay
  writes one append-only occurrence record into the run's bundle directory.
* Determinism -- replay re-runs the same ``PortfolioConstructionEngine`` with
  the persisted authorization, alpha signals, risk estimate, constraints, cost
  model, current weights, portfolio value, decision time and risk budget, and
  compares every acceptance metric with a recorded strict tolerance.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig, TransactionCostModel
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
    PortfolioTarget,
)
from personal_alpha_terminal.quant_engine.production_pipeline import DailyQuantInput
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
    RegimeRiskInput,
    RiskBudget,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    RiskModelEstimate,
    RiskModelStatus,
    SizeExposureStatus,
)
from personal_alpha_terminal.research.data_gate import (
    GateDecision,
    GateStatus,
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataRequest,
    ResearchPurpose,
)

BUNDLE_SCHEMA_VERSION = "run-bundle-v1"
REPLAY_OCCURRENCE_SCHEMA = "replay-occurrence-v1"

REPLAY_PASS = "REPLAY_PASS"
REPLAY_FAIL = "REPLAY_FAIL"
REPLAY_NOT_POSSIBLE = "REPLAY_NOT_POSSIBLE_MISSING_ORIGINAL_INPUT"

# Strict but realistic tolerances.  The replay re-runs the same deterministic
# SLSQP path; cross-platform float drift is bounded far below these values.
WEIGHT_ABS_TOL = 1e-9
AGGREGATE_REL_TOL = 1e-6
COUNT_TOL = 0


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _as_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _iso(value: datetime) -> str:
    return value.isoformat() if value.tzinfo is not None else value.replace(tzinfo=UTC).isoformat()


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


class ContentAddressedBlobStore:
    """Immutable blob store keyed by SHA-256 content hash.

    Writes are atomic (temp file + ``os.replace``) and never overwrite an
    existing blob.  Identical content deduplicates to the same digest.
    """

    def __init__(self, root: Path) -> None:
        self.root = root / "blobs"

    def put_bytes(self, data: bytes) -> str:
        digest = _hash_bytes(data)
        target = self.root / digest
        if target.exists():
            return digest
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".tmp-{uuid4().hex}"
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return digest

    def put_json(self, payload: dict[str, object]) -> str:
        return self.put_bytes(_canonical_json(payload))

    def put_array(self, array: np.ndarray) -> str:
        buffer = BytesIO()
        np.save(buffer, array, allow_pickle=False)
        return self.put_bytes(buffer.getvalue())

    def has(self, digest: str) -> bool:
        return (self.root / digest).is_file()

    def read_bytes(self, digest: str) -> bytes:
        path = self.root / digest
        if not path.is_file():
            raise FileNotFoundError(f"bundle blob missing: {digest}")
        return path.read_bytes()

    def read_json(self, digest: str) -> dict[str, object]:
        payload = json.loads(self.read_bytes(digest).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"bundle blob is not a JSON object: {digest}")
        return payload

    def read_array(self, digest: str) -> np.ndarray:
        buffer = BytesIO(self.read_bytes(digest))
        return np.asarray(np.load(buffer, allow_pickle=False), dtype=float)

    def verify(self, digest: str) -> bool:
        try:
            return _hash_bytes(self.read_bytes(digest)) == digest
        except FileNotFoundError:
            return False


# ---------------------------------------------------------------------------
# Serialization helpers (deterministic, symmetric)
# ---------------------------------------------------------------------------

def serialize_authorization(authorization: ResearchDataAuthorization) -> dict[str, object]:
    request = authorization.request
    decision = authorization.decision
    evidence = authorization.evidence
    return {
        "authorization_id": authorization.authorization_id,
        "issued_at": _iso(authorization.issued_at),
        "request": {
            "purpose": request.purpose.value,
            "market": request.market,
            "asset_type": request.asset_type,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "decision_time": _iso(request.decision_time),
            "adjustment_mode": request.adjustment_mode,
            "universe_snapshot_id": request.universe_snapshot_id,
            "maximum_age_seconds": request.maximum_age.total_seconds(),
        },
        "decision": {
            "status": decision.status.value,
            "purpose": decision.purpose.value,
            "blockers": list(decision.blockers),
            "warnings": list(decision.warnings),
            "allowed_actions": list(decision.allowed_actions),
            "evidence_fingerprint": decision.evidence_fingerprint,
            "evaluated_at": _iso(decision.evaluated_at),
        },
        "evidence": None
        if evidence is None
        else {
            "market": evidence.market,
            "asset_type": evidence.asset_type,
            "quality_status": evidence.quality_status,
            "source": evidence.source,
            "provider": evidence.provider,
            "source_ids": list(evidence.source_ids),
            "latest_available_time": _iso(evidence.latest_available_time)
            if evidence.latest_available_time is not None
            else None,
            "point_in_time_status": evidence.point_in_time_status,
            "adjustment_mode": evidence.adjustment_mode,
            "universe_snapshot_id": evidence.universe_snapshot_id,
            "universe_available_time": _iso(evidence.universe_available_time)
            if evidence.universe_available_time is not None
            else None,
            "corporate_actions_complete": evidence.corporate_actions_complete,
            "trading_calendar_complete": evidence.trading_calendar_complete,
            "missing_rate": evidence.missing_rate,
            "anomaly_rate": evidence.anomaly_rate,
            "maximum_missing_rate": evidence.maximum_missing_rate,
            "maximum_anomaly_rate": evidence.maximum_anomaly_rate,
            "data_version": evidence.data_version,
            "allow_backtest": evidence.allow_backtest,
            "allow_display": evidence.allow_display,
            "allow_portfolio_decision": evidence.allow_portfolio_decision,
            "dual_source_verified": evidence.dual_source_verified,
            "source_conflict": evidence.source_conflict,
            "fundamentals_vintage_complete": evidence.fundamentals_vintage_complete,
            "earnings_vintage_complete": evidence.earnings_vintage_complete,
        },
    }


def deserialize_authorization(payload: dict[str, object]) -> ResearchDataAuthorization:
    request_raw = _as_dict(payload.get("request"))
    decision_raw = _as_dict(payload.get("decision"))
    evidence_raw = payload.get("evidence")
    request = ResearchDataRequest(
        purpose=ResearchPurpose(_as_text(request_raw.get("purpose"), "portfolio_decision")),
        market=_as_text(request_raw.get("market")),
        asset_type=_as_text(request_raw.get("asset_type")),
        start_date=date.fromisoformat(_as_text(request_raw.get("start_date"))),
        end_date=date.fromisoformat(_as_text(request_raw.get("end_date"))),
        decision_time=_require_utc(_as_utc(_as_text(request_raw.get("decision_time")))),
        adjustment_mode=_as_text(request_raw.get("adjustment_mode")),
        universe_snapshot_id=_as_optional_text(request_raw.get("universe_snapshot_id")),
        maximum_age=timedelta(
            seconds=_as_float_strict(request_raw.get("maximum_age_seconds"), "maximum_age_seconds")
        ),
    )
    decision = GateDecision(
        status=GateStatus(_as_text(decision_raw.get("status"), "APPROVED")),
        purpose=ResearchPurpose(_as_text(decision_raw.get("purpose"), "portfolio_decision")),
        blockers=tuple(_as_text(item, "") for item in _list(decision_raw.get("blockers"))),
        warnings=tuple(_as_text(item, "") for item in _list(decision_raw.get("warnings"))),
        allowed_actions=tuple(
            _as_text(item, "") for item in _list(decision_raw.get("allowed_actions"))
        ),
        evidence_fingerprint=_as_text(decision_raw.get("evidence_fingerprint")),
        evaluated_at=_require_utc(_as_utc(_as_text(decision_raw.get("evaluated_at")))),
    )
    evidence: ResearchDataEvidence | None = None
    if isinstance(evidence_raw, dict):
        evidence = ResearchDataEvidence(
            market=_as_text(evidence_raw.get("market")),
            asset_type=_as_text(evidence_raw.get("asset_type")),
            quality_status=_as_text(evidence_raw.get("quality_status")),
            source=_as_text(evidence_raw.get("source")),
            provider=_as_text(evidence_raw.get("provider")),
            source_ids=tuple(
                _as_text(item, "") for item in _list(evidence_raw.get("source_ids"))
            ),
            latest_available_time=_as_utc(
                _as_optional_text(evidence_raw.get("latest_available_time"))
            ),
            point_in_time_status=_as_text(evidence_raw.get("point_in_time_status")),
            adjustment_mode=_as_text(evidence_raw.get("adjustment_mode")),
            universe_snapshot_id=_as_optional_text(evidence_raw.get("universe_snapshot_id")),
            universe_available_time=_as_utc(
                _as_optional_text(evidence_raw.get("universe_available_time"))
            ),
            corporate_actions_complete=bool(evidence_raw.get("corporate_actions_complete", False)),
            trading_calendar_complete=bool(evidence_raw.get("trading_calendar_complete", False)),
            missing_rate=_as_optional_float(evidence_raw.get("missing_rate")),
            anomaly_rate=_as_optional_float(evidence_raw.get("anomaly_rate")),
            maximum_missing_rate=float(evidence_raw.get("maximum_missing_rate", 1.0)),
            maximum_anomaly_rate=float(evidence_raw.get("maximum_anomaly_rate", 1.0)),
            data_version=_as_text(evidence_raw.get("data_version")),
            allow_backtest=bool(evidence_raw.get("allow_backtest", False)),
            allow_display=bool(evidence_raw.get("allow_display", False)),
            allow_portfolio_decision=bool(evidence_raw.get("allow_portfolio_decision", False)),
            dual_source_verified=bool(evidence_raw.get("dual_source_verified", False)),
            source_conflict=bool(evidence_raw.get("source_conflict", False)),
            fundamentals_vintage_complete=bool(
                evidence_raw.get("fundamentals_vintage_complete", False)
            ),
            earnings_vintage_complete=bool(evidence_raw.get("earnings_vintage_complete", False)),
        )
    return ResearchDataAuthorization(
        decision=decision,
        request=request,
        issued_at=_require_utc(_as_utc(_as_text(payload.get("issued_at")))),
        authorization_id=_as_text(payload.get("authorization_id")),
        evidence=evidence,
    )


def serialize_alpha_signals(signals: tuple[AlphaSignal, ...]) -> dict[str, object]:
    return {
        "count": len(signals),
        "signals": [
            {
                "symbol": item.symbol,
                "as_of": _iso(item.as_of),
                "signal_type": item.signal_type,
                "expected_excess_return": item.expected_excess_return,
                "horizon": item.horizon,
                "raw_signal": item.raw_signal,
                "normalized_signal": item.normalized_signal,
                "confidence": item.confidence,
                "confidence_calibrated": item.confidence_calibrated,
                "sample_size": item.sample_size,
                "statistical_strength": item.statistical_strength,
                "economic_strength": item.economic_strength,
                "decay_half_life": item.decay_half_life,
                "valid_until": _iso(item.valid_until),
                "data_quality": item.data_quality.value,
                "pit_valid": item.pit_valid,
                "validation_status": item.validation_status.value,
                "model_version": item.model_version,
                "data_version": item.data_version,
                "evidence_coverage": item.evidence_coverage,
                "calibration_id": item.calibration_id,
                "operational_approval_hash": item.operational_approval_hash,
            }
            for item in signals
        ],
    }


def deserialize_alpha_signals(payload: dict[str, object]) -> tuple[AlphaSignal, ...]:
    rows = payload.get("signals")
    if not isinstance(rows, list):
        return ()
    output: list[AlphaSignal] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        output.append(
            AlphaSignal(
                symbol=_as_text(row.get("symbol")),
                as_of=_require_utc(_as_utc(_as_text(row.get("as_of")))),
                signal_type=_as_text(row.get("signal_type")),
                expected_excess_return=float(row.get("expected_excess_return", 0.0)),
                horizon=int(row.get("horizon", 21)),
                raw_signal=float(row.get("raw_signal", 0.0)),
                normalized_signal=float(row.get("normalized_signal", 0.0)),
                confidence=float(row.get("confidence", 0.0)),
                confidence_calibrated=bool(row.get("confidence_calibrated", False)),
                sample_size=int(row.get("sample_size", 0)),
                statistical_strength=float(row.get("statistical_strength", 0.0)),
                economic_strength=float(row.get("economic_strength", 0.0)),
                decay_half_life=_as_optional_float(row.get("decay_half_life")),
                valid_until=_require_utc(_as_utc(_as_text(row.get("valid_until")))),
                data_quality=AlphaDataQuality(_as_text(row.get("data_quality"), "VALID")),
                pit_valid=bool(row.get("pit_valid", False)),
                validation_status=AlphaValidationStatus(
                    _as_text(row.get("validation_status"), "PRODUCTION_APPROVED")
                ),
                model_version=_as_text(row.get("model_version")),
                data_version=_as_text(row.get("data_version")),
                evidence_coverage=_as_float_strict(
                    row.get("evidence_coverage"), "evidence_coverage"
                ),
                calibration_id=_as_optional_text(row.get("calibration_id")),
                operational_approval_hash=_as_optional_text(
                    row.get("operational_approval_hash")
                ),
            )
        )
    return tuple(output)


def serialize_risk_metadata(metadata: tuple[AssetRiskMetadata, ...]) -> dict[str, object]:
    return {
        "count": len(metadata),
        "items": [
            {
                "symbol": item.symbol,
                "sector": item.sector,
                "average_daily_dollar_volume": item.average_daily_dollar_volume,
                "size_score": item.size_score,
                "market_cap": item.market_cap,
            }
            for item in metadata
        ],
    }


def deserialize_risk_metadata(payload: dict[str, object]) -> tuple[AssetRiskMetadata, ...]:
    rows = payload.get("items")
    if not isinstance(rows, list):
        return ()
    output: list[AssetRiskMetadata] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        output.append(
            AssetRiskMetadata(
                symbol=_as_text(row.get("symbol")),
                sector=_as_text(row.get("sector")),
                average_daily_dollar_volume=float(
                    row.get("average_daily_dollar_volume", 0.0)
                ),
                size_score=_as_optional_float(row.get("size_score")),
                market_cap=_as_optional_float(row.get("market_cap")),
            )
        )
    return tuple(output)


def serialize_regime(regime: RegimeRiskInput | None) -> dict[str, object] | None:
    if regime is None:
        return None
    return {
        "risk_on_probability": regime.risk_on_probability,
        "neutral_probability": regime.neutral_probability,
        "risk_off_probability": regime.risk_off_probability,
        "confidence": regime.confidence,
        "calibrated": regime.calibrated,
        "model_version": regime.model_version,
    }


def deserialize_regime(payload: object) -> RegimeRiskInput | None:
    if not isinstance(payload, dict):
        return None
    return RegimeRiskInput(
        risk_on_probability=float(payload.get("risk_on_probability", 0.0)),
        neutral_probability=float(payload.get("neutral_probability", 0.0)),
        risk_off_probability=float(payload.get("risk_off_probability", 0.0)),
        confidence=float(payload.get("confidence", 0.0)),
        calibrated=bool(payload.get("calibrated", False)),
        model_version=_as_text(payload.get("model_version")),
    )


def serialize_risk_state(state: PortfolioRiskState) -> dict[str, object]:
    return {
        "current_drawdown": state.current_drawdown,
        "rolling_volatility": state.rolling_volatility,
        "portfolio_beta": state.portfolio_beta,
        "concentration_hhi": state.concentration_hhi,
        "average_correlation": state.average_correlation,
        "baseline_average_correlation": state.baseline_average_correlation,
        "correlation_status": state.correlation_status.value,
        "correlation_recent_window": state.correlation_recent_window,
        "correlation_baseline_window": state.correlation_baseline_window,
        "correlation_recent_samples": state.correlation_recent_samples,
        "correlation_baseline_samples": state.correlation_baseline_samples,
    }


def deserialize_risk_state(payload: dict[str, object]) -> PortfolioRiskState:
    return PortfolioRiskState(
        current_drawdown=_as_float_strict(payload.get("current_drawdown"), "current_drawdown"),
        rolling_volatility=_as_float_strict(
            payload.get("rolling_volatility"), "rolling_volatility"
        ),
        portfolio_beta=_as_float_strict(payload.get("portfolio_beta"), "portfolio_beta"),
        concentration_hhi=_as_float_strict(
            payload.get("concentration_hhi"), "concentration_hhi"
        ),
        average_correlation=_as_optional_float(payload.get("average_correlation")),
        baseline_average_correlation=_as_optional_float(
            payload.get("baseline_average_correlation")
        ),
        correlation_status=CorrelationRiskStatus(
            _as_text(payload.get("correlation_status"), "NOT_VALIDATED")
        ),
        correlation_recent_window=_as_int_strict(
            payload.get("correlation_recent_window"), "correlation_recent_window"
        ),
        correlation_baseline_window=_as_int_strict(
            payload.get("correlation_baseline_window"), "correlation_baseline_window"
        ),
        correlation_recent_samples=_as_int_strict(
            payload.get("correlation_recent_samples"), "correlation_recent_samples"
        ),
        correlation_baseline_samples=_as_int_strict(
            payload.get("correlation_baseline_samples"), "correlation_baseline_samples"
        ),
    )


def serialize_risk_budget(budget: RiskBudget) -> dict[str, object]:
    return {
        "gross_exposure_multiplier": budget.gross_exposure_multiplier,
        "volatility_multiplier": budget.volatility_multiplier,
        "position_cap_multiplier": budget.position_cap_multiplier,
        "allow_new_risk": budget.allow_new_risk,
        "reasons": list(budget.reasons),
    }


def deserialize_risk_budget(payload: dict[str, object]) -> RiskBudget:
    return RiskBudget(
        gross_exposure_multiplier=_as_float_strict(
            payload.get("gross_exposure_multiplier"), "gross_exposure_multiplier"
        ),
        volatility_multiplier=_as_float_strict(
            payload.get("volatility_multiplier"), "volatility_multiplier"
        ),
        position_cap_multiplier=_as_float_strict(
            payload.get("position_cap_multiplier"), "position_cap_multiplier"
        ),
        allow_new_risk=bool(payload.get("allow_new_risk", False)),
        reasons=tuple(_as_text(item, "") for item in _list(payload.get("reasons"))),
    )


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_text(value: object, fallback: str = "UNAVAILABLE") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _as_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _as_float_strict(value: object, name: str) -> float:
    """Strict float parse for persisted decision inputs (fail-closed)."""

    if value is None:
        raise ValueError(f"persisted bundle is missing required numeric field: {name}")
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"persisted bundle contains a malformed numeric field: {name}")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"persisted bundle contains a malformed numeric field: {name}"
        ) from None


def _as_int_strict(value: object, name: str) -> int:
    """Strict integer parse for persisted decision inputs (fail-closed)."""

    if value is None:
        raise ValueError(f"persisted bundle is missing required integer field: {name}")
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"persisted bundle contains a malformed integer field: {name}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"persisted bundle contains a malformed integer field: {name}"
        ) from None


def _as_float_dict_strict(value: object, name: str) -> dict[str, float]:
    """Strict float-map parse for persisted risk inputs (fail-closed)."""

    raw = value if isinstance(value, dict) else None
    if raw is None:
        raise ValueError(f"persisted bundle is missing required map: {name}")
    return {
        str(key): _as_float_strict(item, f"{name}:{key}")
        for key, item in raw.items()
    }


def _as_str_dict_strict(value: object, name: str) -> dict[str, str]:
    """Strict string-map parse for persisted risk inputs (fail-closed)."""

    raw = value if isinstance(value, dict) else None
    if raw is None:
        raise ValueError(f"persisted bundle is missing required map: {name}")
    output: dict[str, str] = {}
    for key, item in raw.items():
        text = _as_text(item)
        if text == "UNAVAILABLE" and item is not None:
            raise ValueError(f"persisted bundle has a malformed string map entry: {name}:{key}")
        output[str(key)] = text
    return output


def _require_utc(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("persisted bundle is missing a required timestamp")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _serialize_returns_frame(frame: pd.DataFrame) -> dict[str, object]:
    values = frame.to_numpy(dtype=float)
    columns = [str(column) for column in frame.columns]
    index = [item.isoformat() for item in frame.index]
    return {
        "columns": columns,
        "index": index,
        "shape": [int(values.shape[0]), int(values.shape[1])],
        "values": values.tolist(),
    }


def _deserialize_returns_frame(payload: dict[str, object]) -> pd.DataFrame:
    columns = [_as_text(item, "") for item in _list(payload.get("columns"))]
    index = [
        datetime.fromisoformat(cast(str, item)) for item in _list(payload.get("index"))
    ]
    raw = payload.get("values")
    if not isinstance(raw, list):
        raise ValueError("persisted returns values are missing")
    frame = pd.DataFrame(raw, index=index, columns=columns, dtype=float)
    return frame


# ---------------------------------------------------------------------------
# Run bundle manifest
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RunBundleManifest:
    schema_version: str
    run_id: str
    decision_id: str
    created_at: str
    analysis_date: str
    decision_cutoff: str
    trade_date: str
    decision_manifest_semantic_hash: str
    status: str
    sections: dict[str, dict[str, object]]
    blob_digests: dict[str, str]
    bundle_hash: str

    def document(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "created_at": self.created_at,
            "analysis_date": self.analysis_date,
            "decision_cutoff": self.decision_cutoff,
            "trade_date": self.trade_date,
            "decision_manifest_semantic_hash": self.decision_manifest_semantic_hash,
            "status": self.status,
            "sections": self.sections,
            "blob_digests": self.blob_digests,
            "bundle_hash": self.bundle_hash,
        }


@dataclass(frozen=True, slots=True)
class ReconstructedBundleInputs:
    """Typed reconstruction of the frozen optimizer inputs from the bundle."""

    inputs: DailyQuantInput
    constraints: PortfolioConstraints
    cost_model: TransactionCostModel
    risk_budget: RiskBudget
    risk: RiskModelEstimate
    operational_mode: bool
    decision_time: datetime
    portfolio_value: float
    current_weights: dict[str, float]


class RunBundleStore:
    """File layout for run bundles under ``<root>/<run_id>/``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs = ContentAddressedBlobStore(root)

    def bundle_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def manifest_path(self, run_id: str) -> Path:
        return self.bundle_dir(run_id) / "run_manifest.json"

    def occurrences_path(self, run_id: str) -> Path:
        return self.bundle_dir(run_id) / "replay_occurrences.jsonl"

    def load_manifest(self, run_id: str) -> dict[str, object]:
        path = self.manifest_path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"run bundle manifest missing: {run_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"run bundle manifest is invalid: {run_id}")
        return payload

    def list_run_ids(self) -> tuple[str, ...]:
        if not self.root.is_dir():
            return ()
        output: list[str] = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and (child / "run_manifest.json").is_file():
                output.append(child.name)
        return tuple(output)


def _section(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {"name": name, **payload}


def build_input_sections(
    *,
    inputs: DailyQuantInput,
    risk: RiskModelEstimate | None,
    target: PortfolioTarget | None,
    constraints: PortfolioConstraints,
    cost_model: TransactionCostModel,
    risk_budget: RiskBudget,
    operational_mode: bool,
    store: ContentAddressedBlobStore,
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """Write every optimizer input as immutable blobs and return sections."""

    sections: dict[str, dict[str, object]] = {}
    digests: dict[str, str] = {}

    # Universe -------------------------------------------------------------
    universe_symbols = list(risk.symbols) if risk is not None else list(inputs.current_weights)
    universe_payload: dict[str, object] = {
        "decision_timestamp": _iso(inputs.decision_time),
        "pit_cutoff": _iso(inputs.decision_time),
        "universe_snapshot_id": _as_text(inputs.universe_snapshot_id, "UNAVAILABLE"),
        "data_quality": _as_text(inputs.data_quality, "UNAVAILABLE"),
        "pit_valid": bool(inputs.pit_valid),
        "symbols": universe_symbols,
        "eligibility": {
            "current_weights_symbols": sorted(inputs.current_weights),
            "alpha_signal_count": len(inputs.alpha_signals),
            "risk_estimate_symbols": len(risk.symbols) if risk is not None else 0,
        },
        "exclusions": [],
        "exclusion_reasons": {},
    }
    digests["universe"] = store.put_json(universe_payload)
    digests["authorization"] = store.put_json(serialize_authorization(inputs.authorization))
    sections["universe"] = _section(
        "universe",
        {
            "snapshot_id": _as_text(inputs.universe_snapshot_id, "UNAVAILABLE"),
            "pit_valid": bool(inputs.pit_valid),
            "data_quality": _as_text(inputs.data_quality, "UNAVAILABLE"),
            "symbol_count": len(universe_symbols),
            "blob": digests["universe"],
        },
    )
    sections["authorization"] = _section(
        "authorization",
        {
            "authorization_id": inputs.authorization.authorization_id,
            "purpose": inputs.authorization.request.purpose.value,
            "gate_status": inputs.authorization.decision.status.value,
            "blob": digests["authorization"],
        },
    )

    # Features / factors ---------------------------------------------------
    digests["alpha_signals"] = store.put_json(serialize_alpha_signals(inputs.alpha_signals))
    sections["alpha"] = _section(
        "alpha",
        {
            "signal_count": len(inputs.alpha_signals),
            "signal_type": _as_text(inputs.alpha_signals[0].signal_type)
            if inputs.alpha_signals
            else "UNAVAILABLE",
            "blob": digests["alpha_signals"],
        },
    )

    # Risk -----------------------------------------------------------------
    risk_payload: dict[str, object] = {
        "returns_window_identity": {
            "observations": int(inputs.returns.shape[0]),
            "symbols": int(inputs.returns.shape[1]),
            "first_observation": (
                _iso(inputs.returns.index[0]) if len(inputs.returns.index) else None
            ),
            "last_observation": (
                _iso(inputs.returns.index[-1]) if len(inputs.returns.index) else None
            ),
            "data_version": _as_text(inputs.alpha_signals[0].data_version)
            if inputs.alpha_signals
            else "UNAVAILABLE",
        },
        "benchmark_dates": [
            item.isoformat() for item in inputs.benchmark_returns.index
        ],
    }
    digests["returns"] = store.put_json(_serialize_returns_frame(inputs.returns))
    benchmark_payload: dict[str, object] = {
        "values": inputs.benchmark_returns.to_numpy(dtype=float).tolist(),
        "index": [item.isoformat() for item in inputs.benchmark_returns.index],
    }
    digests["benchmark_returns"] = store.put_json(benchmark_payload)
    digests["risk_metadata"] = store.put_json(
        serialize_risk_metadata(inputs.risk_metadata)
    )
    if risk is not None:
        digests["covariance"] = store.put_array(np.asarray(risk.annualized_covariance))
        digests["correlation"] = store.put_array(np.asarray(risk.correlation))
        risk_payload["symbols"] = list(risk.symbols)
        risk_payload["model_version"] = risk.model_version
        risk_payload["status"] = risk.status.value
        risk_payload["observations"] = int(risk.observations)
        risk_payload["condition_number"] = float(risk.condition_number)
        risk_payload["shrinkage"] = float(risk.shrinkage)
        risk_payload["limitations"] = list(risk.limitations)
        risk_payload["size_exposure_status"] = risk.size_exposure_status.value
        risk_payload["annualized_volatility"] = risk.annualized_volatility
        risk_payload["beta"] = risk.beta
        risk_payload["sectors"] = risk.sectors
        risk_payload["average_daily_dollar_volume"] = risk.average_daily_dollar_volume
        risk_payload["size_scores"] = risk.size_scores
        risk_payload["market_caps"] = risk.market_caps
    digests["risk"] = store.put_json(risk_payload)
    sections["risk"] = _section(
        "risk",
        {
            "model_version": _as_text(risk.model_version) if risk is not None else "UNAVAILABLE",
            "status": _as_text(risk.status.value) if risk is not None else "UNAVAILABLE",
            "observations": int(risk.observations) if risk is not None else 0,
            "returns_window": risk_payload["returns_window_identity"],
            "covariance_blob": digests.get("covariance", "UNAVAILABLE"),
            "correlation_blob": digests.get("correlation", "UNAVAILABLE"),
            "returns_blob": digests["returns"],
            "benchmark_returns_blob": digests["benchmark_returns"],
            "risk_metadata_blob": digests["risk_metadata"],
            "risk_summary_blob": digests["risk"],
        },
    )

    # Liquidity ------------------------------------------------------------
    participation = cost_model.config.maximum_adv_participation
    liquidity_rows: dict[str, object] = {}
    if risk is not None:
        for symbol in risk.symbols:
            adv = risk.average_daily_dollar_volume.get(symbol, 0.0)
            max_tradable = adv * participation / max(1.0, float(inputs.portfolio_value))
            liquidity_rows[symbol] = {
                "adv": adv,
                "price": None,
                "liquidity_eligible": adv > 0,
                "participation_assumption": participation,
                "max_tradable_weight": max_tradable,
                "source_timestamp": _iso(inputs.decision_time),
            }
    digests["liquidity"] = store.put_json({"rows": liquidity_rows})
    sections["liquidity"] = _section(
        "liquidity",
        {
            "symbol_count": len(liquidity_rows),
            "participation_assumption": participation,
            "source_timestamp": _iso(inputs.decision_time),
            "blob": digests["liquidity"],
        },
    )

    # Cost -----------------------------------------------------------------
    digests["cost"] = store.put_json(_serialize_cost_config(cost_model.config))
    sections["cost"] = _section(
        "cost",
        {
            "model_version": _as_text(cost_model.config.version, "UNAVAILABLE"),
            "blob": digests["cost"],
        },
    )

    # Constraints ----------------------------------------------------------
    digests["constraints"] = store.put_json(asdict(constraints))
    sections["constraints"] = _section(
        "constraints",
        {
            "model_version": _as_text(constraints.model_version, "UNAVAILABLE"),
            "blob": digests["constraints"],
        },
    )

    # Portfolio ------------------------------------------------------------
    portfolio_payload: dict[str, object] = {
        "current_weights": inputs.current_weights,
        "portfolio_value": float(inputs.portfolio_value),
        "operational_mode": bool(operational_mode),
        "risk_state": serialize_risk_state(inputs.portfolio_risk_state),
        "regime": serialize_regime(inputs.regime),
        "risk_budget": serialize_risk_budget(risk_budget),
        "decision_time": _iso(inputs.decision_time),
        "target_symbols": sorted(target.target_weights) if target is not None else [],
        "target_weights": target.target_weights if target is not None else {},
        "raw_target_weights": target.raw_target_weights if target is not None else None,
        "cash_weight": float(target.cash_weight) if target is not None else 1.0,
        "expected_alpha": float(target.expected_alpha) if target is not None else 0.0,
        "expected_volatility": (
            float(target.expected_volatility)
            if target is not None and target.expected_volatility is not None
            else None
        ),
        "expected_beta": (
            float(target.expected_beta)
            if target is not None and target.expected_beta is not None
            else None
        ),
        "turnover": float(target.turnover) if target is not None else 0.0,
        "estimated_transaction_cost": (
            float(target.estimated_transaction_cost) if target is not None else 0.0
        ),
        "hhi": float(target.hhi) if target is not None else 0.0,
        "sector_weights": target.sector_weights if target is not None else {},
        "cluster_weights": target.cluster_weights if target is not None else {},
        "alpha_contributions": [
            asdict(item)
            for item in (target.alpha_contributions if target is not None else ())
        ],
        "risk_reductions": list(target.risk_reductions) if target is not None else [],
        "blockers": list(target.blockers) if target is not None else [],
        "status": _as_text(target.status.value) if target is not None else "UNAVAILABLE",
        "model_version": _as_text(target.model_version) if target is not None else "UNAVAILABLE",
        "risk_model_version": (
            _as_text(target.risk_model_version) if target is not None else "UNAVAILABLE"
        ),
        "cost_model_version": (
            _as_text(target.cost_model_version) if target is not None else "UNAVAILABLE"
        ),
        "model_validation_id": (
            _as_text(target.model_validation_id, "") if target is not None else ""
        ),
        "optimizer_provenance": target.optimizer_provenance if target is not None else None,
    }
    digests["portfolio"] = store.put_json(portfolio_payload)
    sections["portfolio"] = _section(
        "portfolio",
        {
            "portfolio_value": float(inputs.portfolio_value),
            "current_holding_count": len(inputs.current_weights),
            "blob": digests["portfolio"],
        },
    )

    return sections, digests


def _serialize_cost_config(config: TransactionCostConfig) -> dict[str, object]:
    return asdict(config)


def stage_run_bundle(
    *,
    store: RunBundleStore,
    run_id: str,
    decision_id: str,
    created_at: datetime,
    analysis_date: str,
    decision_cutoff: datetime,
    trade_date: str,
    inputs: DailyQuantInput,
    risk: RiskModelEstimate | None,
    target: PortfolioTarget | None,
    constraints: PortfolioConstraints,
    cost_model: TransactionCostModel,
    risk_budget: RiskBudget,
    operational_mode: bool,
) -> dict[str, object]:
    """Write input blobs and a STAGED manifest for a formal run.

    The orchestrator later calls :func:`finalize_run_bundle` once the
    DecisionManifest has been sealed, turning the bundle immutable.
    """

    sections, digests = build_input_sections(
        inputs=inputs,
        risk=risk,
        target=target,
        constraints=constraints,
        cost_model=cost_model,
        risk_budget=risk_budget,
        operational_mode=operational_mode,
        store=store.blobs,
    )
    manifest: dict[str, object] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "run_id": run_id,
        "decision_id": decision_id,
        "created_at": _iso(created_at),
        "analysis_date": analysis_date,
        "decision_cutoff": _iso(decision_cutoff),
        "trade_date": trade_date,
        "decision_manifest_semantic_hash": "PENDING",
        "status": "STAGED",
        "sections": sections,
        "blob_digests": digests,
        "bundle_hash": "PENDING",
    }
    canonical = _canonical_json(manifest)
    manifest["bundle_hash"] = _hash_bytes(canonical)
    bundle_dir = store.bundle_dir(run_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = store.manifest_path(run_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("status") != "STAGED":
            raise RuntimeError(f"run bundle already sealed: {run_id}")
    temporary = bundle_dir / f".manifest-{uuid4().hex}"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return {
        "status": "STAGED",
        "run_id": run_id,
        "manifest_path": str(path),
        "blob_count": len(digests),
        "sections": sorted(sections),
    }


def finalize_run_bundle(
    *,
    store: RunBundleStore,
    run_id: str,
    decision_manifest: dict[str, object] | None,
) -> dict[str, object]:
    """Seal a staged bundle with the sealed DecisionManifest hash.

    Idempotent for identical content; otherwise refuses to mutate a sealed
    bundle (immutability invariant).
    """

    path = store.manifest_path(run_id)
    if not path.is_file():
        raise FileNotFoundError(f"staged run bundle missing for finalize: {run_id}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"invalid run bundle manifest: {run_id}")
    if manifest.get("status") == "SEALED":
        return {"status": "ALREADY_SEALED", "run_id": run_id}
    if manifest.get("status") != "STAGED":
        raise RuntimeError(f"run bundle cannot be finalized from {manifest.get('status')!r}")
    semantic_hash = _as_text(
        (decision_manifest or {}).get("semantic_hash"),
        "UNAVAILABLE",
    )
    manifest["decision_manifest_semantic_hash"] = semantic_hash
    manifest["status"] = "SEALED"
    canonical = _canonical_json(manifest)
    manifest["bundle_hash"] = _hash_bytes(canonical)
    temporary = path.with_name(f".manifest-{uuid4().hex}")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return {
        "status": "SEALED",
        "run_id": run_id,
        "bundle_hash": manifest["bundle_hash"],
        "decision_manifest_semantic_hash": semantic_hash,
    }


def verify_bundle_integrity(
    *,
    store: RunBundleStore,
    run_id: str,
) -> dict[str, object]:
    """Verify every referenced blob exists and hashes to its digest."""

    manifest = store.load_manifest(run_id)
    digests_raw = manifest.get("blob_digests")
    digests = digests_raw if isinstance(digests_raw, dict) else {}
    failures: list[str] = []
    checked = 0
    for section, digest in sorted(digests.items()):
        if not isinstance(digest, str) or not digest:
            failures.append(f"{section}: missing digest")
            continue
        if not store.blobs.has(digest):
            failures.append(f"{section}: blob missing {digest}")
            continue
        if not store.blobs.verify(digest):
            failures.append(f"{section}: blob hash mismatch {digest}")
            continue
        checked += 1
    status = "INTEGRITY_PASS" if not failures else "INTEGRITY_FAIL"
    return {
        "status": status,
        "run_id": run_id,
        "blob_count": len(digests),
        "verified_blobs": checked,
        "failures": failures,
    }


def reconstruct_optimizer_inputs(
    *,
    store: RunBundleStore,
    run_id: str,
) -> tuple[ReconstructedBundleInputs, dict[str, object]]:
    """Rebuild the frozen optimizer inputs from persisted blobs.

    Raises ``FileNotFoundError``/``ValueError`` for any missing original input.
    """

    manifest = store.load_manifest(run_id)
    digests_raw = manifest.get("blob_digests")
    digests = digests_raw if isinstance(digests_raw, dict) else {}

    def _require(section: str) -> str:
        digest = digests.get(section)
        if not isinstance(digest, str) or not store.blobs.has(digest):
            raise FileNotFoundError(f"original input missing for section: {section}")
        return digest

    constraints = PortfolioConstraints(
        **cast(dict[str, Any], store.blobs.read_json(_require("constraints")))
    )
    cost_config = TransactionCostConfig(
        **cast(dict[str, Any], store.blobs.read_json(_require("cost")))
    )
    cost_model = TransactionCostModel(cost_config)
    signals = deserialize_alpha_signals(store.blobs.read_json(_require("alpha_signals")))
    risk_payload = store.blobs.read_json(_require("risk"))
    covariance = store.blobs.read_array(_require("covariance"))
    correlation = store.blobs.read_array(_require("correlation"))
    risk_metadata = deserialize_risk_metadata(
        store.blobs.read_json(_require("risk_metadata"))
    )
    returns = _deserialize_returns_frame(store.blobs.read_json(_require("returns")))
    benchmark_payload = store.blobs.read_json(_require("benchmark_returns"))
    benchmark_values = benchmark_payload.get("values")
    benchmark_index = benchmark_payload.get("index")
    if not isinstance(benchmark_values, list) or not isinstance(benchmark_index, list):
        raise ValueError("persisted benchmark returns are missing")
    benchmark_returns = pd.Series(
        [_as_float_strict(item, "benchmark_value") for item in benchmark_values],
        index=[
            datetime.fromisoformat(_as_text(item, "")) for item in benchmark_index
        ],
        dtype=float,
    )
    portfolio_payload = store.blobs.read_json(_require("portfolio"))
    current_weights_raw = portfolio_payload.get("current_weights")
    if not isinstance(current_weights_raw, dict):
        raise ValueError("persisted current weights are missing")
    current_weights = {
        str(key): _as_float_strict(value, f"current_weight:{key}")
        for key, value in current_weights_raw.items()
    }
    risk_budget = deserialize_risk_budget(
        _as_dict(portfolio_payload.get("risk_budget"))
    )
    symbols = tuple(_as_text(item, "") for item in _list(risk_payload.get("symbols", [])))
    if not symbols:
        symbols = tuple(current_weights)
    risk = RiskModelEstimate(
        symbols=symbols,
        annualized_covariance=covariance,
        correlation=correlation,
        annualized_volatility=_as_float_dict_strict(
            risk_payload.get("annualized_volatility"), "annualized_volatility"
        ),
        beta=_as_float_dict_strict(risk_payload.get("beta"), "beta"),
        sectors=_as_str_dict_strict(risk_payload.get("sectors"), "sectors"),
        average_daily_dollar_volume=_as_float_dict_strict(
            risk_payload.get("average_daily_dollar_volume"),
            "average_daily_dollar_volume",
        ),
        size_scores=_as_float_dict_strict(
            risk_payload.get("size_scores"), "size_scores"
        ),
        size_exposure_status=SizeExposureStatus(
            _as_text(risk_payload.get("size_exposure_status"), "NOT_VALIDATED")
        ),
        observations=_as_int_strict(risk_payload.get("observations"), "observations"),
        status=RiskModelStatus(_as_text(risk_payload.get("status"), "BLOCKED")),
        condition_number=_as_float_strict(
            risk_payload.get("condition_number"), "condition_number"
        ),
        shrinkage=_as_float_strict(risk_payload.get("shrinkage"), "shrinkage"),
        model_version=_as_text(risk_payload.get("model_version")),
        limitations=tuple(_as_text(item, "") for item in _list(risk_payload.get("limitations"))),
        market_caps=_as_float_dict_strict(risk_payload.get("market_caps"), "market_caps"),
    )
    authorization = deserialize_authorization(
        store.blobs.read_json(_require("authorization"))
    )
    decision_time = _require_utc(
        _as_utc(_as_text(portfolio_payload.get("decision_time")))
    )
    portfolio_value = _as_float_strict(
        portfolio_payload.get("portfolio_value"), "portfolio_value"
    )
    operational_mode = bool(portfolio_payload.get("operational_mode", False))
    recorded = {
        "target_symbols": sorted(
            _as_text(item, "") for item in _list(portfolio_payload.get("target_symbols"))
        ),
        "target_weights": _as_float_dict_strict(
            portfolio_payload.get("target_weights"), "target_weights"
        ),
        "cash_weight": _as_float_strict(
            portfolio_payload.get("cash_weight"), "cash_weight"
        ),
        "expected_alpha": _as_float_strict(
            portfolio_payload.get("expected_alpha"), "expected_alpha"
        ),
        "expected_volatility": _as_optional_float(
            portfolio_payload.get("expected_volatility")
        ),
        "expected_beta": _as_optional_float(portfolio_payload.get("expected_beta")),
        "turnover": _as_float_strict(portfolio_payload.get("turnover"), "turnover"),
        "estimated_transaction_cost": _as_float_strict(
            portfolio_payload.get("estimated_transaction_cost"),
            "estimated_transaction_cost",
        ),
        "hhi": _as_float_strict(portfolio_payload.get("hhi"), "hhi"),
        "status": _as_text(portfolio_payload.get("status"), "UNAVAILABLE"),
    }
    universe_section = _as_dict(_as_dict(manifest.get("sections", {})).get("universe", {}))
    inputs = DailyQuantInput(
        authorization=authorization,
        decision_time=decision_time,
        alpha_signals=signals,
        returns=returns,
        benchmark_returns=benchmark_returns,
        risk_metadata=risk_metadata,
        current_weights=current_weights,
        portfolio_value=portfolio_value,
        portfolio_risk_state=deserialize_risk_state(
            _as_dict(portfolio_payload.get("risk_state"))
        ),
        regime=deserialize_regime(portfolio_payload.get("regime")),
        pit_valid=bool(universe_section.get("pit_valid", False)),
        universe_snapshot_id=_as_optional_text(
            universe_section.get("snapshot_id")
        ),
        data_quality=_as_text(universe_section.get("data_quality"), "UNAVAILABLE"),
    )
    return ReconstructedBundleInputs(
        inputs=inputs,
        constraints=constraints,
        cost_model=cost_model,
        risk_budget=risk_budget,
        risk=risk,
        operational_mode=operational_mode,
        decision_time=decision_time,
        portfolio_value=portfolio_value,
        current_weights=current_weights,
    ), recorded


@dataclass(frozen=True, slots=True)
class ReplayMetric:
    name: str
    recorded: float | str | None
    replayed: float | str | None
    tolerance: str
    passed: bool


@dataclass(frozen=True, slots=True)
class RunBundleReplayReport:
    status: str
    run_id: str
    bundle_hash: str
    decision_manifest_semantic_hash: str
    replay_occurrence_id: str
    metrics: tuple[ReplayMetric, ...]
    detail: str

    def document(self) -> dict[str, object]:
        return {
            "status": self.status,
            "run_id": self.run_id,
            "bundle_hash": self.bundle_hash,
            "decision_manifest_semantic_hash": self.decision_manifest_semantic_hash,
            "replay_occurrence_id": self.replay_occurrence_id,
            "metrics": [
                {
                    "name": item.name,
                    "recorded": item.recorded,
                    "replayed": item.replayed,
                    "tolerance": item.tolerance,
                    "passed": item.passed,
                }
                for item in self.metrics
            ],
            "detail": self.detail,
        }


def replay_run_bundle(
    *,
    store: RunBundleStore,
    run_id: str,
    now: datetime | None = None,
) -> RunBundleReplayReport:
    """Deterministically re-derive the decision from the frozen bundle."""

    manifest = store.load_manifest(run_id)
    if manifest.get("status") != "SEALED":
        return RunBundleReplayReport(
            status="REPLAY_NOT_POSSIBLE_BUNDLE_NOT_SEALED",
            run_id=run_id,
            bundle_hash=_as_text(manifest.get("bundle_hash"), "UNAVAILABLE"),
            decision_manifest_semantic_hash=_as_text(
                manifest.get("decision_manifest_semantic_hash"), "UNAVAILABLE"
            ),
            replay_occurrence_id="",
            metrics=(),
            detail=f"bundle status is {manifest.get('status')!r}; replay requires SEALED",
        )
    occurrence_id = f"replay-{uuid4().hex}"
    try:
        rebuilt, recorded = reconstruct_optimizer_inputs(store=store, run_id=run_id)
    except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
        return RunBundleReplayReport(
            status=REPLAY_NOT_POSSIBLE,
            run_id=run_id,
            bundle_hash=_as_text(manifest.get("bundle_hash"), "UNAVAILABLE"),
            decision_manifest_semantic_hash=_as_text(
                manifest.get("decision_manifest_semantic_hash"), "UNAVAILABLE"
            ),
            replay_occurrence_id=occurrence_id,
            metrics=(),
            detail=f"missing or invalid original input: {error}",
        )

    inputs = rebuilt.inputs
    engine = PortfolioConstructionEngine(
        constraints=rebuilt.constraints,
        cost_model=rebuilt.cost_model,
        operational_mode=rebuilt.operational_mode,
    )
    target = engine.construct(
        authorization=inputs.authorization,
        alpha_signals=inputs.alpha_signals,
        risk=rebuilt.risk,
        current_weights=rebuilt.current_weights,
        portfolio_value=rebuilt.portfolio_value,
        decision_time=rebuilt.decision_time,
        risk_budget=rebuilt.risk_budget,
    )
    metrics = _compare_replay(recorded, target)
    passed = all(item.passed for item in metrics)
    status = REPLAY_PASS if passed else REPLAY_FAIL
    recorded_targets = _as_float_dict_strict(
        recorded.get("target_weights"), "target_weights"
    )
    symbol_union = set(target.target_weights) | set(recorded_targets)
    max_weight_delta = max(
        (
            abs(
                target.target_weights.get(symbol, 0.0)
                - recorded_targets.get(symbol, 0.0)
            )
            for symbol in symbol_union
        ),
        default=0.0,
    )
    _append_occurrence(
        store=store,
        run_id=run_id,
        occurrence={
            "schema_version": REPLAY_OCCURRENCE_SCHEMA,
            "occurrence_id": occurrence_id,
            "run_id": run_id,
            "replayed_at": _iso(now or datetime.now(UTC)),
            "status": status,
            "target_symbol_count": len(target.target_weights),
            "target_weight_max_delta": max_weight_delta,
        },
    )
    return RunBundleReplayReport(
        status=status,
        run_id=run_id,
        bundle_hash=_as_text(manifest.get("bundle_hash"), "UNAVAILABLE"),
        decision_manifest_semantic_hash=_as_text(
            manifest.get("decision_manifest_semantic_hash"), "UNAVAILABLE"
        ),
        replay_occurrence_id=occurrence_id,
        metrics=metrics,
        detail=(
            "replay reproduced the recorded decision within tolerance"
            if passed
            else "replay diverged from the recorded decision"
        ),
    )


def _compare_replay(
    recorded: dict[str, object],
    target: PortfolioTarget,
) -> tuple[ReplayMetric, ...]:
    recorded_targets = _as_float_dict_strict(
        recorded.get("target_weights"), "target_weights"
    )
    replayed_targets = dict(target.target_weights)
    weight_delta = 0.0
    for symbol in set(recorded_targets) | set(replayed_targets):
        weight_delta = max(
            weight_delta,
            abs(
                recorded_targets.get(symbol, 0.0)
                - replayed_targets.get(symbol, 0.0)
            ),
        )
    recorded_gross = sum(recorded_targets.values())
    replayed_gross = sum(replayed_targets.values())
    recorded_cash = _as_float_strict(recorded.get("cash_weight"), "cash_weight")
    recorded_hhi = _as_float_strict(recorded.get("hhi"), "hhi")
    recorded_turnover = _as_float_strict(recorded.get("turnover"), "turnover")
    recorded_cost = _as_float_strict(
        recorded.get("estimated_transaction_cost"), "estimated_transaction_cost"
    )
    recorded_alpha = _as_float_strict(recorded.get("expected_alpha"), "expected_alpha")
    return (
        ReplayMetric(
            "target_symbol_count",
            len(recorded_targets),
            len(replayed_targets),
            "exact",
            len(recorded_targets) == len(replayed_targets),
        ),
        ReplayMetric(
            "target_weight_max_delta",
            None,
            weight_delta,
            f"abs <= {WEIGHT_ABS_TOL}",
            weight_delta <= WEIGHT_ABS_TOL,
        ),
        ReplayMetric(
            "gross",
            recorded_gross,
            replayed_gross,
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_gross, replayed_gross),
        ),
        ReplayMetric(
            "cash_weight",
            recorded_cash,
            float(target.cash_weight),
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_cash, float(target.cash_weight)),
        ),
        ReplayMetric(
            "expected_volatility",
            _as_optional_float(recorded.get("expected_volatility")),
            target.expected_volatility,
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(
                _as_optional_float(recorded.get("expected_volatility")),
                target.expected_volatility,
            ),
        ),
        ReplayMetric(
            "hhi",
            recorded_hhi,
            float(target.hhi),
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_hhi, float(target.hhi)),
        ),
        ReplayMetric(
            "turnover",
            recorded_turnover,
            float(target.turnover),
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_turnover, float(target.turnover)),
        ),
        ReplayMetric(
            "estimated_transaction_cost",
            recorded_cost,
            float(target.estimated_transaction_cost),
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_cost, float(target.estimated_transaction_cost)),
        ),
        ReplayMetric(
            "expected_alpha",
            recorded_alpha,
            float(target.expected_alpha),
            f"rel <= {AGGREGATE_REL_TOL}",
            _rel_close(recorded_alpha, float(target.expected_alpha)),
        ),
    )


def _rel_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if abs(left - right) <= AGGREGATE_REL_TOL * max(1.0, abs(left), abs(right)):
        return True
    return bool(np.isclose(left, right, rtol=AGGREGATE_REL_TOL, atol=1e-12))


def _append_occurrence(
    *,
    store: RunBundleStore,
    run_id: str,
    occurrence: dict[str, object],
) -> None:
    path = store.occurrences_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(occurrence, sort_keys=True, ensure_ascii=False) + "\n")
