from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from json import dumps

from personal_alpha_terminal.data.market_data_certification import (
    CertificationGateResult,
    CertificationStatus,
)


class USRealDataStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class USRealDataCertification:
    status: USRealDataStatus
    sample_size: int
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_fingerprint: str

    @property
    def permits_quant_research(self) -> bool:
        return self.status is USRealDataStatus.PASS


def certify_us_research_data(
    gate: CertificationGateResult,
    *,
    has_pit_universe_history: bool,
    has_pit_corporate_actions: bool,
    has_verified_calendar: bool,
    has_delisting_and_symbol_history: bool,
) -> USRealDataCertification:
    """Promote existing cross-source evidence only when every PIT prerequisite passes."""

    blockers = list(gate.blockers)
    requirements = {
        "point-in-time universe history is incomplete": has_pit_universe_history,
        "point-in-time corporate-action history is incomplete": has_pit_corporate_actions,
        "verified US trading calendar is unavailable": has_verified_calendar,
        "delisting and symbol-change history is incomplete": has_delisting_and_symbol_history,
    }
    blockers.extend(message for message, passed in requirements.items() if not passed)
    if gate.status is not CertificationStatus.PASSED:
        blockers.append(f"cross-source certification status is {gate.status.value}")
    blockers = list(dict.fromkeys(blockers))
    payload = {
        "gate_status": gate.status.value,
        "sample_size": gate.random_sample_size,
        "gate_blockers": list(gate.blockers),
        "requirements": requirements,
        "results": [
            {
                "symbol": item.symbol,
                "status": item.status.value,
                "source_count": item.source_count,
                "matched_sessions": item.matched_sessions,
                "price_mismatches": item.price_mismatches,
                "volume_mismatches": item.volume_mismatches,
            }
            for item in gate.results
        ],
    }
    fingerprint = sha256(
        dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return USRealDataCertification(
        status=USRealDataStatus.BLOCKED if blockers else USRealDataStatus.PASS,
        sample_size=gate.random_sample_size,
        blockers=tuple(blockers),
        warnings=(),
        evidence_fingerprint=fingerprint,
    )
