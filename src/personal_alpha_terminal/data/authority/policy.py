"""Authority selection policies; they choose eligible sources, never data truth."""

from __future__ import annotations

from dataclasses import dataclass

from personal_alpha_terminal.data.authority.contracts import (
    AuthorityTier,
    DataDomain,
    DataQualityStatus,
    PITQuery,
    ProviderAdapter,
    ProviderMetadata,
    ProviderRole,
    RawObservation,
)


@dataclass(frozen=True, slots=True)
class AuthorityPolicy:
    """Required provider roles and PIT expectations for one evidence domain."""

    domain: DataDomain
    allowed_roles: frozenset[ProviderRole]
    require_pit_capability: bool
    require_enabled_provider: bool = True


@dataclass(frozen=True, slots=True)
class AuthorityResolution:
    domain: DataDomain
    status: DataQualityStatus
    providers: tuple[ProviderMetadata, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


class ProviderRegistry:
    """Provider-independent registry; actual fetching remains behind adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        provider_id = adapter.metadata.provider_id
        if provider_id in self._adapters:
            raise ValueError(f"provider already registered: {provider_id}")
        self._adapters[provider_id] = adapter

    def metadata(self) -> tuple[ProviderMetadata, ...]:
        return tuple(self._adapters[key].metadata for key in sorted(self._adapters))

    def adapter_for(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as error:
            raise ValueError(f"unknown provider: {provider_id}") from error

    def providers_for(self, domain: DataDomain) -> tuple[ProviderMetadata, ...]:
        return tuple(item for item in self.metadata() if domain in item.data_domains)

    def resolve(self, policy: AuthorityPolicy) -> AuthorityResolution:
        candidates = tuple(
            item
            for item in self.providers_for(policy.domain)
            if item.fallback_role in policy.allowed_roles
        )
        enabled = tuple(item for item in candidates if item.enabled)
        pit_capable = tuple(item for item in enabled if item.pit_capable)
        blockers: list[str] = []
        warnings: list[str] = []
        selected = enabled
        if policy.require_enabled_provider and not enabled:
            blockers.append(f"{policy.domain.value}:NO_ENABLED_AUTHORITY_PROVIDER")
        if policy.require_pit_capability:
            if not pit_capable:
                blockers.append(f"{policy.domain.value}:NO_ENABLED_PIT_CAPABLE_PROVIDER")
            selected = pit_capable
        if selected and not blockers:
            has_primary_or_official = any(
                item.authority_tier in {AuthorityTier.PRIMARY, AuthorityTier.OFFICIAL}
                for item in selected
            )
            if not has_primary_or_official:
                warnings.append(f"{policy.domain.value}:NO_PRIMARY_OR_OFFICIAL_PROVIDER")
            if not any(item.pit_capable for item in selected):
                warnings.append(f"{policy.domain.value}:OPERATIONAL_SOURCE_NOT_CERTIFIED_PIT")
            if warnings:
                status = DataQualityStatus.PARTIAL
            else:
                status = DataQualityStatus.PASS_WITH_WARNINGS
        else:
            status = DataQualityStatus.BLOCKED_WITH_EVIDENCE
        return AuthorityResolution(
            domain=policy.domain,
            status=status,
            providers=selected,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )


@dataclass(frozen=True, slots=True)
class _MetadataOnlyAdapter:
    """Registers a declared source without accidentally enabling network calls."""

    metadata: ProviderMetadata

    def fetch_raw(self, query: PITQuery) -> tuple[RawObservation, ...]:
        del query
        raise RuntimeError(
            f"provider {self.metadata.provider_id} is metadata-only; "
            "configure an adapter explicitly"
        )


def default_authority_policy() -> tuple[AuthorityPolicy, ...]:
    """Declared source policy. It is not a data-certification bypass."""

    research_roles = frozenset(
        {ProviderRole.PRIMARY, ProviderRole.SECONDARY, ProviderRole.CROSS_CHECK}
    )
    all_roles = research_roles | frozenset({ProviderRole.OPTIONAL})
    return (
        AuthorityPolicy(DataDomain.MARKET_PRICES, research_roles, False),
        AuthorityPolicy(DataDomain.CORPORATE_ACTIONS, research_roles, True),
        AuthorityPolicy(DataDomain.TOTAL_RETURN, research_roles, True),
        AuthorityPolicy(DataDomain.ISSUER_IDENTITY, research_roles, True),
        AuthorityPolicy(DataDomain.SECURITY_IDENTITY, research_roles, True),
        AuthorityPolicy(DataDomain.SECURITY_LIFECYCLE, research_roles, True),
        AuthorityPolicy(DataDomain.UNIVERSE_MEMBERSHIP, research_roles, True),
        AuthorityPolicy(DataDomain.BENCHMARK, research_roles, True),
        AuthorityPolicy(DataDomain.FUNDAMENTALS, research_roles, True),
        AuthorityPolicy(DataDomain.FILINGS, research_roles, True),
        AuthorityPolicy(DataDomain.NEWS_EVENTS, research_roles, True),
        AuthorityPolicy(DataDomain.EXECUTABLE_OPENS, research_roles, True),
        AuthorityPolicy(DataDomain.MACRO_RISK_FREE, all_roles, True),
    )


def default_provider_registry() -> ProviderRegistry:
    """Return explicit source posture without importing or calling provider SDKs."""

    descriptors = (
        ProviderMetadata(
            provider_id="yahoo_finance",
            data_domains=frozenset({DataDomain.MARKET_PRICES, DataDomain.BENCHMARK}),
            authority_tier=AuthorityTier.PRIMARY,
            pit_capable=False,
            timestamp_semantics=(
                "provider retrieval timestamp; daily bars retain explicit available_at"
            ),
            adjustment_semantics=(
                "raw OHLCV plus provider adjusted close; adjusted history may be revised"
            ),
            credential_required=False,
            coverage_notes=(
                "Operational US price source; not certified historical PIT total-return evidence."
            ),
            fallback_role=ProviderRole.PRIMARY,
            enabled=True,
        ),
        ProviderMetadata(
            provider_id="stooq",
            data_domains=frozenset({DataDomain.MARKET_PRICES, DataDomain.BENCHMARK}),
            authority_tier=AuthorityTier.SECONDARY,
            pit_capable=False,
            timestamp_semantics=(
                "daily CSV retrieval timestamp; provider publication vintage is not guaranteed"
            ),
            adjustment_semantics="raw daily OHLCV; no declared total-return vintage",
            credential_required=False,
            coverage_notes=(
                "Operational backup/cross-check; not a certified complete US security history."
            ),
            fallback_role=ProviderRole.SECONDARY,
            enabled=True,
        ),
        ProviderMetadata(
            provider_id="sec_edgar",
            data_domains=frozenset(
                {
                    DataDomain.ISSUER_IDENTITY,
                    DataDomain.SECURITY_IDENTITY,
                    DataDomain.FILINGS,
                    DataDomain.FUNDAMENTALS,
                    DataDomain.NEWS_EVENTS,
                }
            ),
            authority_tier=AuthorityTier.OFFICIAL,
            pit_capable=True,
            timestamp_semantics=(
                "SEC filing acceptance datetime is known_at; filing date alone is not a "
                "time-of-day substitute"
            ),
            adjustment_semantics="not applicable to filings or XBRL facts",
            credential_required=True,
            coverage_notes=(
                "Requires a compliant declared SEC user-agent and exact accession/acceptance "
                "provenance."
            ),
            fallback_role=ProviderRole.PRIMARY,
            enabled=False,
        ),
        ProviderMetadata(
            provider_id="official_exchange_evidence",
            data_domains=frozenset(
                {
                    DataDomain.SECURITY_LIFECYCLE,
                    DataDomain.CORPORATE_ACTIONS,
                    DataDomain.EXECUTABLE_OPENS,
                }
            ),
            authority_tier=AuthorityTier.OFFICIAL,
            pit_capable=True,
            timestamp_semantics=(
                "exchange announcement and effective timestamps must be retained separately"
            ),
            adjustment_semantics="event-specific explicit split/dividend/merger semantics",
            credential_required=False,
            coverage_notes=(
                "Adapter/import must prove scope; Nasdaq alone does not establish all-US coverage."
            ),
            fallback_role=ProviderRole.PRIMARY,
            enabled=False,
        ),
        ProviderMetadata(
            provider_id="openfigi",
            data_domains=frozenset({DataDomain.SECURITY_IDENTITY}),
            authority_tier=AuthorityTier.SECONDARY,
            pit_capable=False,
            timestamp_semantics=(
                "mapping observation time only; it cannot retroactively prove historical identity"
            ),
            adjustment_semantics="not applicable to identifier mapping",
            credential_required=True,
            coverage_notes=(
                "Optional secondary FIGI cross-check; ambiguity remains unresolved without PIT "
                "evidence."
            ),
            fallback_role=ProviderRole.CROSS_CHECK,
            enabled=False,
        ),
        ProviderMetadata(
            provider_id="fred_alfred",
            data_domains=frozenset({DataDomain.MACRO_RISK_FREE}),
            authority_tier=AuthorityTier.OFFICIAL,
            pit_capable=True,
            timestamp_semantics="ALFRED release/revision vintage and available_at are required",
            adjustment_semantics="not applicable to macro/risk-free observations",
            credential_required=False,
            coverage_notes=(
                "Provider adapter is not configured; FRED current values cannot replace ALFRED "
                "vintages."
            ),
            fallback_role=ProviderRole.PRIMARY,
            enabled=False,
        ),
        ProviderMetadata(
            provider_id="historical_constituents_import",
            data_domains=frozenset({DataDomain.UNIVERSE_MEMBERSHIP}),
            authority_tier=AuthorityTier.PRIMARY,
            pit_capable=True,
            timestamp_semantics="membership effective and availability timestamps are mandatory",
            adjustment_semantics="not applicable to membership",
            credential_required=False,
            coverage_notes=(
                "Provider-neutral import slot; no current-list substitution is permitted."
            ),
            fallback_role=ProviderRole.PRIMARY,
            enabled=False,
        ),
        ProviderMetadata(
            provider_id="alpaca_optional",
            data_domains=frozenset({DataDomain.EXECUTABLE_OPENS}),
            authority_tier=AuthorityTier.OPTIONAL,
            pit_capable=False,
            timestamp_semantics="provider timestamp and bar/quote timestamp must be retained",
            adjustment_semantics=(
                "provider-specific; cross-check only unless a certified historical contract is "
                "bound"
            ),
            credential_required=True,
            coverage_notes=(
                "Optional configured execution cross-check; no account or broker submission "
                "authority."
            ),
            fallback_role=ProviderRole.OPTIONAL,
            enabled=False,
        ),
    )
    registry = ProviderRegistry()
    for descriptor in descriptors:
        registry.register(_MetadataOnlyAdapter(descriptor))
    return registry


def authority_status_document() -> dict[str, object]:
    """Machine-readable source posture without contacting any provider.

    The report deliberately says *declared authority* rather than certifying a
    dataset.  A provider being listed or enabled cannot change ROUND74's
    historical-data certification by itself.
    """

    registry = default_provider_registry()
    policies = default_authority_policy()
    resolutions = tuple(registry.resolve(policy) for policy in policies)
    return {
        "schema_version": "ROUND80-DATA-AUTHORITY-v1",
        "providers": [
            {
                "provider_id": item.provider_id,
                "data_domains": sorted(domain.value for domain in item.data_domains),
                "authority_tier": item.authority_tier.value,
                "pit_capable": item.pit_capable,
                "timestamp_semantics": item.timestamp_semantics,
                "adjustment_semantics": item.adjustment_semantics,
                "credential_required": item.credential_required,
                "coverage_notes": item.coverage_notes,
                "fallback_role": item.fallback_role.value,
                "enabled": item.enabled,
            }
            for item in registry.metadata()
        ],
        "domain_resolutions": [
            {
                "domain": item.domain.value,
                "status": item.status.value,
                "providers": [provider.provider_id for provider in item.providers],
                "blockers": list(item.blockers),
                "warnings": list(item.warnings),
            }
            for item in resolutions
        ],
        "certification_boundary": (
            "DECLARED_PROVIDER_AUTHORITY_ONLY: operational adapters and source metadata "
            "do not certify PIT, survivorship, corporate-action, benchmark, tradability, "
            "or locked-OOS evidence. Bind an immutable external package before PASS."
        ),
    }
