from __future__ import annotations

from personal_alpha_terminal.quant_engine.historical_data_acquisition import CapabilityStatus
from personal_alpha_terminal.quant_engine.provider_selection import (
    MarketDataCapabilityClaim,
    provider_capability_claims,
)


def _claim_map() -> dict[tuple[str, str], MarketDataCapabilityClaim]:
    return {
        (claim.provider_id, claim.capability): claim
        for claim in provider_capability_claims()
    }


def test_all_provider_selection_claims_are_officially_grounded() -> None:
    claims = provider_capability_claims()
    assert claims
    for claim in claims:
        assert claim.official_url.startswith("https://")
        assert claim.official_url
        assert claim.exact_official_statement.strip()
        if claim.confidence == "UNKNOWN_REQUIRES_PROVIDER_CONFIRMATION":
            assert claim.status is CapabilityStatus.UNKNOWN


def test_critical_provider_claims_are_conservative() -> None:
    claims = _claim_map()
    assert claims[("crsp_us_stock", "permanent_security_id")].status is CapabilityStatus.YES
    assert claims[("norgate_data", "delisting_return")].status is CapabilityStatus.NO
    assert claims[("norgate_data", "pit_total_return_vintages")].status is CapabilityStatus.NO
    assert claims[("massive", "license_scope")].status is CapabilityStatus.REQUIRES_LICENSE
    assert claims[("alpaca", "pit_corporate_action_availability")].status is CapabilityStatus.NO
    assert claims[("eodhd", "historical_membership")].status is CapabilityStatus.NO
