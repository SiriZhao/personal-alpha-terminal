from decimal import Decimal
from html import escape

import streamlit as st

from personal_alpha_terminal.core.product import (
    MarketColorConvention,
    ThemeMode,
)
from personal_alpha_terminal.dashboard.runtime import database_ready


def apply_product_theme(
    theme: ThemeMode = ThemeMode.SYSTEM,
    color_convention: MarketColorConvention = MarketColorConvention.INTERNATIONAL,
) -> None:
    up_color = "#FF6B7D" if color_convention is MarketColorConvention.CHINA else "#3CCF91"
    down_color = "#3CCF91" if color_convention is MarketColorConvention.CHINA else "#FF6B7D"
    light_override = """
        .stApp { background: linear-gradient(180deg, #F7F9FC 0%, #EEF2F8 100%); color:#172033; }
        [data-testid="stSidebar"] { background: rgba(250,252,255,.97); }
        [data-testid="stMetric"], [data-testid="stVerticalBlockBorderWrapper"], .pat-kpi {
            background: rgba(255,255,255,.92); border-color: rgba(48,63,92,.13);
            box-shadow: 0 12px 28px rgba(33,48,78,.07);
        }
        .pat-hero { background: linear-gradient(120deg,#FFFFFF,#EEF3FF); }
        .pat-hero h1, .pat-kpi-value, .pat-signal-title { color:#172033; }
        .pat-hero p, .pat-kpi-detail, .pat-signal-meta { color:#5D6A80; }
    """
    if theme is ThemeMode.LIGHT:
        theme_css = light_override
    elif theme is ThemeMode.SYSTEM:
        theme_css = f"@media (prefers-color-scheme: light) {{{light_override}}}"
    else:
        theme_css = ""
    stylesheet = """
        <style>
        :root { color-scheme: light dark; --pat-up:__UP_COLOR__; --pat-down:__DOWN_COLOR__; }
        html { scroll-behavior: smooth; }
        .stApp {
            background:
                radial-gradient(circle at 10% -5%, rgba(83,112,255,.15), transparent 31rem),
                radial-gradient(circle at 92% 2%, rgba(157,104,255,.10), transparent 28rem),
                linear-gradient(180deg, #080D18 0%, #0A101C 48%, #080D18 100%);
            color: #E9EEF8;
        }
        .stMainBlockContainer {
            max-width: 1480px;
            padding-top: 2rem;
            padding-bottom: 5rem;
        }
        [data-testid="stSidebar"] {
            border-right: 1px solid rgba(148,163,184,.14);
            background: rgba(10,15,27,.94);
            backdrop-filter: blur(18px);
        }
        [data-testid="stSidebar"] [data-testid="stPageLink"] {
            border-radius: 10px;
            transition: background .16s ease, color .16s ease, transform .16s ease;
        }
        [data-testid="stSidebar"] [data-testid="stPageLink"]:hover {
            background: rgba(108,140,255,.10);
            transform: translateX(2px);
        }
        [data-testid="stMetric"] {
            background: linear-gradient(145deg, rgba(20,29,48,.92), rgba(13,20,35,.94));
            border: 1px solid rgba(135,154,190,.14);
            border-radius: 14px;
            padding: 1rem 1.1rem;
            box-shadow: 0 14px 34px rgba(0,0,0,.13);
            transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease;
        }
        [data-testid="stMetric"]:hover {
            border-color: rgba(108,140,255,.38);
            transform: translateY(-2px);
            box-shadow: 0 18px 44px rgba(0,0,0,.20);
        }
        [data-testid="stMetricValue"] {
            font-variant-numeric: tabular-nums;
            letter-spacing: -.035em;
            font-weight: 650;
        }
        [data-testid="stMetricDelta"] svg { display: none; }
        [data-testid="stMetricLabel"] { color: #98A5BA; }
        [data-testid="stPlotlyChart"] {
            border: 1px solid rgba(135,154,190,.12);
            border-radius: 16px;
            background: rgba(13,20,35,.58);
            overflow: hidden;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(135,154,190,.13);
            border-radius: 16px;
            background: linear-gradient(145deg, rgba(18,27,45,.80), rgba(12,18,32,.84));
            box-shadow: 0 12px 30px rgba(0,0,0,.10);
        }
        h1, h2, h3 { letter-spacing: -.035em; }
        h1 { font-size: clamp(1.9rem, 3vw, 2.7rem) !important; font-weight: 720 !important; }
        h2 { font-size: 1.35rem !important; }
        h3 { font-size: 1.05rem !important; }
        hr { border-color: rgba(148,163,184,.10) !important; }
        .stButton > button, .stDownloadButton > button {
            border-radius: 10px;
            border: 1px solid rgba(108,140,255,.28);
            transition: transform .16s ease, border-color .16s ease, background .16s ease;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            transform: translateY(-1px);
            border-color: #6C8CFF;
            background: rgba(108,140,255,.12);
        }
        [data-baseweb="tab-list"] { gap: .35rem; }
        [data-baseweb="tab"] {
            border-radius: 9px;
            padding-left: .8rem;
            padding-right: .8rem;
        }
        .pat-eyebrow {
            color: #88A2FF;
            font-size: .74rem;
            font-weight: 700;
            letter-spacing: .14em;
            text-transform: uppercase;
            margin-bottom: .45rem;
        }
        .pat-hero {
            position: relative;
            overflow: hidden;
            padding: clamp(1.25rem, 3vw, 2rem);
            border: 1px solid rgba(128,149,190,.17);
            border-radius: 22px;
            background:
                linear-gradient(120deg, rgba(27,40,68,.96), rgba(15,23,40,.91)),
                #10182A;
            box-shadow: 0 24px 64px rgba(0,0,0,.20);
            margin-bottom: 1.25rem;
        }
        .pat-hero::after {
            content: "";
            position: absolute;
            inset: -70% -10% auto 55%;
            height: 22rem;
            border-radius: 999px;
            background: radial-gradient(circle, rgba(108,140,255,.22), transparent 64%);
            pointer-events: none;
        }
        .pat-hero h1 { margin: 0 0 .45rem 0; position: relative; z-index: 1; }
        .pat-hero p { color: #AAB5C9; margin: 0; max-width: 52rem; position: relative; z-index: 1; }
        .pat-hero-meta { margin-top: .9rem; position: relative; z-index: 1; }
        .pat-chip {
            display: inline-block;
            border-radius: 999px;
            padding: .28rem .58rem;
            margin-right: .35rem;
            font-size: .72rem;
            background: rgba(108,140,255,.12);
            color: #B7C5FF;
            border: 1px solid rgba(108,140,255,.22);
        }
        .pat-warning {
            border-left: 3px solid #F2C85B;
            padding: .55rem .75rem;
            color: #D5DDEA;
            background: rgba(246,200,95,.08);
            border-radius: 4px 10px 10px 4px;
            margin-bottom: .55rem;
        }
        .pat-section-head {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.8rem 0 .8rem;
        }
        .pat-section-head h2 { margin: 0; }
        .pat-section-head p { margin: .25rem 0 0; color: #8390A6; font-size: .84rem; }
        .pat-section-index {
            color: #52617B;
            font-variant-numeric: tabular-nums;
            font-size: .78rem;
            letter-spacing: .08em;
        }
        .pat-kpi {
            min-height: 118px;
            padding: 1rem 1.05rem;
            border: 1px solid rgba(135,154,190,.13);
            border-radius: 15px;
            background: linear-gradient(145deg, rgba(19,28,47,.88), rgba(12,19,33,.90));
            transition: transform .18s ease, border-color .18s ease, background .18s ease;
        }
        .pat-kpi:hover {
            transform: translateY(-2px);
            border-color: rgba(108,140,255,.36);
            background: linear-gradient(145deg, rgba(24,35,58,.94), rgba(13,20,35,.96));
        }
        .pat-kpi-label { color: #8F9DB3; font-size: .76rem; letter-spacing: .04em; }
        .pat-kpi-value {
            color: #F5F7FC;
            font-size: clamp(1.25rem, 2.2vw, 1.75rem);
            font-weight: 680;
            letter-spacing: -.035em;
            margin-top: .42rem;
            font-variant-numeric: tabular-nums;
        }
        .pat-kpi-detail { color: #7F8CA2; font-size: .74rem; margin-top: .35rem; }
        .pat-kpi[data-tone="positive"] .pat-kpi-value { color: var(--pat-up); }
        .pat-kpi[data-tone="negative"] .pat-kpi-value { color: var(--pat-down); }
        .pat-kpi[data-tone="accent"] .pat-kpi-value { color: #9EB1FF; }
        .pat-signal {
            padding: .82rem .9rem;
            border-bottom: 1px solid rgba(135,154,190,.10);
            transition: background .16s ease;
        }
        .pat-signal:last-child { border-bottom: 0; }
        .pat-signal:hover { background: rgba(108,140,255,.055); }
        .pat-signal-top { display: flex; justify-content: space-between; gap: .7rem; }
        .pat-signal-title { color: #E7ECF6; font-weight: 600; font-size: .87rem; }
        .pat-signal-value { color: #AFC0FF; font-weight: 680; font-variant-numeric: tabular-nums; }
        .pat-signal-meta { color: #7E8BA1; font-size: .73rem; margin-top: .28rem; }
        .pat-pill {
            display: inline-flex;
            align-items: center;
            gap: .38rem;
            padding: .28rem .58rem;
            border-radius: 999px;
            color: #B9C4D7;
            background: rgba(148,163,184,.10);
            border: 1px solid rgba(148,163,184,.14);
            font-size: .72rem;
            font-weight: 650;
        }
        .pat-pill::before {
            content: "";
            width: .42rem;
            height: .42rem;
            border-radius: 50%;
            background: #8290A8;
        }
        .pat-pill[data-tone="positive"] {
            color: var(--pat-up);
            background: rgba(48,214,163,.09);
            border-color: rgba(48,214,163,.20);
        }
        .pat-pill[data-tone="positive"]::before {
            background: var(--pat-up);
            box-shadow: 0 0 12px rgba(48,214,163,.7);
        }
        .pat-pill[data-tone="negative"] {
            color: var(--pat-down);
            background: rgba(255,97,125,.09);
            border-color: rgba(255,97,125,.20);
        }
        .pat-pill[data-tone="negative"]::before {
            background: var(--pat-down);
            box-shadow: 0 0 12px rgba(255,97,125,.65);
        }
        .pat-pill[data-tone="accent"] {
            color: #ADBDFF;
            background: rgba(108,140,255,.10);
            border-color: rgba(108,140,255,.22);
        }
        .pat-pill[data-tone="accent"]::before {
            background: #6C8CFF;
            box-shadow: 0 0 12px rgba(108,140,255,.65);
        }
        .pat-allocation-row { margin-bottom: .75rem; }
        .pat-allocation-label {
            display: flex;
            justify-content: space-between;
            color: #AAB5C7;
            font-size: .76rem;
            margin-bottom: .28rem;
        }
        .pat-allocation-track {
            height: .38rem;
            border-radius: 999px;
            background: rgba(148,163,184,.10);
            overflow: hidden;
        }
        .pat-allocation-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #6C8CFF, #A78BFA);
        }
        @media (max-width: 760px) {
            .stMainBlockContainer { padding-left: 1rem; padding-right: 1rem; }
            .pat-section-head { align-items: flex-start; flex-direction: column; gap: .35rem; }
            .pat-kpi { min-height: 102px; }
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                transition: none !important;
                animation: none !important;
            }
        }
        __THEME_CSS__
        </style>
        """
    st.markdown(
        stylesheet.replace("__UP_COLOR__", up_color)
        .replace("__DOWN_COLOR__", down_color)
        .replace("__THEME_CSS__", theme_css),
        unsafe_allow_html=True,
    )


def require_database() -> None:
    if database_ready():
        return
    st.error("研究数据库尚未初始化。请先运行 `python -m personal_alpha_terminal init-db`。")
    st.stop()


def page_header(title: str, description: str) -> None:
    st.title(title)
    st.caption(description)


def section_header(index: str, title: str, description: str) -> None:
    st.markdown(
        (
            '<div class="pat-section-head">'
            f'<div><div class="pat-eyebrow">{escape(index)}</div>'
            f'<h2>{escape(title)}</h2><p>{escape(description)}</p></div>'
            f'<div class="pat-section-index">{escape(index)}</div></div>'
        ),
        unsafe_allow_html=True,
    )


def kpi_card(
    label: str,
    value: str,
    detail: str,
    *,
    tone: str = "neutral",
) -> None:
    st.markdown(
        (
            f'<div class="pat-kpi" data-tone="{escape(tone)}">'
            f'<div class="pat-kpi-label">{escape(label)}</div>'
            f'<div class="pat-kpi-value">{escape(value)}</div>'
            f'<div class="pat-kpi-detail">{escape(detail)}</div></div>'
        ),
        unsafe_allow_html=True,
    )


def status_pill(label: str, *, tone: str = "neutral") -> str:
    return (
        f'<span class="pat-pill" data-tone="{escape(tone)}">{escape(label)}</span>'
    )


def signal_row(title: str, value: str, meta: str) -> None:
    st.markdown(
        (
            '<div class="pat-signal"><div class="pat-signal-top">'
            f'<span class="pat-signal-title">{escape(title)}</span>'
            f'<span class="pat-signal-value">{escape(value)}</span></div>'
            f'<div class="pat-signal-meta">{escape(meta)}</div></div>'
        ),
        unsafe_allow_html=True,
    )


def allocation_bar(label: str, weight: float) -> None:
    bounded = max(0.0, min(1.0, weight))
    st.markdown(
        (
            '<div class="pat-allocation-row">'
            f'<div class="pat-allocation-label"><span>{escape(label)}</span>'
            f'<span>{bounded:.1%}</span></div>'
            '<div class="pat-allocation-track">'
            f'<div class="pat-allocation-fill" style="width:{bounded:.2%}"></div>'
            "</div></div>"
        ),
        unsafe_allow_html=True,
    )


def empty_state(message: str, *, hint: str | None = None) -> None:
    st.info(message, icon=":material/info:")
    if hint:
        st.caption(hint)


def format_price(value: Decimal | float | None, currency: str = "") -> str:
    if value is None:
        return "—"
    numeric = float(value)
    prefix = f"{currency} " if currency else ""
    return f"{prefix}{numeric:,.2f}"


def format_percent(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2%}"


def format_volume(value: int | None) -> str:
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.2f}K"
    return f"{value:,}"
