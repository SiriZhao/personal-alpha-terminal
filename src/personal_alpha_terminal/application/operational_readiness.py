"""Operational readiness separated from long-horizon research certification.

Research certification continues to require survivorship-safe historical data,
PIT corporate actions, locked OOS, and after-cost validation.  Operational
readiness is a separate daily-decision state: it requires current real data,
current PIT eligibility, sufficient factor lookback, portfolio constraints, and
risk controls, but it does not claim long-run after-cost Alpha certification.
"""

from __future__ import annotations

import inspect
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, cast

from personal_alpha_terminal.core.build_metadata import current_build_metadata
from personal_alpha_terminal.core.fingerprints import fingerprint

if TYPE_CHECKING:
    from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )


class OperationalReadiness(StrEnum):
    BLOCKED = "BLOCKED"
    PROVISIONAL_ACTIONABLE = "PROVISIONAL_ACTIONABLE"
    FULLY_CERTIFIED_ACTIONABLE = "FULLY_CERTIFIED_ACTIONABLE"


OPERATIONAL_IDENTITY_V1 = "pat-operational-identity-v1"
OPERATIONAL_IDENTITY_V2 = "pat-operational-identity-v2"
LEGACY_UNBOUND = "LEGACY_UNBOUND"


@dataclass(frozen=True, slots=True)
class OperationalApprovalIdentity:
    strategy_name: str
    strategy_version: str
    factor_config_hash: str
    operational_universe_policy: str
    required_factor_lookbacks: tuple[tuple[str, int], ...]
    portfolio_config_hash: str
    risk_config_hash: str
    cost_model_hash: str
    schema_version: str = OPERATIONAL_IDENTITY_V1
    strategy_hash: str = LEGACY_UNBOUND
    factor_definition_hash: str = LEGACY_UNBOUND
    universe_definition_hash: str = LEGACY_UNBOUND
    probability_artifact_hash: str = LEGACY_UNBOUND
    probability_production_influence: str = LEGACY_UNBOUND
    llm_influence_identity: str = LEGACY_UNBOUND
    code_config_fingerprint: str = LEGACY_UNBOUND

    def __post_init__(self) -> None:
        if any(not str(value).strip() for value in (
            self.strategy_name,
            self.strategy_version,
            self.factor_config_hash,
            self.operational_universe_policy,
            self.portfolio_config_hash,
            self.risk_config_hash,
            self.cost_model_hash,
        )):
            raise ValueError("operational approval identity is incomplete")
        if not self.required_factor_lookbacks:
            raise ValueError("operational approval requires factor lookbacks")
        if any(
            not name.strip() or lookback < 1
            for name, lookback in self.required_factor_lookbacks
        ):
            raise ValueError("operational factor lookbacks must be positive")
        if self.schema_version not in {OPERATIONAL_IDENTITY_V1, OPERATIONAL_IDENTITY_V2}:
            raise ValueError("unsupported operational identity schema")
        if self.schema_version == OPERATIONAL_IDENTITY_V2:
            v2_values = (
                self.strategy_hash,
                self.factor_definition_hash,
                self.universe_definition_hash,
                self.probability_artifact_hash,
                self.probability_production_influence,
                self.llm_influence_identity,
                self.code_config_fingerprint,
            )
            if any(not value.strip() or value == LEGACY_UNBOUND for value in v2_values):
                raise ValueError("v2 operational approval identity is incomplete")

    def document(self) -> dict[str, object]:
        """Return schema-exact hash material, preserving verification of v1 artifacts."""

        legacy: dict[str, object] = {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "factor_config_hash": self.factor_config_hash,
            "operational_universe_policy": self.operational_universe_policy,
            "required_factor_lookbacks": self.required_factor_lookbacks,
            "portfolio_config_hash": self.portfolio_config_hash,
            "risk_config_hash": self.risk_config_hash,
            "cost_model_hash": self.cost_model_hash,
        }
        if self.schema_version == OPERATIONAL_IDENTITY_V1:
            return legacy
        return {
            "schema_version": self.schema_version,
            **legacy,
            "strategy_id": self.strategy_name,
            "strategy_hash": self.strategy_hash,
            "factor_definition_hash": self.factor_definition_hash,
            "universe_definition_hash": self.universe_definition_hash,
            "probability_artifact_hash": self.probability_artifact_hash,
            "probability_production_influence": self.probability_production_influence,
            "llm_influence_identity": self.llm_influence_identity,
            "code_config_fingerprint": self.code_config_fingerprint,
        }

    @property
    def identity_hash(self) -> str:
        return fingerprint(self.document())

    def diff(self, other: OperationalApprovalIdentity) -> dict[str, dict[str, object]]:
        stored = self.document()
        current = other.document()
        missing = object()
        differences: dict[str, dict[str, object]] = {}
        for key in sorted(set(stored) | set(current)):
            stored_value = stored.get(key, missing)
            current_value = current.get(key, missing)
            if stored_value == current_value:
                continue
            differences[key] = {
                "stored": (
                    "NOT_BOUND_IN_STORED_SCHEMA"
                    if stored_value is missing
                    else stored_value
                ),
                "current": (
                    "NOT_BOUND_IN_CURRENT_SCHEMA"
                    if current_value is missing
                    else current_value
                ),
            }
        return differences


@dataclass(frozen=True, slots=True)
class ProvisionalOperationalApproval:
    approval_id: str
    identity: OperationalApprovalIdentity
    created_at: datetime
    approval_reason: str
    research_certification_state: str
    full_research_certified: bool
    artifact_hash: str

    def __post_init__(self) -> None:
        if not self.approval_id.strip() or not self.approval_reason.strip():
            raise ValueError("provisional approval identity is incomplete")
        if self.created_at.tzinfo is None:
            raise ValueError("provisional approval created_at must be timezone-aware")
        if self.full_research_certified:
            raise ValueError("provisional approval cannot claim full research certification")

    def document(self) -> dict[str, object]:
        payload = {
            "approval_id": self.approval_id,
            "identity": self.identity.document(),
            "created_at": self.created_at.isoformat(),
            "approval_reason": self.approval_reason,
            "research_certification_state": self.research_certification_state,
            "full_research_certified": self.full_research_certified,
            "artifact_hash": self.artifact_hash,
        }
        return cast(dict[str, object], json.loads(json.dumps(payload, default=str, sort_keys=True)))


class ProvisionalOperationalRegistry:
    """Immutable file registry for provisional daily operational approvals."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def produce(
        self,
        *,
        identity: OperationalApprovalIdentity,
        created_at: datetime,
        approval_reason: str,
        research_certification_state: str,
    ) -> ProvisionalOperationalApproval:
        if created_at.tzinfo is None:
            raise ValueError("provisional approval created_at must be timezone-aware")
        if not research_certification_state.strip():
            raise ValueError("research certification state is required")
        payload = {
            "identity": identity.document(),
            "created_at": created_at.isoformat(),
            "approval_reason": approval_reason,
            "research_certification_state": research_certification_state,
            "full_research_certified": False,
        }
        artifact_hash = fingerprint(payload)
        approval_id = f"provisional-operational-{artifact_hash[:20]}"
        artifact = ProvisionalOperationalApproval(
            approval_id=approval_id,
            identity=identity,
            created_at=created_at,
            approval_reason=approval_reason,
            research_certification_state=research_certification_state,
            full_research_certified=False,
            artifact_hash=artifact_hash,
        )
        self._write(artifact)
        return artifact

    def matching_approval(
        self, identity: OperationalApprovalIdentity
    ) -> ProvisionalOperationalApproval | None:
        for path in sorted(self.root.glob("*.json")):
            try:
                artifact = self._load(path)
            except (OSError, KeyError, TypeError, ValueError):
                continue
            if (
                artifact.identity == identity
                and artifact.full_research_certified is False
            ):
                return artifact
        return None

    def load(self, approval_id: str) -> ProvisionalOperationalApproval:
        for path in self.root.glob("*.json"):
            artifact = self._load(path)
            if artifact.approval_id == approval_id:
                return artifact
        raise ValueError(f"provisional operational approval not found: {approval_id}")

    def _write(self, artifact: ProvisionalOperationalApproval) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{artifact.approval_id}.json"
        rendered = json.dumps(
            artifact.document(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(
                f"refusing to overwrite immutable provisional approval: {target}"
            )
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(target)

    @staticmethod
    def _load(path: Path) -> ProvisionalOperationalApproval:
        payload = cast(
            dict[str, object],
            json.loads(path.read_text(encoding="utf-8")),
        )
        identity_payload = cast(dict[str, object], payload["identity"])
        identity = _identity_from_payload(identity_payload)
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        artifact_hash = str(payload["artifact_hash"])
        expected_hash = fingerprint(
            {
                "identity": identity.document(),
                "created_at": created_at.isoformat(),
                "approval_reason": str(payload["approval_reason"]),
                "research_certification_state": str(
                    payload["research_certification_state"]
                ),
                "full_research_certified": bool(
                    payload["full_research_certified"]
                ),
            }
        )
        if expected_hash != artifact_hash:
            raise ValueError(f"provisional approval hash mismatch: {path}")
        return ProvisionalOperationalApproval(
            approval_id=str(payload["approval_id"]),
            identity=identity,
            created_at=created_at,
            approval_reason=str(payload["approval_reason"]),
            research_certification_state=str(
                payload["research_certification_state"]
            ),
            full_research_certified=bool(payload["full_research_certified"]),
            artifact_hash=artifact_hash,
        )


class OperationalPolicyDecision(StrEnum):
    """Explicit operational permission, independent of research certification."""

    ALLOW_PROVISIONAL = "ALLOW_PROVISIONAL"
    BLOCK = "BLOCK"


class OperationalPolicyStatusCode(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    BLOCKED = "BLOCKED"
    RESEARCH_STATE_NOT_ALLOWED = "RESEARCH_STATE_NOT_ALLOWED"
    TAMPERED_OR_MALFORMED = "TAMPERED_OR_MALFORMED"


@dataclass(frozen=True, slots=True)
class OperationalPolicyStatus:
    status: OperationalPolicyStatusCode
    effective: bool
    reason: str
    current_identity_hash: str
    stored_identity_hash: str = "NOT_CONFIGURED"
    mismatch_fields: dict[str, dict[str, object]] = field(default_factory=dict)
    policy: OperationalPolicy | None = None

    def public_document(self) -> dict[str, object]:
        policy = self.policy
        return {
            "Status": self.status.value,
            "Decision": (
                policy.decision.value
                if policy is not None
                else OperationalPolicyDecision.BLOCK.value
            ),
            "Effective": self.effective,
            "Reason": self.reason,
            "Policy ID": policy.policy_id if policy is not None else "NOT_CONFIGURED",
            "Created At": (
                policy.created_at.isoformat() if policy is not None else None
            ),
            "Expires At": (
                policy.expires_at.isoformat()
                if policy is not None and policy.expires_at is not None
                else None
            ),
            "Current Identity Hash": self.current_identity_hash,
            "Stored Identity Hash": self.stored_identity_hash,
            "Mismatch Fields": self.mismatch_fields,
            "Policy Artifact Hash": (
                policy.artifact_hash if policy is not None else "NOT_CONFIGURED"
            ),
        }


DEFAULT_ALLOWED_RESEARCH_STATES = ("NOT_CERTIFIABLE", "PARTIAL", "DEGRADED")


@dataclass(frozen=True, slots=True)
class OperationalPolicy:
    """Persistent, user-issued permission to run degraded production advice.

    Research certification is a separate truth source.  This policy only answers:
    given the current research state and an exact strategy/config identity, may the
    daily pipeline emit provisional recommendations?
    """

    policy_id: str
    decision: OperationalPolicyDecision
    research_states_allowed: tuple[str, ...]
    identity: OperationalApprovalIdentity
    issued_by: str
    created_at: datetime
    reason: str
    artifact_hash: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.reason.strip() or not self.issued_by.strip():
            raise ValueError("operational policy identity fields are required")
        object.__setattr__(
            self,
            "research_states_allowed",
            tuple(sorted(self.research_states_allowed)),
        )
        if self.created_at.tzinfo is None or (
            self.expires_at is not None and self.expires_at.tzinfo is None
        ):
            raise ValueError("operational policy timestamps must be timezone-aware")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("operational policy expiry must follow creation")
        if self.decision is OperationalPolicyDecision.ALLOW_PROVISIONAL:
            if not self.research_states_allowed:
                raise ValueError(
                    "ALLOW_PROVISIONAL requires at least one allowed research state"
                )
        else:
            object.__setattr__(self, "research_states_allowed", ())
        if not self.artifact_hash.strip():
            raise ValueError("operational policy artifact hash is required")

    def is_active(self, now: datetime) -> bool:
        if now.tzinfo is None:
            raise ValueError("operational policy evaluation time must be timezone-aware")
        return self.expires_at is None or now <= self.expires_at

    def allows(
        self,
        identity: OperationalApprovalIdentity,
        research_state: str,
        *,
        now: datetime,
    ) -> tuple[bool, str]:
        """Fail-closed permission check. Gates stay with the caller."""

        if not self.is_active(now):
            return False, "OPERATIONAL_POLICY_EXPIRED"
        if self.identity != identity:
            return False, "OPERATIONAL_POLICY_IDENTITY_MISMATCH"
        if research_state == "CERTIFIED":
            return True, "RESEARCH_CERTIFIED"
        if self.decision is OperationalPolicyDecision.BLOCK:
            return False, "OPERATIONAL_POLICY_BLOCK"
        if research_state not in self.research_states_allowed:
            return False, f"RESEARCH_STATE_NOT_ALLOWED:{research_state}"
        return True, "OPERATIONAL_POLICY_ALLOW_PROVISIONAL"

    @staticmethod
    def _payload(
        identity: OperationalApprovalIdentity,
        decision: OperationalPolicyDecision,
        research_states_allowed: tuple[str, ...],
        issued_by: str,
        created_at: datetime,
        reason: str,
        expires_at: datetime | None,
    ) -> dict[str, object]:
        return {
            "identity": identity.document(),
            "decision": decision.value,
            "research_states_allowed": sorted(research_states_allowed),
            "issued_by": issued_by,
            "created_at": created_at.isoformat(),
            "reason": reason,
            "expires_at": expires_at.isoformat() if expires_at is not None else None,
            "full_research_certified": False,
        }

    def document(self) -> dict[str, object]:
        payload = self._payload(
            self.identity,
            self.decision,
            self.research_states_allowed,
            self.issued_by,
            self.created_at,
            self.reason,
            self.expires_at,
        )
        return {
            "policy_id": self.policy_id,
            **payload,
            "artifact_hash": fingerprint(payload),
        }


class OperationalPolicyStore:
    """Read-only daily accessor plus explicit user-issued writes.

    ``load`` never creates the file: a missing or invalid policy fails closed.
    ``save`` is only reachable through an explicit operator command and refuses
    to overwrite a different policy unless ``force`` is passed.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> OperationalPolicy | None:
        if not self.path.exists():
            return None
        try:
            payload = cast(
                dict[str, object],
                json.loads(self.path.read_text(encoding="utf-8")),
            )
            payload = self._resolve_active_payload(payload)
            return self._from_payload(payload)
        except (KeyError, OSError, TypeError, ValueError):
            return None

    def status(
        self,
        current_identity: OperationalApprovalIdentity,
        *,
        research_state: str,
        now: datetime,
    ) -> OperationalPolicyStatus:
        if not self.path.exists():
            return OperationalPolicyStatus(
                OperationalPolicyStatusCode.NOT_CONFIGURED,
                False,
                "OPERATIONAL_POLICY_NOT_CONFIGURED",
                current_identity.identity_hash,
            )
        try:
            payload = cast(
                dict[str, object],
                json.loads(self.path.read_text(encoding="utf-8")),
            )
            payload = self._resolve_active_payload(payload)
            policy = self._from_payload(payload)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return OperationalPolicyStatus(
                OperationalPolicyStatusCode.TAMPERED_OR_MALFORMED,
                False,
                "OPERATIONAL_POLICY_TAMPERED_OR_MALFORMED",
                current_identity.identity_hash,
            )
        mismatch = policy.identity.diff(current_identity)
        if not policy.is_active(now):
            code = OperationalPolicyStatusCode.EXPIRED
            reason = "OPERATIONAL_POLICY_EXPIRED"
            effective = False
        elif mismatch:
            code = OperationalPolicyStatusCode.IDENTITY_MISMATCH
            reason = "OPERATIONAL_POLICY_IDENTITY_MISMATCH"
            effective = False
        elif policy.decision is OperationalPolicyDecision.BLOCK:
            code = OperationalPolicyStatusCode.BLOCKED
            reason = "OPERATIONAL_POLICY_BLOCK"
            effective = False
        elif research_state not in policy.research_states_allowed:
            code = OperationalPolicyStatusCode.RESEARCH_STATE_NOT_ALLOWED
            reason = f"RESEARCH_STATE_NOT_ALLOWED:{research_state}"
            effective = False
        else:
            code = OperationalPolicyStatusCode.VALID
            reason = "OPERATIONAL_POLICY_ALLOW_PROVISIONAL"
            effective = True
        return OperationalPolicyStatus(
            code,
            effective,
            reason,
            current_identity.identity_hash,
            policy.identity.identity_hash,
            mismatch,
            policy,
        )

    def save(self, policy: OperationalPolicy, *, force: bool = False) -> None:
        rendered = (
            json.dumps(policy.document(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        artifact_dir = self.path.parent / "policy-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / f"{policy.artifact_hash}.json"
        if artifact.exists() and artifact.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(
                f"refusing to overwrite immutable operational policy artifact: {artifact}"
            )
        if not artifact.exists():
            artifact_temporary = artifact.with_suffix(".json.tmp")
            artifact_temporary.write_text(rendered, encoding="utf-8")
            artifact_temporary.replace(artifact)
        active_document = {
            "active_policy_schema": "pat-operational-policy-active-v1",
            "policy_id": policy.policy_id,
            "artifact_hash": policy.artifact_hash,
            "artifact_path": f"policy-artifacts/{policy.artifact_hash}.json",
        }
        active_rendered = (
            json.dumps(active_document, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        if self.path.exists():
            if self.path.read_text(encoding="utf-8") in {rendered, active_rendered}:
                return
            if not force:
                raise FileExistsError(
                    f"operational policy already exists and differs: {self.path}"
                )
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(active_rendered, encoding="utf-8")
        temporary.replace(self.path)

    def _resolve_active_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        if payload.get("active_policy_schema") != "pat-operational-policy-active-v1":
            return payload
        artifact_hash = str(payload["artifact_hash"])
        artifact_path = str(payload["artifact_path"])
        expected_relative = f"policy-artifacts/{artifact_hash}.json"
        if artifact_path.replace("\\", "/") != expected_relative:
            raise ValueError("operational policy active reference path mismatch")
        target = self.path.parent / "policy-artifacts" / f"{artifact_hash}.json"
        artifact_payload = cast(
            dict[str, object],
            json.loads(target.read_text(encoding="utf-8")),
        )
        if str(artifact_payload.get("artifact_hash")) != artifact_hash:
            raise ValueError("operational policy active reference hash mismatch")
        if str(artifact_payload.get("policy_id")) != str(payload["policy_id"]):
            raise ValueError("operational policy active reference id mismatch")
        return artifact_payload

    @staticmethod
    def _from_payload(payload: dict[str, object]) -> OperationalPolicy:
        identity_payload = cast(dict[str, object], payload["identity"])
        identity = _identity_from_payload(identity_payload)
        decision = OperationalPolicyDecision(str(payload["decision"]))
        research_states = tuple(
            str(item)
            for item in cast(list[object], payload.get("research_states_allowed", []))
        )
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        expires_raw = payload.get("expires_at")
        expires_at = (
            datetime.fromisoformat(str(expires_raw))
            if expires_raw
            else None
        )
        expected = fingerprint(
            OperationalPolicy._payload(
                identity,
                decision,
                research_states,
                str(payload["issued_by"]),
                created_at,
                str(payload["reason"]),
                expires_at,
            )
        )
        artifact_hash = str(payload["artifact_hash"])
        if expected != artifact_hash:
            raise ValueError("operational policy hash mismatch")
        return OperationalPolicy(
            policy_id=str(payload["policy_id"]),
            decision=decision,
            research_states_allowed=research_states,
            identity=identity,
            issued_by=str(payload["issued_by"]),
            created_at=created_at,
            reason=str(payload["reason"]),
            artifact_hash=artifact_hash,
            expires_at=expires_at,
        )


def issue_operational_policy(
    *,
    identity: OperationalApprovalIdentity,
    decision: OperationalPolicyDecision,
    research_states_allowed: tuple[str, ...],
    issued_by: str,
    reason: str,
    created_at: datetime,
    expires_at: datetime | None = None,
) -> OperationalPolicy:
    """Create a hash-bound operational policy. Only an explicit operator call may use this."""

    payload = OperationalPolicy._payload(
        identity,
        decision,
        research_states_allowed,
        issued_by,
        created_at,
        reason,
        expires_at,
    )
    artifact_hash = fingerprint(payload)
    return OperationalPolicy(
        policy_id=f"operational-policy-{artifact_hash[:20]}",
        decision=decision,
        research_states_allowed=research_states_allowed,
        identity=identity,
        issued_by=issued_by,
        created_at=created_at,
        reason=reason,
        artifact_hash=artifact_hash,
        expires_at=expires_at,
    )


def classify_operational_state(
    identity: OperationalApprovalIdentity,
    research_state: str,
    policy: OperationalPolicy | None,
    *,
    now: datetime,
) -> tuple[bool, str, str]:
    """Return ``(operationally_allowed, policy_id_or_NOT_CONFIGURED, reason)``."""

    if research_state == "CERTIFIED":
        return (
            True,
            policy.policy_id if policy is not None else "NOT_CONFIGURED",
            "RESEARCH_CERTIFIED",
        )
    if policy is None:
        return False, "NOT_CONFIGURED", "OPERATIONAL_POLICY_NOT_CONFIGURED"
    allowed, reason = policy.allows(identity, research_state, now=now)
    return allowed, policy.policy_id, reason


def _identity_from_payload(
    identity_payload: dict[str, object],
) -> OperationalApprovalIdentity:
    lookbacks = cast(
        list[list[object]],
        identity_payload["required_factor_lookbacks"],
    )
    schema_version = str(
        identity_payload.get("schema_version", OPERATIONAL_IDENTITY_V1)
    )
    return OperationalApprovalIdentity(
        strategy_name=str(identity_payload["strategy_name"]),
        strategy_version=str(identity_payload["strategy_version"]),
        factor_config_hash=str(identity_payload["factor_config_hash"]),
        operational_universe_policy=str(
            identity_payload["operational_universe_policy"]
        ),
        required_factor_lookbacks=tuple(
            (str(name), int(str(value)))
            for name, value in lookbacks
        ),
        portfolio_config_hash=str(identity_payload["portfolio_config_hash"]),
        risk_config_hash=str(identity_payload["risk_config_hash"]),
        cost_model_hash=str(identity_payload["cost_model_hash"]),
        schema_version=schema_version,
        strategy_hash=str(identity_payload.get("strategy_hash", LEGACY_UNBOUND)),
        factor_definition_hash=str(
            identity_payload.get("factor_definition_hash", LEGACY_UNBOUND)
        ),
        universe_definition_hash=str(
            identity_payload.get("universe_definition_hash", LEGACY_UNBOUND)
        ),
        probability_artifact_hash=str(
            identity_payload.get("probability_artifact_hash", LEGACY_UNBOUND)
        ),
        probability_production_influence=str(
            identity_payload.get(
                "probability_production_influence",
                LEGACY_UNBOUND,
            )
        ),
        llm_influence_identity=str(
            identity_payload.get("llm_influence_identity", LEGACY_UNBOUND)
        ),
        code_config_fingerprint=str(
            identity_payload.get("code_config_fingerprint", LEGACY_UNBOUND)
        ),
    )


def build_operational_identity(
    config: EffectiveRuntimeConfig,
    strategy: USAdaptiveAlphaCoreV1,
    *,
    probability_artifact_hash: str = "NO_PROBABILITY_ASSESSMENT",
    probability_production_influence: float = 0.0,
    llm_influence_identity: str = "LLM_SHADOW_NONE",
) -> OperationalApprovalIdentity:
    """Derive the exact strategy/config identity an operational policy must match."""

    from personal_alpha_terminal.data.us_market.broad_universe import EligibilityRules

    rules = EligibilityRules(**asdict(config.broad_universe))
    required_lookbacks = {
        "momentum": strategy.config.momentum_lookback,
        "trend": strategy.config.trend_window,
        "volatility": strategy.config.volatility_window,
    }
    if getattr(sys, "frozen", False):
        metadata = current_build_metadata()
        strategy_definition = (
            f"frozen:{strategy.model_id}:{strategy.version}:"
            f"{metadata.build_id}:{metadata.git_commit}"
        )
        factor_definition = f"frozen-factor:{type(strategy.config).__name__}"
    else:
        strategy_definition = inspect.getsource(type(strategy))
        factor_definition = inspect.getsource(type(strategy.config))
    return OperationalApprovalIdentity(
        strategy_name=strategy.model_id,
        strategy_version=strategy.version,
        factor_config_hash=strategy.config.parameter_fingerprint,
        operational_universe_policy=rules.fingerprint,
        required_factor_lookbacks=tuple(sorted(required_lookbacks.items())),
        portfolio_config_hash=config.portfolio_constraint_hash,
        risk_config_hash=config.risk_model_hash,
        cost_model_hash=config.cost_model_hash,
        schema_version=OPERATIONAL_IDENTITY_V2,
        strategy_hash=fingerprint(
            {
                "model_id": strategy.model_id,
                "version": strategy.version,
                "definition": strategy_definition,
            }
        ),
        factor_definition_hash=fingerprint(
            {
                "definition": factor_definition,
                "parameters": strategy.config.parameter_fingerprint,
            }
        ),
        universe_definition_hash=rules.fingerprint,
        probability_artifact_hash=probability_artifact_hash,
        probability_production_influence=f"{probability_production_influence:.12g}",
        llm_influence_identity=llm_influence_identity,
        code_config_fingerprint=fingerprint(
            {
                "canonical_run_config_hash": config.canonical_run_config_hash,
                "strategy_hash": fingerprint(strategy_definition),
                "factor_definition_hash": fingerprint(factor_definition),
            }
        ),
    )


def resolve_current_operational_identity(
    config: EffectiveRuntimeConfig,
    strategy: USAdaptiveAlphaCoreV1,
    *,
    decision_time: datetime,
) -> OperationalApprovalIdentity:
    """Resolve the exact policy identity used by CLI and daily operation."""

    if decision_time.tzinfo is None:
        raise ValueError("operational identity decision_time must be timezone-aware")
    from personal_alpha_terminal.quant_engine.probability_assessment import (
        ProbabilityAssessmentRegistry,
    )

    assessment = ProbabilityAssessmentRegistry(
        config.validation_artifact_dir
    ).latest_for_strategy(
        strategy_id=strategy.model_id,
        strategy_version=strategy.version,
        strategy_parameter_hash=strategy.config.parameter_fingerprint,
        decision_time=decision_time,
    )
    return build_operational_identity(
        config,
        strategy,
        probability_artifact_hash=(
            assessment.artifact_hash
            if assessment is not None
            else "NO_PROBABILITY_ASSESSMENT"
        ),
        probability_production_influence=(
            assessment.production_influence if assessment is not None else 0.0
        ),
        llm_influence_identity="LLM_SHADOW_NONE",
    )
