"""ROUND24 AI Chinese advisory package (PHASE B).

The AI explains deterministic quant output in natural Chinese.  It has no
trade authority, no target-weight authority and no BUY/SELL authority.
"""

from personal_alpha_terminal.ai_advisory.cache import (
    DEFAULT_CACHE_ROOT,
    BriefCache,
    BriefCacheKey,
)
from personal_alpha_terminal.ai_advisory.deterministic import (
    build_deterministic_brief,
)
from personal_alpha_terminal.ai_advisory.facts import build_quant_facts
from personal_alpha_terminal.ai_advisory.llm import (
    BRIEF_STATUS_API_ERROR,
    BRIEF_STATUS_EMPTY,
    BRIEF_STATUS_OK,
    BRIEF_STATUS_QUOTA_ERROR,
    BRIEF_STATUS_SCHEMA_INVALID,
    BRIEF_STATUS_TIMEOUT,
    BriefCallOutcome,
    call_deepseek_brief,
)
from personal_alpha_terminal.ai_advisory.renderer import (
    BRIEF_TITLE,
    render_brief_compact,
    render_brief_full,
    render_brief_header,
)
from personal_alpha_terminal.ai_advisory.schemas import (
    PRODUCTION_INFLUENCE,
    PROMPT_VERSION,
    QUARANTINE_STATUS,
    SCHEMA_VERSION,
    validate_brief,
)
from personal_alpha_terminal.ai_advisory.service import AiBriefResult, AiBriefService

__all__ = [
    "AiBriefResult",
    "AiBriefService",
    "BRIEF_STATUS_API_ERROR",
    "BRIEF_STATUS_EMPTY",
    "BRIEF_STATUS_OK",
    "BRIEF_STATUS_QUOTA_ERROR",
    "BRIEF_STATUS_SCHEMA_INVALID",
    "BRIEF_STATUS_TIMEOUT",
    "BRIEF_TITLE",
    "BriefCache",
    "BriefCacheKey",
    "BriefCallOutcome",
    "DEFAULT_CACHE_ROOT",
    "PRODUCTION_INFLUENCE",
    "PROMPT_VERSION",
    "QUARANTINE_STATUS",
    "SCHEMA_VERSION",
    "build_deterministic_brief",
    "build_quant_facts",
    "call_deepseek_brief",
    "render_brief_compact",
    "render_brief_full",
    "render_brief_header",
    "validate_brief",
]
