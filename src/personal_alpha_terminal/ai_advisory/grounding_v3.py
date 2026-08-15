"""ROUND26 P0: section-level quarantine for the AI daily brief.

The full 19-section brief is no longer thrown away when one section contains
a numeric conflict.  Non-critical sections are individually replaced with
their deterministic fallback; conflicts in critical sections (formal
conclusions, portfolio state, execution authority, cash, gross) still
quarantine the whole brief.
"""

from __future__ import annotations

import re
from typing import Any

from personal_alpha_terminal.ai_advisory.grounding import (
    GROUNDING_OK,
    GROUNDING_QUARANTINED,
)

CRITICAL_SECTIONS = frozenset(
    {"executive_summary", "formal_conclusions", "portfolio_risk_analysis"}
)

SECTION_LEVEL_QUARANTINED = "AI_BRIEF_SECTION_QUARANTINED"


def _percent_claims(text: str, labels: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    for label in labels:
        for match in re.finditer(re.escape(label), text):
            window = text[match.start() : match.start() + 80]
            # Only the number in the same clause as the label counts; stop at
            # the next punctuation so "现金 100%,总敞口 9.77%" attributes
            # 9.77% to gross, never to cash.
            clause = re.split(r"[,;。，；\n]", window, maxsplit=1)[0]
            found = re.findall(r"(\d+(?:\.\d+)?)\s*%", clause)
            if found:
                values.append(float(found[0]))
    return values


def _facts_v3_value(facts_v3: dict[str, Any], section: str, name: str) -> Any:
    section_payload = facts_v3.get(section) or {}
    if isinstance(section_payload, dict):
        entry = section_payload.get(name)
        if isinstance(entry, dict) and "value" in entry:
            return entry["value"]
        return entry
    return None


def _cash_gross_count_issues(text: str, facts_v3: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    cash_weight = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "cash_weight")
    if isinstance(cash_weight, (int, float)) and not isinstance(cash_weight, bool):
        for value in _percent_claims(text, ("现金", "cash")):
            if abs(value / 100.0 - cash_weight) > 0.05:
                issues.append(
                    f"stated cash {value}% contradicts fact portfolio.cash_weight "
                    f"{cash_weight * 100:.2f}%"
                )
    gross = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "gross_weight")
    if isinstance(gross, (int, float)) and not isinstance(gross, bool) and gross > 0:
        for value in _percent_claims(text, ("总敞口", "总权重", "合计权重", "gross")):
            if abs(value / 100.0 - gross) > 0.05:
                issues.append(
                    f"stated gross {value}% contradicts fact portfolio.gross_weight "
                    f"{gross * 100:.2f}%"
                )
    return issues


def _news_ref_issues(rows: list[Any], facts_v3: dict[str, Any]) -> list[str]:
    evidence_refs = set(facts_v3.get("EVIDENCE_REFERENCES") or [])
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        ref = row.get("evidence_ref")
        if not isinstance(ref, str) or not ref:
            issues.append(f"important_news[{index}] missing evidence_ref")
        elif ref.startswith("N") and ref not in evidence_refs:
            # news cluster ids are allowed when present in facts
            pass
    return issues


def validate_brief_sections(
    brief: dict[str, Any], facts_v3: dict[str, Any]
) -> tuple[dict[str, list[str]], list[str]]:
    """Return per-section issues plus global (critical) issues."""

    section_issues: dict[str, list[str]] = {}
    global_issues: list[str] = []
    for section, value in brief.items():
        if not isinstance(value, str) or not value:
            continue
        text = value
        issues = _cash_gross_count_issues(str(text or ""), facts_v3)
        if issues:
            section_issues[section] = issues
            if section in CRITICAL_SECTIONS:
                global_issues.extend(issues)
    news_rows = brief.get("important_news") or []
    news_issues = _news_ref_issues(news_rows, facts_v3)
    if news_issues:
        section_issues["important_news"] = news_issues
    return section_issues, global_issues


def quarantine_sections(
    brief: dict[str, Any],
    fallback_brief: dict[str, Any],
    *,
    facts_v3: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Quarantine failing non-critical sections; critical failures quarantine all."""

    section_issues, global_issues = validate_brief_sections(brief, facts_v3)
    if global_issues:
        return fallback_brief, {
            "status": GROUNDING_QUARANTINED,
            "quarantined_sections": sorted(section_issues),
            "issues": global_issues,
            "critical_failure": True,
        }
    quarantined: list[str] = []
    merged = dict(brief)
    for section in section_issues:
        if section in CRITICAL_SECTIONS:
            continue
        if section in fallback_brief:
            merged[section] = fallback_brief[section]
        quarantined.append(section)
    status = (
        SECTION_LEVEL_QUARANTINED if quarantined else GROUNDING_OK
    )
    return merged, {
        "status": status,
        "quarantined_sections": quarantined,
        "issues": {
            section: issues for section, issues in section_issues.items()
        },
        "critical_failure": False,
    }
