"""ROUND24 AI Chinese brief service (B3, B7, B8).

Orchestrates: quant facts -> cache lookup -> optional DeepSeek call ->
strict schema validation -> quarantine on failure -> deterministic fallback.
The Classical pipeline result is never modified by this service.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from personal_alpha_terminal.ai_advisory.cache import BriefCache, BriefCacheKey
from personal_alpha_terminal.ai_advisory.deterministic import build_deterministic_brief
from personal_alpha_terminal.ai_advisory.grounding import (
    GROUNDING_OK,
    GROUNDING_QUARANTINED,
    validate_semantic_grounding,
)
from personal_alpha_terminal.ai_advisory.llm import (
    BRIEF_STATUS_OK,
    BriefCallOutcome,
    call_deepseek_brief,
)
from personal_alpha_terminal.ai_advisory.schemas import (
    PRODUCTION_INFLUENCE,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    validate_brief,
)

SCHEMA_HINT = json.dumps(
    {
        "schema_version": SCHEMA_VERSION,
        "summary": "string",
        "market_interpretation": "string",
        "portfolio_interpretation": "string",
        "action_explanations": [
            {
                "symbol": "string",
                "quant_alpha": "string|null",
                "trend": "string|null",
                "volatility": "string|null",
                "risk_target": "string|null",
                "liquidity": "string|null",
                "portfolio_role": "string|null",
                "pit_events": "string|null",
                "ai_interpretation": "string",
                "evidence_refs": ["string"],
            }
        ],
        "event_risks": ["string"],
        "portfolio_risks": ["string"],
        "contrarian_view": "string",
        "uncertainties": ["string"],
        "data_gaps": ["string"],
    },
    ensure_ascii=False,
)


@dataclass(frozen=True, slots=True)
class AiBriefResult:
    run_id: str
    model: str
    prompt_version: str
    llm_status: str
    source: str
    brief: dict[str, Any]
    cache_hit: bool
    llm_call_outcome: BriefCallOutcome | None
    generated_at: datetime
    production_influence: str = PRODUCTION_INFLUENCE
    semantic_grounding_status: str = GROUNDING_OK
    semantic_grounding_issues: tuple[str, ...] = ()

    def document(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "llm_status": self.llm_status,
            "source": self.source,
            "brief": self.brief,
            "cache_hit": self.cache_hit,
            "llm_call": (
                {
                    "status": self.llm_call_outcome.status,
                    "error": self.llm_call_outcome.error,
                    "latency_ms": self.llm_call_outcome.latency_ms,
                    "prompt_tokens": self.llm_call_outcome.prompt_tokens,
                    "completion_tokens": self.llm_call_outcome.completion_tokens,
                    "estimated_cost_usd": self.llm_call_outcome.estimated_cost_usd,
                }
                if self.llm_call_outcome is not None
                else None
            ),
            "generated_at": self.generated_at.isoformat(),
            "production_influence": self.production_influence,
            "semantic_grounding_status": self.semantic_grounding_status,
            "semantic_grounding_issues": list(self.semantic_grounding_issues),
        }


class AiBriefService:
    """Generates the Chinese advisory brief without ever touching weights."""

    def __init__(self, cache: BriefCache | None = None) -> None:
        self.cache = cache or BriefCache()

    def generate(
        self,
        *,
        cache_key: BriefCacheKey,
        facts: dict[str, Any],
        model: str,
        provider_factory: Callable[[], Any] | None,
        now: datetime | None = None,
    ) -> AiBriefResult:
        generated_at = now or datetime.now(UTC)
        if generated_at.tzinfo is None:
            raise ValueError("brief generated_at must be timezone-aware")
        allowed_symbols = frozenset(facts.get("allowed_action_symbols", []))
        cached = self.cache.read(cache_key)
        if cached is not None:
            payload = cached.get("brief")
            ok, error = validate_brief(payload, allowed_symbols=allowed_symbols)
            grounding_ok, grounding_issues = validate_semantic_grounding(
                cast(dict[str, Any], payload), facts
            )
            if ok and grounding_ok:
                return AiBriefResult(
                    run_id=cache_key.run_id,
                    model=model,
                    prompt_version=PROMPT_VERSION,
                    llm_status=str(cached.get("llm_status", "PASS")),
                    source=str(cached.get("source", "CACHED")),
                    brief=cast(dict[str, Any], payload),
                    cache_hit=True,
                    llm_call_outcome=None,
                    generated_at=generated_at,
                    semantic_grounding_status=GROUNDING_OK,
                )
            self.cache.quarantine(
                cache_key,
                reason=(
                    f"cached brief failed re-validation: {error}; "
                    f"semantic grounding: {grounding_issues}"
                ),
                raw=None,
            )
        outcome: BriefCallOutcome | None = None
        brief: dict[str, Any] | None = None
        llm_status = "PASS_DEGRADED"
        source = "RULE_BASED_DETERMINISTIC"
        if provider_factory is not None:
            outcome = call_deepseek_brief(
                provider_factory=provider_factory,
                model=model,
                facts=facts,
                schema_hint=SCHEMA_HINT,
                allowed_symbols=allowed_symbols,
            )
            if outcome.status == BRIEF_STATUS_OK and outcome.payload is not None:
                brief = outcome.payload
                llm_status = "PASS"
                source = "DEEPSEEK_JSON"
                self.cache.write(
                    cache_key,
                    {
                        "brief": brief,
                        "llm_status": llm_status,
                        "source": source,
                        "model": model,
                    },
                )
            elif outcome.payload is not None or outcome.error is not None:
                self.cache.quarantine(
                    cache_key,
                    reason=(
                        f"LLM brief {outcome.status}: "
                        f"{outcome.error or 'unusable payload'}"
                    ),
                    raw=(
                        json.dumps(outcome.payload, ensure_ascii=False, default=str)
                        if outcome.payload is not None
                        else None
                    ),
                )
        if brief is None:
            brief = build_deterministic_brief(facts)
        grounding_ok, grounding_issues = validate_semantic_grounding(brief, facts)
        if source == "DEEPSEEK_JSON" and not grounding_ok:
            # ROUND25 P0: a semantically polluted LLM brief is quarantined and
            # replaced by the deterministic fallback; it is never displayed
            # unmarked.
            self.cache.quarantine(
                cache_key,
                reason=(
                    f"{GROUNDING_QUARANTINED}: "
                    + "; ".join(grounding_issues)
                ),
                raw=json.dumps(brief, ensure_ascii=False, default=str),
            )
            brief = build_deterministic_brief(facts)
            llm_status = "PASS_DEGRADED"
            source = GROUNDING_QUARANTINED
        ok, error = validate_brief(brief, allowed_symbols=allowed_symbols)
        if not ok:
            self.cache.quarantine(cache_key, reason=f"fallback schema violation: {error}", raw=None)
            brief = {
                "schema_version": SCHEMA_VERSION,
                "summary": "研判生成失败,已隔离(AI_BRIEF_QUARANTINED);量化结果不受影响。",
                "market_interpretation": "不适用",
                "portfolio_interpretation": "不适用",
                "action_explanations": [],
                "event_risks": [],
                "portfolio_risks": [],
                "contrarian_view": "不适用",
                "uncertainties": [],
                "data_gaps": [],
            }
            llm_status = "PASS_DEGRADED"
            source = "AI_BRIEF_QUARANTINED"
        return AiBriefResult(
            run_id=cache_key.run_id,
            model=model,
            prompt_version=PROMPT_VERSION,
            llm_status=llm_status,
            source=source,
            brief=brief,
            cache_hit=False,
            llm_call_outcome=outcome,
            generated_at=generated_at,
            semantic_grounding_status=(
                GROUNDING_OK if grounding_ok else GROUNDING_QUARANTINED
            ),
            semantic_grounding_issues=tuple(grounding_issues),
        )
