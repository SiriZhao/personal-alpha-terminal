"""ROUND25 P0 semantic domain isolation (FORMAL / RESEARCH / CONTEXT).

Every instrument shown in the terminal must belong to exactly one of three
domains derived from the real backend state:

* ``FORMAL_ACTIONABLE`` -- survived SIGNAL -> PORTFOLIO -> RISK -> DECISION ->
  EXECUTION and has ``final_decision != NO_ACTION``.  Only these may render
  BUY / SELL / ADD / REDUCE and may enter the formal action list.
* ``RESEARCH_CANDIDATE`` -- ETF sleeve targets, alpha challengers, risk
  overlay candidates.  They may render a research direction, never an order.
* ``CONTEXT_ONLY`` -- benchmarks, news-mentioned securities, macro ETFs and
  market proxies.  They never enter any action table.

The renderer and the AI facts assembly both import this module so the same
classification is applied at every display surface.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any

FORMAL_ACTIONABLE = "FORMAL_ACTIONABLE"
RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
CONTEXT_ONLY = "CONTEXT_ONLY"

# A formal actionable row must carry every one of these fields; a missing
# field makes the row non-renderable as a formal BUY/SELL.  ``instrument_type``
# / ``sleeve`` / ``risk_status`` are display enrichments resolved by the
# backend stage that produced the row (STOCK / EQUITY_ALPHA / gate state);
# fabricating them inside a renderer is forbidden.
FORMAL_REQUIRED_FIELDS: tuple[str, ...] = (
    "symbol",
    "action",
    "current_weight",
    "target_weight",
    "delta_weight",
    "estimated_value",
    "estimated_quantity",
    "estimated_cost",
    "earliest_execution_time",
)

_NO_ACTION_VALUES = frozenset({"NO_ACTION", "NONE", ""})


def is_no_action(action: Any) -> bool:
    """True when the action string means 'no formal decision'."""

    if action is None:
        return True
    return str(action).upper() in _NO_ACTION_VALUES


def formal_required_fields_present(item: dict[str, Any]) -> bool:
    """True when every mandatory formal field exists (None counts as missing)."""

    if not isinstance(item, dict):
        return False
    for field in FORMAL_REQUIRED_FIELDS:
        if field not in item or item[field] is None:
            return False
    return True


def classify_item(item: dict[str, Any]) -> str:
    """Classify one instrument row into a semantic domain.

    The default for anything without positive formal evidence is
    ``RESEARCH_CANDIDATE`` for ETF/multi-sleeve rows and ``CONTEXT_ONLY`` for
    everything else.  A row is only FORMAL_ACTIONABLE when it has a real
    non-NO_ACTION decision plus every required formal field.
    """

    document = row_document(item)
    if document is None:
        return CONTEXT_ONLY
    explicit = str(document.get("domain", ""))
    if explicit in {FORMAL_ACTIONABLE, RESEARCH_CANDIDATE, CONTEXT_ONLY}:
        return explicit
    model_status = str(document.get("model_status", "")).upper()
    if model_status == "RESEARCH_CANDIDATE":
        return RESEARCH_CANDIDATE
    action = document.get("action")
    has_decision = not is_no_action(action)
    if has_decision and formal_required_fields_present(document):
        return FORMAL_ACTIONABLE
    instrument_type = str(document.get("instrument_type", "")).upper()
    if instrument_type == "ETF":
        return RESEARCH_CANDIDATE
    return CONTEXT_ONLY


def row_document(item: Any) -> dict[str, Any] | None:
    """Return a plain dict for a dict row or a dataclass row."""

    if isinstance(item, dict):
        return dict(item)
    if dataclasses.is_dataclass(item) and not isinstance(item, type):
        return dataclasses.asdict(item)
    return None


def formal_action_rows(items: Any) -> tuple[dict[str, Any], ...]:
    """Return only rows that may legally appear in the formal action table."""

    if not isinstance(items, (list, tuple)):
        return ()
    rows: list[dict[str, Any]] = []
    for item in items:
        document = row_document(item)
        if document is None:
            continue
        if classify_item(item) != FORMAL_ACTIONABLE:
            continue
        rows.append(document)
    return tuple(rows)


def research_candidate_rows(items: Any) -> tuple[dict[str, Any], ...]:
    """Return rows that must render inside the research-candidate section."""

    if not isinstance(items, (list, tuple)):
        return ()
    rows: list[dict[str, Any]] = []
    for item in items:
        document = row_document(item)
        if document is not None and classify_item(item) == RESEARCH_CANDIDATE:
            rows.append(document)
    return tuple(rows)


def context_only_rows(items: Any) -> tuple[dict[str, Any], ...]:
    """Return rows that must never enter an action table."""

    if not isinstance(items, (list, tuple)):
        return ()
    rows: list[dict[str, Any]] = []
    for item in items:
        document = row_document(item)
        if document is not None and classify_item(item) == CONTEXT_ONLY:
            rows.append(document)
    return tuple(rows)


def annotate_domain(items: Any, domain: str) -> tuple[dict[str, Any], ...]:
    """Deep-copy items and stamp the explicit semantic domain onto each row."""

    if not isinstance(items, (list, tuple)):
        return ()
    annotated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        copy["domain"] = domain
        annotated.append(copy)
    return tuple(annotated)


def is_finite_metric(value: Any) -> bool:
    """True only for finite numeric metric values.

    Strings, booleans, None, NaN and Inf are all rejected: a renderer must
    receive an actual number with a declared unit before it may format it.
    """

    if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)
