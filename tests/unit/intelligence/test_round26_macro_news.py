"""ROUND26 P0: official macro news acquisition tests (no fabrication)."""

from __future__ import annotations

from personal_alpha_terminal.intelligence.macro_news import (
    OFFICIAL_MACRO_NEWS_UNAVAILABLE,
    _parse_rfc2822,
    _rss_items,
)

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Federal Reserve Press Releases</title>
    <item>
      <title>Federal Reserve issues FOMC statement</title>
      <pubDate>Wed, 12 Aug 2026 18:00:00 GMT</pubDate>
      <description>The Federal Reserve maintained the target range.</description>
    </item>
    <item>
      <title>Federal Reserve Board announces reserve bank appointments</title>
      <pubDate>Mon, 10 Aug 2026 14:00:00 GMT</pubDate>
      <description>Appointments announced.</description>
    </item>
  </channel>
</rss>
"""


def test_rss_parsing_produces_tier1_official_items() -> None:
    items = _rss_items(RSS_SAMPLE, source="fed")
    assert len(items) == 2
    assert items[0].source == "official-fed"
    assert items[0].source_tier == "TIER1_OFFICIAL"
    assert items[0].headline.startswith("Federal Reserve issues")
    assert "2026-08-12" in items[0].published_at.isoformat()


def test_rfc2822_parsing_is_utc() -> None:
    parsed = _parse_rfc2822("Wed, 12 Aug 2026 18:00:00 GMT")
    assert parsed.hour == 18
    assert parsed.tzinfo is not None


def test_malformed_rss_yields_empty_not_crash() -> None:
    assert _rss_items("<not-xml", source="fed") == ()


def test_unavailable_status_is_honest() -> None:
    assert OFFICIAL_MACRO_NEWS_UNAVAILABLE == "OFFICIAL_MACRO_NEWS_UNAVAILABLE"
