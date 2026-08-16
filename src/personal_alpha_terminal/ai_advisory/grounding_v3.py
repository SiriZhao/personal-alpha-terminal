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


def _percent_claims_excluding_lookbehind(
    text: str, labels: tuple[str, ...], excluded_prefixes: tuple[str, ...]
) -> list[float]:
    """Return percentage claims only when the label is not preceded by ``占``.

    This prevents a claim like ``占总权重 5.58%`` (a cost share) from being
    read as the total portfolio gross weight.
    """
    values: list[float] = []
    for label in labels:
        for match in re.finditer(re.escape(label), text):
            prefix = text[max(0, match.start() - 2) : match.start()]
            if any(excluded in prefix for excluded in excluded_prefixes):
                continue
            window = text[match.end() : match.end() + 100]
            clause = re.split(r"[,;。，；\n]", window, maxsplit=1)[0]
            found = re.findall(r"(\d+(?:\.\d+)?)\s*%", clause)
            if found:
                values.append(float(found[0]))
    return values


def _symbol_risk_claims(
    text: str, facts_v3: dict[str, Any]
) -> list[tuple[str, float, float]]:
    """Validate symbol-scoped risk-contribution claims against formal facts."""
    claims: list[tuple[str, float, float]] = []
    formal = facts_v3.get("FORMAL_ACTIONS") or []
    for item in formal:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "")
        risk_fact = item.get("risk_contribution") or {}
        expected = risk_fact.get("value")
        if not symbol or not isinstance(expected, (int, float)):
            continue
        pattern = re.compile(
            re.escape(symbol) + r"[^,;。，；\n]{0,50}风险贡献"
        )
        for match in pattern.finditer(text):
            window = text[match.start() : match.start() + 90]
            clause = re.split(r"[,;。，；\n]", window, maxsplit=1)[0]
            found = re.findall(r"(\d+(?:\.\d+)?)\s*%", clause)
            if found:
                claims.append((symbol, float(found[0]), float(expected)))
    return claims


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
        for value in _percent_claims(text, ("现金权重", "现金比例", "现金占比", "cash weight")):
            if abs(value / 100.0 - cash_weight) > 0.05:
                issues.append(
                    f"stated cash {value}% contradicts fact portfolio.cash_weight "
                    f"{cash_weight * 100:.2f}%"
                )
    gross = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "gross_weight")
    if isinstance(gross, (int, float)) and not isinstance(gross, bool) and gross > 0:
        for value in _percent_claims_excluding_lookbehind(
            text,
            ("总敞口", "组合总权重", "总权重", "gross exposure"),
            ("占",),
        ):
            if abs(value / 100.0 - gross) > 0.05:
                issues.append(
                    f"stated gross {value}% contradicts fact portfolio.gross_weight "
                    f"{gross * 100:.2f}%"
                )
    top5_weight = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "top5_weight")
    if isinstance(top5_weight, (int, float)):
        for value in _percent_claims(
            text, ("前五大持仓合计权重", "前五持仓合计权重", "合计权重")
        ):
            if abs(value / 100.0 - top5_weight) > 0.05:
                issues.append(
                    f"stated top-5 weight {value}% contradicts fact portfolio.top5_weight "
                    f"{top5_weight * 100:.2f}%"
                )
    top5_risk = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "top5_risk_contribution")
    if isinstance(top5_risk, (int, float)):
        for value in _percent_claims(text, ("前五大风险贡献合计", "风险贡献合计", "合计风险贡献")):
            if abs(value / 100.0 - top5_risk) > 0.05:
                issues.append(
                    f"stated top-5 risk contribution {value}% contradicts fact "
                    f"portfolio.top5_risk_contribution {top5_risk * 100:.2f}%"
                )
    for symbol, value, expected in _symbol_risk_claims(text, facts_v3):
        if abs(value / 100.0 - expected) > 0.05:
            issues.append(
                f"stated {symbol} risk contribution {value}% contradicts formal fact "
                f"{expected * 100:.2f}%"
            )
    cost_share = _facts_v3_value(facts_v3, "PORTFOLIO_FACTS", "cost_pct_of_gross")
    if isinstance(cost_share, (int, float)):
        for value in _percent_claims(text, ("占总权重", "占组合总权重", "占正式总权重")):
            if abs(value / 100.0 - cost_share) > 0.05:
                issues.append(
                    f"stated cost share {value}% contradicts fact "
                    f"portfolio.cost_pct_of_gross {cost_share * 100:.2f}%"
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
