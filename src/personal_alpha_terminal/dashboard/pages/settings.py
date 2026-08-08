from __future__ import annotations

import os
from dataclasses import replace
from typing import cast

import streamlit as st

from personal_alpha_terminal.agents.llm import LLMProviderError, LLMRequest, build_llm_provider
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.credentials import (
    CredentialStoreError,
    delete_api_key,
    read_api_key,
    write_api_key,
)
from personal_alpha_terminal.core.product import (
    FIRST_RUN_NOTICE,
    MarketColorConvention,
    RunMode,
    ThemeMode,
    default_application_data_dir,
    load_preferences,
    save_preferences,
)
from personal_alpha_terminal.dashboard.components import page_header

PROVIDER_LABELS = {
    "disabled": "禁用 AI",
    "mock": "Mock（明确测试标识）",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "anthropic": "Anthropic",
    "custom": "Custom OpenAI-compatible API",
}
EXTERNAL_PROVIDERS = {"openai", "deepseek", "anthropic", "custom"}
MODE_LABELS = {
    RunMode.RESEARCH_PREVIEW: "Research Preview",
    RunMode.MOCK_DEMO: "Mock Demo",
    RunMode.OFFLINE: "Offline",
    RunMode.DATA_VALIDATION: "Data Validation",
}


def _provider_defaults(provider: str) -> tuple[str, str]:
    settings = get_settings()
    return {
        "openai": (settings.openai_model, "https://api.openai.com/v1"),
        "deepseek": (settings.deepseek_model, settings.deepseek_base_url),
        "anthropic": (settings.anthropic_model, settings.anthropic_base_url),
        "custom": (settings.custom_model, settings.custom_base_url),
    }.get(provider, ("", ""))


def _write_ai_config(
    *,
    provider: str,
    model: str,
    base_url: str,
    temperature: float,
    timeout: int,
    retries: int,
) -> None:
    root = default_application_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "config.env"
    updates = {
        "PAT_LLM_PROVIDER": provider,
        "PAT_LLM_TEMPERATURE": str(temperature),
        "PAT_LLM_TIMEOUT_SECONDS": str(timeout),
        "PAT_LLM_MAX_RETRIES": str(retries),
    }
    if provider in EXTERNAL_PROVIDERS:
        updates[f"PAT_{provider.upper()}_MODEL"] = model.strip()
        if provider != "openai":
            updates[f"PAT_{provider.upper()}_BASE_URL"] = base_url.strip().rstrip("/")
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    output: list[str] = []
    remaining = dict(updates)
    for line in lines:
        key = line.partition("=")[0].strip().upper()
        output.append(f"{key}={remaining.pop(key)}" if key in remaining else line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(path)
    for key, value in updates.items():
        os.environ[key] = value


page_header("系统设置 Settings", "运行模式、市场、外观、AI Provider 与本地隐私控制。")
preferences = load_preferences()
settings = get_settings()

st.info(FIRST_RUN_NOTICE)
links = st.columns(3)
if links[0].button("数据源与数据合同", icon=":material/database:", width="stretch"):
    st.switch_page("pages/data_sources.py")
if links[1].button("数据库与环境检测", icon=":material/monitor_heart:", width="stretch"):
    st.switch_page("pages/diagnostics.py")
if links[2].button("研究说明", icon=":material/info:", width="stretch"):
    st.switch_page("pages/about.py")

with st.form("product-settings"):
    left, right = st.columns(2)
    with left:
        run_mode = st.selectbox(
            "运行模式",
            options=tuple(RunMode),
            index=tuple(RunMode).index(preferences.run_mode),
            format_func=lambda value: MODE_LABELS[RunMode(str(value))],
        )
        theme = st.selectbox(
            "界面主题",
            options=tuple(ThemeMode),
            index=tuple(ThemeMode).index(preferences.theme),
            format_func=lambda value: {
                ThemeMode.SYSTEM: "跟随系统",
                ThemeMode.DARK: "深色",
                ThemeMode.LIGHT: "浅色",
            }[ThemeMode(str(value))],
        )
        color_convention = st.selectbox(
            "涨跌颜色",
            options=tuple(MarketColorConvention),
            index=tuple(MarketColorConvention).index(preferences.market_color_convention),
            format_func=lambda value: {
                MarketColorConvention.CHINA: "中国市场：红涨绿跌",
                MarketColorConvention.INTERNATIONAL: "国际市场：绿涨红跌",
            }[MarketColorConvention(str(value))],
        )
        markets = cast(
            list[str],
            st.multiselect(
                "研究市场",
                options=("A", "HK", "US"),
                default=list(preferences.selected_markets),
                format_func=lambda value: {"A": "A股", "HK": "港股", "US": "美股"}[str(value)],
            ),
        )
        exclude_positions = st.checkbox(
            "诊断包排除精确持仓金额",
            value=preferences.exclude_position_amounts_from_diagnostics,
        )
        allow_portfolio_ai = st.checkbox(
            "允许将组合证据发送给已配置的外部 AI",
            value=preferences.allow_portfolio_evidence_to_ai,
            help="默认关闭。AI 只能解释已存在证据，不能改变量化决策。",
        )
    with right:
        provider = st.selectbox(
            "AI Provider",
            options=tuple(PROVIDER_LABELS),
            index=tuple(PROVIDER_LABELS).index(preferences.ai_provider)
            if preferences.ai_provider in PROVIDER_LABELS
            else 0,
            format_func=lambda value: PROVIDER_LABELS[str(value)],
        )
        default_model, default_base_url = _provider_defaults(provider)
        model = st.text_input(
            "Model Name",
            value=default_model,
            disabled=provider not in EXTERNAL_PROVIDERS,
        )
        base_url = st.text_input(
            "Base URL",
            value=default_base_url,
            disabled=provider not in {"deepseek", "anthropic", "custom"},
        )
        temperature = st.slider(
            "Temperature",
            min_value=0.0,
            max_value=1.0,
            value=min(settings.llm_temperature, 1.0),
            step=0.05,
            disabled=provider not in EXTERNAL_PROVIDERS,
        )
        timeout = st.number_input(
            "请求超时（秒）",
            min_value=5,
            max_value=600,
            value=int(settings.llm_timeout_seconds),
            disabled=provider not in EXTERNAL_PROVIDERS,
        )
        retries = st.number_input(
            "最大重试次数",
            min_value=0,
            max_value=10,
            value=settings.llm_max_retries,
            disabled=provider not in EXTERNAL_PROVIDERS,
        )
        api_key = st.text_input(
            "新 API Key（留空表示不修改）",
            type="password",
            autocomplete="off",
            disabled=provider not in EXTERNAL_PROVIDERS,
        )
    submit_columns = st.columns(2)
    save_clicked = submit_columns[0].form_submit_button("保存设置", type="primary", width="stretch")
    test_clicked = submit_columns[1].form_submit_button(
        "测试 AI 连接",
        disabled=provider not in EXTERNAL_PROVIDERS,
        width="stretch",
    )

if save_clicked or test_clicked:
    if not markets:
        st.error("至少选择一个研究市场。")
    else:
        try:
            if api_key and provider in EXTERNAL_PROVIDERS:
                write_api_key(provider, api_key)
                os.environ[f"{provider.upper()}_API_KEY"] = api_key
            elif provider in EXTERNAL_PROVIDERS:
                stored = read_api_key(provider)
                if stored:
                    os.environ[f"{provider.upper()}_API_KEY"] = stored
            _write_ai_config(
                provider=provider,
                model=model,
                base_url=base_url,
                temperature=temperature,
                timeout=int(timeout),
                retries=int(retries),
            )
            save_preferences(
                replace(
                    preferences,
                    run_mode=run_mode,
                    theme=theme,
                    market_color_convention=color_convention,
                    selected_markets=tuple(markets),
                    ai_provider=provider,
                    exclude_position_amounts_from_diagnostics=exclude_positions,
                    allow_portfolio_evidence_to_ai=allow_portfolio_ai,
                )
            )
            get_settings.cache_clear()
            if save_clicked:
                st.success("设置已保存；API Key 仅保存在 Windows Credential Manager。")
            if test_clicked:
                response = build_llm_provider(get_settings()).generate(
                    LLMRequest(
                        system_prompt="Return a short JSON object confirming API connectivity.",
                        user_prompt='{"task":"connectivity_test","no_investment_analysis":true}',
                        temperature=0.0,
                    )
                )
                if response.is_mock:
                    st.error("Connection Failed：外部 Provider 未调用，当前返回 Mock。")
                else:
                    st.success(f"Connection Successful · {response.provider} · {response.model}")
        except (CredentialStoreError, LLMProviderError, ValueError) as error:
            st.error(f"Connection Failed：{error}")

st.divider()
with st.expander("AI 请求内容与权限"):
    st.write(
        "AI 仅接收用户明确允许的、已脱敏的量化证据，用于解释和报告。"
        "API Key、完整数据库、日志和投资日志不会作为提示词发送。"
    )
    st.warning("AI 不参与股票排名、目标权重、Action 或风险门禁计算。")

st.subheader("本地凭据状态")
for provider_name in ("openai", "deepseek", "anthropic", "custom"):
    configured = bool(read_api_key(provider_name))
    columns = st.columns((3, 1))
    columns[0].write(
        f"{PROVIDER_LABELS[provider_name]}："
        + ("已保存在 Windows Credential Manager" if configured else "未配置")
    )
    if columns[1].button(
        "删除密钥",
        key=f"delete-{provider_name}",
        disabled=not configured,
        width="stretch",
    ):
        delete_api_key(provider_name)
        st.success("密钥已删除。")
        st.rerun()

st.caption(f"配置目录：{default_application_data_dir()} · API Key 不写入 config.env。")
