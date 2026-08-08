# AI Provider 指南

支持：Disabled、Mock、OpenAI、DeepSeek、Anthropic 和自定义 OpenAI-compatible API。AI 只允许总结数据库已有证据，不预测价格，不自动交易，也不参与 Decision Engine 评分。

## 配置原则

- 优先在“设置”中保存密钥到 Windows Credential Manager。
- 不得把密钥写入仓库、`.env`、日志、截图、诊断包或普通备份。
- 无密钥时选择 Disabled；Mock 只用于流程测试并明确标识。
- 外部 AI 默认不能接收持仓证据。启用前先预览请求内容。
- Temperature、超时和重试次数均可配置；研究报告应保持低温度。

## 输出合同

每条结论必须包含数据来源、引用数据、分析依据、风险与限制。输入证据缺失或质量门禁失败时，Provider 层不得生成实盘风格建议。

环境变量兼容入口：`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`ANTHROPIC_API_KEY`、`CUSTOM_API_KEY`。它们仅应存在于当前用户/进程安全环境中，不应落盘到项目文件。

Anthropic 适配器使用 Messages API；自定义 Provider 要求 HTTPS 的 OpenAI-compatible Chat Completions 接口。连接测试只验证配置和 API 可达性，不生成投资结论。
