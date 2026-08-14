"""Immutable forward strategy authorization, separate from historical certification.

PROVISIONAL_FORWARD_APPROVED means the operator explicitly allows the frozen
Classical Champion to generate manual-trade signals on current, forward PIT data.
It is NOT production certification and never changes research status.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from personal_alpha_terminal.application.operational_readiness import (
    OperationalApprovalIdentity,
)
from personal_alpha_terminal.core.fingerprints import fingerprint


class StrategyApprovalDecision(StrEnum):
    BLOCK = "BLOCK"
    ALLOW_PROVISIONAL_FORWARD = "ALLOW_PROVISIONAL_FORWARD"
    ALLOW_FULL_PRODUCTION = "ALLOW_FULL_PRODUCTION"


@dataclass(frozen=True, slots=True)
class StrategyApproval:
    approval_id: str
    decision: StrategyApprovalDecision
    identity: dict[str, str]
    created_at: datetime
    operator_intent: str
    status: str = "EFFECTIVE"

    def matches(self, identity: OperationalApprovalIdentity) -> bool:
        return self.identity == _identity_document(identity)

    def document(self) -> dict[str, object]:
        return {
            **asdict(self),
            "created_at": self.created_at.isoformat(),
        }


class StrategyApprovalStore:
    """Content-addressed, immutable strategy approval store."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, approval: StrategyApproval, *, force: bool = False) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not force:
            raise FileExistsError(
                f"strategy approval already exists; refusing to overwrite: {self.path}"
            )
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(approval.document(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path

    def load(self) -> StrategyApproval | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return StrategyApproval(
            approval_id=str(payload["approval_id"]),
            decision=StrategyApprovalDecision(str(payload["decision"])),
            identity={str(key): str(value) for key, value in payload["identity"].items()},
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            operator_intent=str(payload.get("operator_intent", "")),
            status=str(payload.get("status", "EFFECTIVE")),
        )

    def status(
        self, identity: OperationalApprovalIdentity, *, now: datetime
    ) -> tuple[StrategyApproval | None, str]:
        approval = self.load()
        if approval is None:
            return None, "STRATEGY_APPROVAL_NOT_CONFIGURED"
        if approval.created_at > now:
            return None, "STRATEGY_APPROVAL_NOT_YET_AVAILABLE"
        if not approval.matches(identity):
            return None, "STRATEGY_APPROVAL_IDENTITY_MISMATCH"
        if approval.status != "EFFECTIVE":
            return None, f"STRATEGY_APPROVAL_STATUS_{approval.status}"
        return approval, "STRATEGY_APPROVAL_EFFECTIVE"


def issue_strategy_approval(
    *,
    identity: OperationalApprovalIdentity,
    decision: StrategyApprovalDecision,
    created_at: datetime | None = None,
    operator_intent: str,
) -> StrategyApproval:
    if decision not in {
        StrategyApprovalDecision.ALLOW_PROVISIONAL_FORWARD,
        StrategyApprovalDecision.ALLOW_FULL_PRODUCTION,
    }:
        raise ValueError("strategy approval decision must allow forward operation")
    now = created_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("strategy approval created_at must be timezone-aware")
    identity_doc = _identity_document(identity)
    approval_id = sha256(
        json.dumps(
            {
                "decision": decision.value,
                "identity": identity_doc,
                "created_at": now.isoformat(),
                "operator_intent": operator_intent,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return StrategyApproval(
        approval_id=f"strategy-approval-{approval_id[:16]}",
        decision=decision,
        identity=identity_doc,
        created_at=now,
        operator_intent=operator_intent,
    )


def _identity_document(identity: OperationalApprovalIdentity) -> dict[str, str]:
    values = asdict(identity)
    values["required_factor_lookbacks"] = sorted(values["required_factor_lookbacks"])
    return {
        str(key): str(value)
        for key, value in sorted(values.items())
        if value not in (None, "")
    }


def approval_identity_hash(identity: OperationalApprovalIdentity) -> str:
    return fingerprint(_identity_document(identity))
