"""ROUND29: source-grounded company dossiers for formal action symbols.

Company facts are current-only operational metadata. They are never written
into historical PIT tables and never used by the formal optimizer. LLM text
must not invent company facts; every displayed value carries source, as_of,
published/filed time when available, and an evidence id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from personal_alpha_terminal.application.current_exposure import size_bucket


@dataclass(frozen=True, slots=True)
class CompanyDossier:
    ticker: str
    company_name: str
    exchange: str | None
    sector: str | None
    industry: str | None
    sic: str | None
    market_cap: float | None
    size_class: str
    business_summary: str
    products: tuple[str, ...]
    revenue_sources: tuple[str, ...]
    headquarters: str | None
    recent_filings: tuple[dict[str, str], ...]
    recent_news: tuple[dict[str, str], ...]
    price_trend: dict[str, float] | None
    source_evidence: dict[str, str] = field(default_factory=dict)
    as_of: str = ""
    status: str = "UNAVAILABLE"

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["products"] = list(payload["products"])
        payload["revenue_sources"] = list(payload["revenue_sources"])
        payload["recent_filings"] = list(payload["recent_filings"])
        payload["recent_news"] = list(payload["recent_news"])
        return payload


def _info_value(info: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if info.get(key) not in (None, "", "N/A"):
            return info[key]
    return None


def build_company_dossiers(
    *,
    symbols: tuple[str, ...],
    current_exposure: dict[str, Any] | None = None,
    info_fetcher: Callable[[str], dict[str, Any]] | None = None,
    as_of: datetime | None = None,
) -> tuple[CompanyDossier, ...]:
    """Build current-only dossiers with explicit source/evidence metadata."""

    exposure = current_exposure or {}
    size_observations = exposure.get("market_cap_observations")
    if not isinstance(size_observations, dict):
        size_exposure = exposure.get("size_exposure")
        size_observations = (
            size_exposure.get("market_cap_observations")
            if isinstance(size_exposure, dict)
            else None
        )
        if not isinstance(size_observations, dict):
            size_observations = {}
    sector_acquisition = exposure.get("sector_acquisition")
    sector_statuses = (
        sector_acquisition.get("symbol_status")
        if isinstance(sector_acquisition, dict)
        else None
    )
    if not isinstance(sector_statuses, dict):
        sector_statuses = {}
    reference = as_of or datetime.now(UTC)
    dossiers: list[CompanyDossier] = []
    for symbol in symbols:
        info: dict[str, Any] = {}
        source_evidence: dict[str, str] = {}
        if info_fetcher is not None:
            try:
                fetched = info_fetcher(symbol)
                if isinstance(fetched, dict):
                    if any(
                        fetched.get(key) not in (None, "", "N/A")
                        for key in (
                            "longName",
                            "shortName",
                            "sector",
                            "industry",
                            "marketCap",
                            "longBusinessSummary",
                            "exchange",
                        )
                    ):
                        info = fetched
                        source_evidence["company_profile"] = "YAHOO_FINANCE_CURRENT_ONLY"
            except (KeyError, OSError, RuntimeError, TypeError, ValueError):
                info = {}
        size_obs = size_observations.get(symbol)
        if isinstance(size_obs, dict):
            market_cap = (
                float(size_obs["market_cap"])
                if isinstance(size_obs.get("market_cap"), (int, float))
                else None
            )
            source_evidence["market_cap"] = str(
                size_obs.get("market_cap_calculation", "CURRENT_ONLY")
            )
        else:
            market_cap = (
                float(info["marketCap"])
                if isinstance(info.get("marketCap"), (int, float))
                else None
            )
            if market_cap is not None:
                source_evidence["market_cap"] = "YAHOO_FINANCE_CURRENT_ONLY"
        company_name = str(
            _info_value(info, "longName", "shortName") or "UNAVAILABLE"
        )
        sector = (
            str(_info_value(info, "sector") or sector_statuses.get(symbol) or "UNKNOWN")
        )
        industry = str(_info_value(info, "industry") or "UNAVAILABLE")
        sic = (
            str(info["sic"])
            if isinstance(info.get("sic"), (int, str))
            else None
        )
        business_summary = str(
            _info_value(info, "longBusinessSummary") or "UNAVAILABLE"
        )
        raw_products = info.get("products")
        products = tuple(
            str(item)
            for item in (raw_products or ())
            if isinstance(raw_products, (list, tuple))
        )
        headquarters_parts = [
            str(value)
            for value in (
                _info_value(info, "city"),
                _info_value(info, "state"),
                _info_value(info, "country"),
            )
            if value
        ]
        price_trend: dict[str, float] | None = None
        trend = info.get("52WeekChange")
        if isinstance(trend, (int, float)):
            price_trend = {"52_week_change": float(trend)}
        dossiers.append(
            CompanyDossier(
                ticker=symbol,
                company_name=company_name,
                exchange=str(_info_value(info, "exchange") or "UNAVAILABLE"),
                sector=sector,
                industry=industry,
                sic=sic,
                market_cap=market_cap,
                size_class=size_bucket(market_cap),
                business_summary=business_summary,
                products=products,
                revenue_sources=(),
                headquarters=", ".join(headquarters_parts) or None,
                recent_filings=(),
                recent_news=(),
                price_trend=price_trend,
                source_evidence=source_evidence,
                as_of=reference.isoformat(),
                status="CURRENT_ONLY" if source_evidence else "UNAVAILABLE",
            )
        )
    return tuple(dossiers)
