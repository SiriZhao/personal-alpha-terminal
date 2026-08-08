from __future__ import annotations

from dataclasses import dataclass

from personal_alpha_terminal.core.config import Settings


@dataclass(frozen=True, slots=True)
class ModuleStatus:
    name: str
    status: str
    reason: str


def module_statuses(settings: Settings, *, database_ready: bool) -> tuple[ModuleStatus, ...]:
    data_status = "数据待配置" if database_ready else "当前不可用"
    gated = "验证中" if database_ready else "已被安全门禁阻止"
    ai_status = (
        "验证中"
        if settings.llm_provider in {"openai", "deepseek", "mock"}
        else "数据待配置"
    )
    return (
        ModuleStatus("市场数据引擎", data_status, "真实数据需配置 Provider 并通过质量门禁"),
        ModuleStatus("数据质量门禁", "可用", "fail-closed，不通过时阻止下游"),
        ModuleStatus("股票与资产主数据", data_status, "支持独立资产端点与单位合同"),
        ModuleStatus("因子研究 / Alpha Discovery", gated, "需要认证 PIT 数据"),
        ModuleStatus("Event Study / Conditional Probability", gated, "需要有效样本与时间一致性"),
        ModuleStatus("Market Graph / Lead-Lag", gated, "统计关系不代表因果"),
        ModuleStatus("Market Regime", gated, "未校准时仅显示市场状态评分"),
        ModuleStatus("Backtest Laboratory", "可用", "输入不满足 PIT/成交门禁时拒绝运行"),
        ModuleStatus("Portfolio / Risk / Scenario", "可用", "仅分析，不执行交易"),
        ModuleStatus("AI Research Agent", ai_status, "未配置密钥时可禁用或使用明确 Mock"),
        ModuleStatus("Investment Journal", "当前不可用", "仓储模型与隐私审计尚未完成"),
        ModuleStatus("Daily Pipeline", "可用", "任务隔离、重试和本地报告"),
        ModuleStatus("SQLite 本地备份", "可用", "API Key 不进入普通备份"),
        ModuleStatus("PostgreSQL 恢复认证", "验证中", "真实损坏恢复演练尚未关闭"),
    )
