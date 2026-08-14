"""ROUND24 deterministic instrument classification master.

Instrument classification is deterministic: it combines the curated ETF
catalog (``data/etf_catalog.json``) with the Nasdaq symbol directory
(``ETF`` flag column).  It never consults an LLM and never guesses a
security type from a symbol pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentSecurityMasterRecord,
    CurrentSecurityType,
)


class InstrumentType(StrEnum):
    """Security master instrument taxonomy (ROUND24 C1)."""

    COMMON_STOCK = "COMMON_STOCK"
    ETF = "ETF"
    ETN = "ETN"
    ADR = "ADR"
    PREFERRED = "PREFERRED"
    WARRANT = "WARRANT"
    RIGHT = "RIGHT"
    OTHER = "OTHER"


class TradabilityTier(StrEnum):
    """Whether an instrument may enter tradable sleeves (ROUND24 C3)."""

    STANDARD_TRADABLE = "STANDARD_TRADABLE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BLOCKED_BY_COMPLEX_PRODUCT_POLICY = "BLOCKED_BY_COMPLEX_PRODUCT_POLICY"


class BenchmarkRole(StrEnum):
    """Benchmark/tradable identity separation (ROUND24 C2)."""

    NONE = "NONE"
    TRADABLE = "TRADABLE"
    BENCHMARK = "BENCHMARK"
    BOTH = "BOTH"
    REGIME_PROXY = "REGIME_PROXY"
    RISK_REFERENCE = "RISK_REFERENCE"


class Sleeve(StrEnum):
    """Portfolio sleeve assignment (ROUND24 C4)."""

    NONE = "NONE"
    EQUITY_ALPHA = "EQUITY_ALPHA"
    ETF_CORE = "ETF_CORE"
    ETF_TACTICAL = "ETF_TACTICAL"


BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class InstrumentClassification:
    symbol: str
    instrument_type: InstrumentType
    is_etf: bool
    is_leveraged: bool
    is_inverse: bool
    asset_class: str
    tradability_tier: TradabilityTier
    benchmark_role: BenchmarkRole
    etf_category: str | None
    sleeve: Sleeve
    benchmark_policy: str
    classification_source: str
    classification_reason: str | None = None
    cataloged: bool = False
    effective_date: date | None = None

    def document(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "instrument_type": self.instrument_type.value,
            "is_etf": self.is_etf,
            "is_leveraged": self.is_leveraged,
            "is_inverse": self.is_inverse,
            "asset_class": self.asset_class,
            "tradability_tier": self.tradability_tier.value,
            "benchmark_role": self.benchmark_role.value,
            "etf_category": self.etf_category,
            "sleeve": self.sleeve.value,
            "benchmark_policy": self.benchmark_policy,
            "classification_source": self.classification_source,
            "classification_reason": self.classification_reason,
            "cataloged": self.cataloged,
            "effective_date": (
                self.effective_date.isoformat() if self.effective_date else None
            ),
        }


def _directory_type_to_instrument_type(
    security_type: CurrentSecurityType,
) -> InstrumentType:
    mapping = {
        CurrentSecurityType.COMMON_STOCK: InstrumentType.COMMON_STOCK,
        CurrentSecurityType.ETF: InstrumentType.ETF,
        CurrentSecurityType.ETN: InstrumentType.ETN,
        CurrentSecurityType.ADR: InstrumentType.ADR,
        CurrentSecurityType.PREFERRED: InstrumentType.PREFERRED,
        CurrentSecurityType.WARRANT: InstrumentType.WARRANT,
        CurrentSecurityType.RIGHT: InstrumentType.RIGHT,
    }
    return mapping.get(security_type, InstrumentType.OTHER)


def classify_instrument(
    symbol: str,
    *,
    directory_record: CurrentSecurityMasterRecord | None,
    catalog_entry: dict[str, object] | None,
    effective_date: date | None = None,
) -> InstrumentClassification:
    """Classify one symbol deterministically.

    - A curated catalog entry decides every ETF attribute (category, asset
      class, sleeve, leverage/inverse flags, benchmark policy, tier).
    - An exchange-listed ETF that is not in the catalog is
      ``RESEARCH_ONLY`` (``UNCLASSIFIED_ETF``): fail-closed, because the
      directory alone cannot prove it is not leveraged/inverse.
    - A non-ETF directory row keeps its deterministic directory type.
    """

    directory_is_etf = bool(directory_record and directory_record.is_etf)
    if catalog_entry is not None:
        complex_product = bool(catalog_entry.get("complex_product", False))
        return InstrumentClassification(
            symbol=symbol,
            instrument_type=InstrumentType.ETF,
            is_etf=True,
            is_leveraged=bool(catalog_entry.get("leveraged", False)),
            is_inverse=bool(catalog_entry.get("inverse", False)),
            asset_class=str(catalog_entry.get("asset_class", "UNCLASSIFIED")),
            tradability_tier=(
                TradabilityTier.BLOCKED_BY_COMPLEX_PRODUCT_POLICY
                if complex_product
                else TradabilityTier.STANDARD_TRADABLE
            ),
            benchmark_role=BenchmarkRole(
                str(catalog_entry.get("benchmark_role", "NONE"))
            ),
            etf_category=str(catalog_entry.get("category")),
            sleeve=Sleeve(str(catalog_entry.get("sleeve", "NONE"))),
            benchmark_policy=str(
                catalog_entry.get("benchmark_policy", BENCHMARK_UNAVAILABLE)
            ),
            classification_source="ETF_CATALOG_V1",
            classification_reason=(
                "BLOCKED_BY_COMPLEX_PRODUCT_POLICY" if complex_product else None
            ),
            cataloged=True,
            effective_date=effective_date,
        )
    if directory_is_etf:
        return InstrumentClassification(
            symbol=symbol,
            instrument_type=InstrumentType.ETF,
            is_etf=True,
            is_leveraged=False,
            is_inverse=False,
            asset_class="UNCLASSIFIED_ETF",
            tradability_tier=TradabilityTier.RESEARCH_ONLY,
            benchmark_role=BenchmarkRole.NONE,
            etf_category=None,
            sleeve=Sleeve.NONE,
            benchmark_policy=BENCHMARK_UNAVAILABLE,
            classification_source="SYMBOL_DIRECTORY_V1",
            classification_reason="UNCLASSIFIED_ETF",
            cataloged=False,
            effective_date=effective_date,
        )
    if directory_record is None:
        return InstrumentClassification(
            symbol=symbol,
            instrument_type=InstrumentType.OTHER,
            is_etf=False,
            is_leveraged=False,
            is_inverse=False,
            asset_class="UNCLASSIFIED",
            tradability_tier=TradabilityTier.RESEARCH_ONLY,
            benchmark_role=BenchmarkRole.NONE,
            etf_category=None,
            sleeve=Sleeve.NONE,
            benchmark_policy=BENCHMARK_UNAVAILABLE,
            classification_source="SYMBOL_DIRECTORY_V1",
            classification_reason="NOT_IN_DIRECTORY",
            cataloged=False,
            effective_date=effective_date,
        )
    return InstrumentClassification(
        symbol=symbol,
        instrument_type=_directory_type_to_instrument_type(
            directory_record.security_type
        ),
        is_etf=False,
        is_leveraged=False,
        is_inverse=False,
        asset_class="US_EQUITY",
        tradability_tier=TradabilityTier.STANDARD_TRADABLE,
        benchmark_role=BenchmarkRole.NONE,
        etf_category=None,
        sleeve=Sleeve.EQUITY_ALPHA,
        benchmark_policy=BENCHMARK_UNAVAILABLE,
        classification_source="SYMBOL_DIRECTORY_V1",
        cataloged=False,
        effective_date=effective_date,
    )
