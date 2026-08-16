"""ROUND30: deterministic formal decision participation panel.

This is a display/provenance projection only.  It never changes a target, an
action, a risk gate, or any formal quantitative value.  It makes explicit which
modules are ACTIVE in the current formal decision and which remain research-only
or advisory-only.
"""

from __future__ import annotations

from typing import Any

PARTICIPATION_SCHEMA = "round30-decision-participation-v1"


def decision_participation_from_provenance(
    provenance: dict[str, Any],
    *,
    market_regime: str = "OBSERVATION_ONLY",
) -> dict[str, str]:
    """Build the user-facing participation statement from persisted provenance."""

    overlay = provenance.get("probability_overlay")
    if not isinstance(overlay, dict):
        overlay = {}
    probability_state = str(overlay.get("state") or "RESEARCH_ONLY")
    return {
        "Alpha": "ACTIVE",
        "Probability": f"{probability_state} / 0%",
        "Covariance": "ACTIVE",
        "Risk": "ACTIVE",
        "Liquidity": "ACTIVE",
        "Transaction cost": "ACTIVE",
        "Turnover": "ACTIVE",
        "Size constraint": "DEGRADED",
        "Sector constraint": "ACTIVE",
        "Market regime": market_regime,
        "LLM": "ADVISORY_ONLY / NONE",
    }


def decision_participation_from_certificate(
    certificate: dict[str, Any],
) -> dict[str, Any]:
    """Project a persisted run certificate into the same participation panel."""

    provenance = certificate.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "schema_version": PARTICIPATION_SCHEMA,
        "source_run_id": certificate.get("run_id"),
        "modules": decision_participation_from_provenance(provenance),
    }
