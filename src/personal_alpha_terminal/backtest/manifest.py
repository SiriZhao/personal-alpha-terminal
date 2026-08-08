from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class BacktestRunManifest:
    code_version: str
    data_snapshot: str
    universe_snapshot: str
    factor_version: str
    parameter_set: dict[str, object]
    execution_model: str
    cost_model: str
    random_seed: int
    start_date: date
    end_date: date
    benchmark: str
    created_at: datetime
    result_hash: str

    def __post_init__(self) -> None:
        if self.start_date >= self.end_date:
            raise ValueError("manifest start_date must precede end_date")
        if self.created_at.tzinfo is None:
            raise ValueError("manifest created_at must be timezone-aware")
        required = (
            self.code_version,
            self.data_snapshot,
            self.universe_snapshot,
            self.factor_version,
            self.execution_model,
            self.cost_model,
            self.benchmark,
            self.result_hash,
        )
        if not all(item.strip() for item in required):
            raise ValueError("backtest manifest requires immutable version identifiers")

    @property
    def manifest_hash(self) -> str:
        payload = json.dumps(asdict(self), default=str, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode()).hexdigest()
