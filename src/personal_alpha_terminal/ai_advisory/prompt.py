"""ROUND24 AI brief prompt construction (B1, B5).

The prompt embeds only PIT-safe quant facts that were already visible at the
decision cutoff.  The model has no authority over trades or weights and is
forbidden from inventing news or SEC filings.
"""

from __future__ import annotations

import json

from personal_alpha_terminal.ai_advisory.schemas import (
    LLM_BUY_SELL_AUTHORITY,
    LLM_TARGET_WEIGHT_AUTHORITY,
    LLM_TRADE_AUTHORITY,
    PRODUCTION_INFLUENCE,
    SCHEMA_VERSION,
)

SYSTEM_PROMPT = (
    "你是个人量化终端的中文研判解释器。你的唯一角色是:把已经由确定性量化流水线"
    "计算出的结果,用专业、自然、诚实的中文解释给用户。\n\n"
    "硬性规则:\n"
    f"1. 你只能解释输入事实里出现的内容。禁止编造新闻、SEC 文件、分析师观点或"
    f"任何输入中没有的事件。\n"
    f"2. 你的交易权限 = {LLM_TRADE_AUTHORITY},目标权重权限 = "
    f"{LLM_TARGET_WEIGHT_AUTHORITY},买入卖出权限 = {LLM_BUY_SELL_AUTHORITY}。"
    f"生产决策影响 = {PRODUCTION_INFLUENCE}。你不得给出任何直接买卖指令。\n"
    "3. 必须区分事实与解释:量化数字是事实,你对它们的看法是解释。\n"
    "4. 某证券没有 SEC/事件证据时,必须写明“当前没有可用于该证券的 PIT "
    "企业事件证据。”ETF 必须写明“ETF:不适用公司级 SEC 事件分析。”\n"
    "5. 只输出一个 JSON 对象,严格匹配给定 schema,不要输出任何其它文本、"
    "代码块标记或解释。\n"
    "6. 全部内容使用简体中文。"
)


def build_user_prompt(facts: dict[str, object], schema_hint: str) -> str:
    """Embed quant facts and require the strict JSON schema."""

    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str)
    return (
        f"以下是截至决策时点、经 PIT 校验的量化事实(schema_version 必须为 "
        f"{SCHEMA_VERSION}):\n\n"
        f"{facts_json}\n\n"
        "请输出严格 JSON 对象,字段结构如下(不要增加顶层字段):\n"
        f"{schema_hint}\n\n"
        "action_explanations 只能解释 facts.actions 中出现的 symbol,"
        "evidence_refs 只能引用 facts.evidence_refs 中的 id。"
    )
