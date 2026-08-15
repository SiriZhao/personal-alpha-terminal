"""ROUND26 P0: OFFICIAL MACRO NEWS acquisition.

Real acquisition against official, keyless public endpoints:

* Federal Reserve press releases (RSS)
* BLS public API v2 (CPI/PPI/employment series)
* U.S. Treasury press RSS

BEA and SEC EDGAR remain provider-interface targets (BEA needs a key; SEC
EDGAR is covered by the separate PIT-gated acquisition path).

PIT rule (hard constraint): ``published_at`` decides decision eligibility,
never ``acquired_at``.  Items published after the decision cutoff are usable
only by the pre-execution risk check and can never recompute alpha.
No model-generated macro content is ever persisted.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from personal_alpha_terminal.intelligence.market_news import (
    NewsItem,
    NewsSourceTier,
)

OFFICIAL_MACRO_NEWS_UNAVAILABLE = "OFFICIAL_MACRO_NEWS_UNAVAILABLE"

_USER_AGENT = "personal-alpha-terminal/1.0 (personal research terminal; contact: local)"


def _http_get(url: str, *, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return str(payload.decode(charset, errors="replace"))


def _parse_rfc2822(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _rss_items(
    payload: str,
    *,
    source: str,
    item_tag: str = "item",
    title_tag: str = "title",
    pubdate_tag: str = "pubDate",
    description_tag: str = "description",
    max_items: int = 20,
) -> tuple[NewsItem, ...]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ()
    items: list[NewsItem] = []
    for node in root.iter(item_tag):
        title_node = node.find(title_tag)
        date_node = node.find(pubdate_tag)
        description_node = node.find(description_tag)
        if title_node is None or date_node is None:
            continue
        title = (title_node.text or "").strip()
        published_raw = (date_node.text or "").strip()
        if not title or not published_raw:
            continue
        try:
            published_at = _parse_rfc2822(published_raw)
        except (TypeError, ValueError):
            continue
        summary = (
            (description_node.text or "").strip()[:500]
            if description_node is not None
            else ""
        )
        retrieved_at = datetime.now(UTC)
        import hashlib as _hashlib

        content = f"{title}|{published_at.isoformat()}"
        content_hash = _hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
        items.append(
            NewsItem(
                news_id=f"macro-{source}-{content_hash[:12]}",
                source=f"official-{source}",
                source_tier=NewsSourceTier.TIER1_OFFICIAL.value,
                headline=title,
                summary=summary,
                published_at=published_at,
                retrieved_at=retrieved_at,
                available_at=published_at,
                url_hash=content_hash,
                content_hash=content_hash,
                topics=("MACRO",),
                country="US",
                language="en",
                evidence_state="RAW_OFFICIAL",
            )
        )
        if len(items) >= max_items:
            break
    return tuple(items)


class FederalReservePressProvider:
    name = "federal-reserve"
    url = "https://www.federalreserve.gov/feeds/press_all.xml"

    def fetch(self, *, max_items: int = 20) -> tuple[NewsItem, ...]:
        return _rss_items(_http_get(self.url), source="fed", max_items=max_items)


class USTreasuryPressProvider:
    name = "us-treasury"
    url = "https://home.treasury.gov/news/press-releases/feed"

    def fetch(self, *, max_items: int = 20) -> tuple[NewsItem, ...]:
        return _rss_items(_http_get(self.url), source="treasury", max_items=max_items)


class BLSPublicApiProvider:
    """BLS public API v2 (keyless access is rate-limited but functional)."""

    name = "bls"
    url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(self, series: tuple[str, ...] = ("CUSR0000SA0", "CES0000000001")) -> None:
        self.series = series

    def fetch(self, *, max_items: int = 20) -> tuple[NewsItem, ...]:
        payload = json.dumps(
            {"seriesid": list(self.series), "startyear": "2020", "endyear": "2030"}
        )
        request = urllib.request.Request(
            self.url,
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        with urllib.request.urlopen(request, timeout=30.0) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
        items: list[NewsItem] = []
        retrieved_at = datetime.now(UTC)
        for series in body.get("Results", {}).get("series", []):
            series_id = series.get("seriesID", "")
            for observation in series.get("data", [])[:max_items]:
                year = observation.get("year")
                period = observation.get("period")  # e.g. M07
                value = observation.get("value")
                if not year or not period:
                    continue
                match = re.match(r"M(\d+)", period)
                _ = int(match.group(1)) if match else 1
                # The public BLS endpoint does not expose the release date of
                # each observation.  The publication date is therefore marked
                # UNAVAILABLE and the item becomes PIT-visible only at
                # retrieval time (conservative: it can never be used as
                # decision-safe evidence for an earlier cutoff).
                title = f"BLS {series_id} {period} {year}: value {value}"
                import hashlib as _hashlib

                content_hash = _hashlib.sha256(title.encode("utf-8")).hexdigest()[:32]
                items.append(
                    NewsItem(
                        news_id=f"macro-bls-{content_hash[:12]}",
                        source="official-bls",
                        source_tier=NewsSourceTier.TIER1_OFFICIAL.value,
                        headline=title,
                        summary=f"Official BLS series {series_id} observation for {period} {year}.",
                        published_at=retrieved_at,
                        retrieved_at=retrieved_at,
                        available_at=retrieved_at,
                        url_hash=content_hash,
                        content_hash=content_hash,
                        topics=("MACRO", "BLS"),
                        country="US",
                        language="en",
                        evidence_state="PUBLICATION_DATE_UNAVAILABLE_AVAILABLE_AT_RETRIEVAL",
                    )
                )
        return tuple(items)


class OfficialMacroAcquisition:
    """Coordinates official providers and reports honest availability."""

    def __init__(self, http_get: Any | None = None) -> None:
        self._http_get = http_get

    def acquire(self) -> dict[str, object]:
        providers = (
            FederalReservePressProvider(),
            USTreasuryPressProvider(),
            BLSPublicApiProvider(),
        )
        items: list[NewsItem] = []
        statuses: dict[str, str] = {}
        for provider in providers:
            try:
                fetched = provider.fetch()
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                statuses[provider.name] = f"{provider.name.upper()}_UNAVAILABLE"
                continue
            statuses[provider.name] = "OK" if fetched else "EMPTY"
            items.extend(fetched)
        if not items:
            return {
                "status": OFFICIAL_MACRO_NEWS_UNAVAILABLE,
                "provider_statuses": statuses,
                "items": [],
                "fabricated": False,
            }
        return {
            "status": "OFFICIAL_MACRO_NEWS_OK",
            "provider_statuses": statuses,
            "items": [item.document() for item in items],
            "fabricated": False,
        }
