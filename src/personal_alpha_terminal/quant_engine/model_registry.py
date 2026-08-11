from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import ModelApprovalRecord, ModelRegistryRecord


@dataclass(frozen=True, slots=True)
class ModelPromotionEvidence:
    data_version: str
    parameter_fingerprint: str
    validation_manifest_hash: str
    locked_oos: bool
    pit_certified: bool
    survivorship_bias_controlled: bool
    costs_included: bool
    approved_by: str
    notes: str = ""


class ModelRegistryService:
    """Govern model state; a status string alone never authorizes production use."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_registered(
        self,
        *,
        model_id: str,
        version: str,
        objective: str,
        inputs: list[str],
        data_requirements: list[str],
        hyperparameters: dict[str, object],
        limitations: list[str],
    ) -> ModelRegistryRecord:
        record = self.session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.model_id == model_id,
                ModelRegistryRecord.version == version,
            )
        )
        if record is not None:
            return record
        record = ModelRegistryRecord(
            model_id=model_id,
            version=version,
            owner="Personal Alpha Terminal",
            objective=objective,
            inputs=inputs,
            data_requirements=data_requirements,
            training_period=None,
            validation_period=None,
            test_period=None,
            hyperparameters=hyperparameters,
            status="Research",
            limitations=limitations,
            approval_level="research_only",
            last_validation=None,
            drift_status="NOT_EVALUATED",
        )
        self.session.add(record)
        self.session.flush()
        return record

    def promote(self, record: ModelRegistryRecord, evidence: ModelPromotionEvidence) -> None:
        if record.status != "Tested":
            raise ValueError("model must be TESTED before production promotion")
        if not all(
            (
                evidence.locked_oos,
                evidence.pit_certified,
                evidence.survivorship_bias_controlled,
                evidence.costs_included,
            )
        ):
            raise ValueError("production promotion requires locked OOS, PIT, universe and costs")
        if not all(
            value.strip()
            for value in (
                evidence.data_version,
                evidence.parameter_fingerprint,
                evidence.validation_manifest_hash,
                evidence.approved_by,
            )
        ):
            raise ValueError("promotion evidence lineage is incomplete")
        approval = ModelApprovalRecord(
            model_id=record.model_id,
            version=record.version,
            data_version=evidence.data_version,
            parameter_fingerprint=evidence.parameter_fingerprint,
            validation_manifest_hash=evidence.validation_manifest_hash,
            locked_oos=True,
            pit_certified=True,
            survivorship_bias_controlled=True,
            costs_included=True,
            approved_at=datetime.now(UTC),
            approved_by=evidence.approved_by,
            notes=evidence.notes,
        )
        self.session.add(approval)
        record.status = "Production Approved"
        record.approval_level = "production_approved"
        record.drift_status = "MONITORING_REQUIRED"
        self.session.flush()

    def production_approval(
        self,
        *,
        model_id: str,
        version: str,
        data_version: str,
        parameter_fingerprint: str,
        decision_time: datetime,
    ) -> ModelApprovalRecord | None:
        if not data_version.strip():
            raise ValueError('runtime data version is required')
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        record = self.session.scalar(
            select(ModelRegistryRecord).where(
                ModelRegistryRecord.model_id == model_id,
                ModelRegistryRecord.version == version,
                ModelRegistryRecord.status == "Production Approved",
            )
        )
        if record is None:
            return None
        return self.session.scalar(
            select(ModelApprovalRecord)
            .where(
                ModelApprovalRecord.model_id == model_id,
                ModelApprovalRecord.version == version,
                ModelApprovalRecord.parameter_fingerprint == parameter_fingerprint,
                ModelApprovalRecord.approved_at <= decision_time,
                ModelApprovalRecord.locked_oos.is_(True),
                ModelApprovalRecord.pit_certified.is_(True),
                ModelApprovalRecord.survivorship_bias_controlled.is_(True),
                ModelApprovalRecord.costs_included.is_(True),
            )
            .order_by(ModelApprovalRecord.approved_at.desc(), ModelApprovalRecord.id.desc())
            .limit(1)
        )


def fingerprint_parameters(parameters: dict[str, object]) -> str:
    import json

    return sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
