"""ROUND34 append-only real portfolio outcome ledger.

The ledger separates model target, accepted manual recommendation, actual
fill, actual holdings, and forward outcome.  No paper/simulated fill may be
written to this ledger.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

LEDGER_SCHEMA_VERSION = "round34-portfolio-outcome-ledger-v1"


def _hash(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PortfolioOutcomeObservation:
    observation_id: str
    portfolio_id: int
    decision_run_id: str
    run_bundle_id: str
    decision_time: datetime
    execution_session: date
    symbol: str
    target_weight: float | None
    pre_trade_weight: float | None
    recommended_quantity: int | None
    accepted_quantity: int | None
    actual_fill_quantity: int | None
    intended_price: float | None
    actual_fill_price: float | None
    commission: float
    spread_estimate: float | None
    realized_slippage: float | None
    cash_before: float | None
    cash_after: float | None
    position_before: float | None
    position_after: float | None
    nav_before: float | None
    nav_after: float | None
    benchmark_levels: dict[str, float]
    created_at: datetime
    provenance_hash: str
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


@dataclass(frozen=True, slots=True)
class PortfolioForwardOutcome:
    outcome_id: str
    observation_id: str
    maturity_sessions: int
    created_at: datetime
    target_date: date
    maturity_date: date
    matured: bool
    realized_return: float | None
    benchmark_return: float | None
    excess_return: float | None
    cost_adjusted_excess_return: float | None
    immutable_hash: str = ""

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["immutable_hash"] = self.immutable_hash or _hash(payload)
        return payload


class PortfolioOutcomeLedger:
    """Append-only JSONL portfolio outcome ledger."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("var/portfolio-outcome")

    @property
    def observations_path(self) -> Path:
        return self.root / "observations.jsonl"

    @property
    def outcomes_path(self) -> Path:
        return self.root / "outcomes.jsonl"

    @property
    def occurrences_path(self) -> Path:
        return self.root / "occurrences.jsonl"

    @property
    def canonical_index_path(self) -> Path:
        return self.root / "canonical-index.json"

    def append_observation(
        self,
        observation: PortfolioOutcomeObservation,
    ) -> bool:
        """Append a new observation or record an idempotent duplicate occurrence."""

        self.root.mkdir(parents=True, exist_ok=True)
        document = observation.document()
        observation_id = str(document["observation_id"])
        existing_ids = {
            str(row.get("observation_id"))
            for row in _read_jsonl(self.observations_path)
        }
        occurrence = {
            "observation_id": observation_id,
            "occurred_at": observation.created_at.isoformat(),
            "is_first_occurrence": observation_id not in existing_ids,
        }
        with self.occurrences_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    occurrence, ensure_ascii=False, sort_keys=True, default=str
                )
                + "\n"
            )
        if observation_id in existing_ids:
            return False
        with self.observations_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    document, ensure_ascii=False, sort_keys=True, default=str
                )
                + "\n"
            )
        self.write_canonical_index()
        return True

    def append_outcome(self, outcome: PortfolioForwardOutcome) -> bool:
        """Append one outcome per observation/maturity pair."""

        self.root.mkdir(parents=True, exist_ok=True)
        existing: set[tuple[str, int]] = set()
        for row in _read_jsonl(self.outcomes_path):
            maturity = row.get("maturity_sessions")
            maturity_value = maturity if isinstance(maturity, (int, float)) else 0
            existing.add((str(row.get("observation_id")), int(maturity_value)))
        key = (outcome.observation_id, outcome.maturity_sessions)
        if key in existing:
            return False
        if outcome.matured and outcome.realized_return is None:
            raise ValueError("matured outcome must contain realized return")
        with self.outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    outcome.document(),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
        return True

    def observations(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.observations_path)

    def outcomes(self) -> tuple[dict[str, object], ...]:
        return _read_jsonl(self.outcomes_path)

    def write_canonical_index(self) -> dict[str, object]:
        observations = self.observations()
        outcomes = self.outcomes()
        canonical: dict[str, dict[str, object]] = {}
        for row in observations:
            key = str(row.get("observation_id"))
            canonical.setdefault(key, row)
        payload = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "raw_observation_rows": len(observations),
            "canonical_observation_rows": len(canonical),
            "duplicate_observation_rows": len(observations) - len(canonical),
            "outcome_rows": len(outcomes),
            "matured_outcome_rows": sum(
                1 for row in outcomes if row.get("matured") is True
            ),
        }
        self.canonical_index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return payload

    def audit(self) -> dict[str, object]:
        observations = self.observations()
        outcomes = self.outcomes()
        pending = sum(1 for row in outcomes if row.get("matured") is False)
        matured = sum(1 for row in outcomes if row.get("matured") is True)
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "observations": len(observations),
            "outcomes": len(outcomes),
            "pending_outcomes": pending,
            "matured_outcomes": matured,
            "duplicate_occurrences": len(_read_jsonl(self.occurrences_path))
            - len(observations),
            "realized_fill_rows": sum(
                1
                for row in observations
                if row.get("actual_fill_quantity") not in (None, 0)
            ),
            "ledger_is_append_only": True,
        }


def _read_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(cast(dict[str, object], parsed))
    return tuple(rows)
