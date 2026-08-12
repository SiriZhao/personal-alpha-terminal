"""ROUND 8: append-only research registry for every experiment.

Every experiment -- promoted, rejected, or research-only -- is recorded.  The
registry never drops a losing experiment, so reported results cannot be a
cherry-picked subset.  Each entry binds the full lineage: strategy ID,
hypothesis, factors, parameters, universe, horizon, benchmark, cost model,
train/validation/OOS periods, results and rejection reason.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.core.fingerprints import fingerprint


class ExperimentStatus(StrEnum):
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"


@dataclass(frozen=True, slots=True)
class ResearchExperiment:
    experiment_id: str
    strategy_id: str
    strategy_version: str
    hypothesis: str
    factors: tuple[str, ...]
    parameters: dict[str, Any]
    universe_version: str
    horizon: int
    benchmark: str
    cost_model_version: str
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    oos_start: date
    oos_end: date
    results: dict[str, Any]
    status: ExperimentStatus
    rejection_reason: str = ""
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.experiment_id,
                self.strategy_id,
                self.strategy_version,
                self.hypothesis,
                self.universe_version,
                self.benchmark,
                self.cost_model_version,
            )
        ):
            raise ValueError("research experiment identity is incomplete")
        if not self.factors or not self.parameters:
            raise ValueError("research experiment requires factors and parameters")
        if self.horizon < 1:
            raise ValueError("research experiment horizon must be positive")
        if not (
            self.train_start <= self.train_end
            <= self.validation_start
            <= self.validation_end
            <= self.oos_start
            <= self.oos_end
        ):
            raise ValueError("research experiment periods must be chronologically ordered")
        if self.status is ExperimentStatus.REJECTED and not self.rejection_reason.strip():
            raise ValueError("a rejected experiment must record its rejection reason")

    @property
    def lineage_hash(self) -> str:
        return fingerprint(
            {
                "strategy_id": self.strategy_id,
                "strategy_version": self.strategy_version,
                "factors": sorted(self.factors),
                "parameters": self.parameters,
                "universe_version": self.universe_version,
                "horizon": self.horizon,
                "benchmark": self.benchmark,
                "cost_model_version": self.cost_model_version,
            }
        )

    def document(self) -> dict[str, Any]:
        payload: dict[str, Any] = asdict(self)
        payload["created_at"] = (
            self.created_at.isoformat() if self.created_at is not None else None
        )
        payload["train_start"] = self.train_start.isoformat()
        payload["train_end"] = self.train_end.isoformat()
        payload["validation_start"] = self.validation_start.isoformat()
        payload["validation_end"] = self.validation_end.isoformat()
        payload["oos_start"] = self.oos_start.isoformat()
        payload["oos_end"] = self.oos_end.isoformat()
        payload["status"] = self.status.value
        payload["lineage_hash"] = self.lineage_hash
        return cast(dict[str, Any], json.loads(json.dumps(payload, default=str, sort_keys=True)))


class ResearchRegistry:
    """Immutable append-only experiment ledger.

    Identical re-appends are idempotent; a conflicting payload for an existing
    experiment_id is rejected.  Rejected and research-only experiments are
    preserved exactly like promoted ones.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, experiment: ResearchExperiment) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = experiment.document()
        lines = self._lines()
        for line in lines:
            prior = json.loads(line)
            if prior["experiment_id"] == document["experiment_id"]:
                if prior != document:
                    raise ValueError(
                        f"experiment identity conflict: {experiment.experiment_id}"
                    )
                return
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document, sort_keys=True) + "\n")

    def load(self) -> tuple[ResearchExperiment, ...]:
        experiments: list[ResearchExperiment] = []
        for line in self._lines():
            experiments.append(_experiment_from_document(json.loads(line)))
        return tuple(experiments)

    def by_strategy(self, strategy_id: str) -> tuple[ResearchExperiment, ...]:
        return tuple(
            item for item in self.load() if item.strategy_id == strategy_id
        )

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.load():
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        counts["total"] = len(self.load())
        return counts

    def _lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _experiment_from_document(payload: dict[str, Any]) -> ResearchExperiment:
    periods = {
        key: date.fromisoformat(str(payload[key]))
        for key in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "oos_start",
            "oos_end",
        )
    }
    created = (
        datetime.fromisoformat(str(payload["created_at"]))
        if payload.get("created_at")
        else None
    )
    return ResearchExperiment(
        experiment_id=str(payload["experiment_id"]),
        strategy_id=str(payload["strategy_id"]),
        strategy_version=str(payload["strategy_version"]),
        hypothesis=str(payload["hypothesis"]),
        factors=tuple(str(item) for item in cast(list[Any], payload["factors"])),
        parameters=cast(dict[str, Any], payload["parameters"]),
        universe_version=str(payload["universe_version"]),
        horizon=int(payload["horizon"]),
        benchmark=str(payload["benchmark"]),
        cost_model_version=str(payload["cost_model_version"]),
        train_start=periods["train_start"],
        train_end=periods["train_end"],
        validation_start=periods["validation_start"],
        validation_end=periods["validation_end"],
        oos_start=periods["oos_start"],
        oos_end=periods["oos_end"],
        results=cast(dict[str, Any], payload["results"]),
        status=ExperimentStatus(str(payload["status"])),
        rejection_reason=str(payload.get("rejection_reason", "")),
        created_at=created,
    )
