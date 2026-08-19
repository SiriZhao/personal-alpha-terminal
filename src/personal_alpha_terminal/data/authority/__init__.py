"""Provider-independent data-authority and PIT provenance contracts.

This package deliberately describes evidence and provider authority without
changing the production market-data refresh path. Operational price adapters
remain in :mod:`personal_alpha_terminal.data.market_data`; historical research
must explicitly satisfy the stronger authority and PIT contracts here.
"""

from personal_alpha_terminal.data.authority.contracts import (
    AuthorityTier,
    CanonicalObservation,
    CoverageReport,
    DataConflict,
    DataDomain,
    DataProvenance,
    DataQualityStatus,
    PITQuery,
    ProviderMetadata,
    ProviderRole,
    RawObservation,
    detect_conflicts,
)
from personal_alpha_terminal.data.authority.identity import (
    IdentityResolutionStatus,
    LifecycleEventType,
    PITIdentityResolution,
    PITSecurityMaster,
    SecurityIdentityVintage,
    SecurityLifecycleEvent,
)
from personal_alpha_terminal.data.authority.policy import (
    AuthorityPolicy,
    AuthorityResolution,
    ProviderRegistry,
    authority_status_document,
    default_authority_policy,
    default_provider_registry,
)
from personal_alpha_terminal.data.authority.repository import (
    AuthorityEvidenceRepository,
    ImmutableEvidenceConflict,
)
from personal_alpha_terminal.data.authority.sec_edgar import (
    CompanyFactsNormalizationResult,
    SecCompanyFact,
    SecEdgarAuthorityAdapter,
    SecFilingAvailability,
    facts_known_at_or_before,
    latest_facts_known_at_or_before,
    normalize_company_facts,
    parse_sec_former_names,
    parse_sec_submissions,
)

__all__ = [
    "AuthorityPolicy",
    "AuthorityEvidenceRepository",
    "AuthorityResolution",
    "AuthorityTier",
    "CanonicalObservation",
    "CompanyFactsNormalizationResult",
    "CoverageReport",
    "DataConflict",
    "DataDomain",
    "DataProvenance",
    "DataQualityStatus",
    "IdentityResolutionStatus",
    "ImmutableEvidenceConflict",
    "LifecycleEventType",
    "PITQuery",
    "PITIdentityResolution",
    "PITSecurityMaster",
    "ProviderMetadata",
    "ProviderRegistry",
    "ProviderRole",
    "RawObservation",
    "SecCompanyFact",
    "SecEdgarAuthorityAdapter",
    "SecFilingAvailability",
    "SecurityIdentityVintage",
    "SecurityLifecycleEvent",
    "authority_status_document",
    "default_authority_policy",
    "default_provider_registry",
    "detect_conflicts",
    "facts_known_at_or_before",
    "latest_facts_known_at_or_before",
    "normalize_company_facts",
    "parse_sec_former_names",
    "parse_sec_submissions",
]
