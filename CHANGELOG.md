# Changelog

## 1.1.0 — Stable Terminal Baseline (2026-08-09)

### Fixed

- 修复 yfinance 1.5.x 缓存目录 API 兼容，避免只读用户目录导致 Provider 静默失败。
- 修复非交互 DAILY 命令在退出提示处触发 `EOFError`。
- 首次运行统一创建用户本地数据库、配置、缓存、报告和轮转日志目录。
- 修复冻结环境首次迁移缺少 SQLAlchemy `TypeEngine` 导出的问题；历史 Alembic revision 未被改写。

### Hardened

- 默认入口为 Rich 终端日报，不使用 Textual、浏览器或 localhost；Doctor、真实组合和人工成交命令保留。
- Yahoo 主源失败可回退 Stooq；所有可靠来源失败且缓存不安全时 fail closed。
- 公司行动未认证、模型未生产批准或数据质量不足时只输出 `NO ACTION`。
- `ACCEPT` 仅进入人工待执行状态，项目不包含券商下单接口。
- 日志按 5 MB × 3 轮转；日报、诊断和更新临时文件应用有界保留策略。

### Removed

- 删除 Streamlit Dashboard、桌面浏览器启动器、旧 Textual 多页 TUI、前端专用桥接代码和对应测试。
- 删除旧发布脚本、浏览器截图脚本和已被正式终端包替代的发布产物。

### Known limitations

- 免费数据仍不能完成 PIT 公司行动、历史成分股、退市与双源认证，相关生产 Action 门禁保持阻止。
- 独立全新 Windows VM、商业代码签名及真实资金认证不在本地构建证据范围内。

## Unreleased — Terminal data stabilization

### Changed

- 默认产品入口收敛为 terminal-first Daily Mode，不打开浏览器。
- 主数据库行情引擎支持有序 Provider fallback；Yahoo 失败时，美股股票/ETF 可降级到 Stooq。
- Canonical 日线增加 UTC/ET、trade date、session、来源、数据年龄和质量分；缓存回退显式标记。
- Nasdaq 23H 市场结构集中配置；Night 默认只作为信息层，禁止夜盘执行。
- Action review 只接受确定性量化链候选；接受后仍需在 Charles Schwab 人工下单并录入实际成交。

### Removed

- 模拟盘、模拟订单和虚拟资金退出正式运行入口；历史回测与真实组合人工跟踪保留。

### Safety

- 免费源行情即使下载成功，缺少双源核验或 PIT 公司行动认证时仍为 `PARTIAL/RESEARCH_ONLY`。
- 所有可靠来源失败且缓存过期时 fail closed，不生成可执行动作。
- 未获 `PRODUCTION_APPROVED` 的 Alpha 只能产生 `NO ACTION`。

## 1.1.0-console-preview — 2026-08-02

### Added

- Textual/Rich 全屏终端驾驶舱、数据中心、行动中心、模拟盘、回测门禁、诊断和设置页。
- UI 无关的 Application Service，以及独立程序/数据/模型/模拟盘状态机。
- 真实行情同步 manifest、不可变快照路径、来源/单位/时区/质量摘要和 required/optional 资产判定。
- 完整模拟盘账本、T+1 开盘成交、限价检查、佣金、滑点、现金和持仓约束。
- Windows console one-folder 构建、中文空格路径 smoke test、脱敏诊断包和单实例锁。

### Changed

- Streamlit 冻结为开发兼容入口；默认 EXE 不再打开浏览器。
- `application_start` 改为每个进程只记录一次，避免 Streamlit rerun 重复。
- 版本升级为 `1.1.0-console-preview`；仍不标记 Production Approved。

### Safety

- 免费行情认证只代表本地价格合同适合研究/模拟，不能替代 PIT 股票池、公司行动和总回报认证。
- AI 不参与候选、权重、风险或模拟订单参数。
- 不连接券商，不自动交易。

## 1.0.0 Personal Quant Investment OS — 2026-08-01

### Added

- Daily Investment Dashboard：数据门禁、市场状态、组合快照和行动摘要。
- 确定性 Decision Engine：显式拆解因子、市场状态、风险、条件证据和组合目标贡献。
- Action Center：接受、拒绝、观望的不可变决策历史；接受仅创建 Paper Order。
- 本地组合创建、手动持仓快照、通用 CSV 与 Charles Schwab 持仓格式导入。
- OpenAI、DeepSeek、Anthropic 和自定义 OpenAI-compatible Provider 配置。
- 独立的 Quant Research Center、Backtest 入口和 Paper Portfolio 页面。

### Safety

- Data Gate 非 APPROVED、证据过期、小样本、未校准或无锁定样本外验证时，不生成行动建议。
- “证据可信度”是可解释质量评分，不展示为上涨概率。
- AI 不进入股票排名、目标权重、Action 或风险门禁计算。
- 无认证数据时显示 `Data unavailable / Research Only / No Decision Generated`。

### Known limitations

- 真实 A/HK/US 历史数据认证、PIT 公司行动、危机样本验证、PostgreSQL 恢复和独立 Windows VM 认证仍未完成。
- 1.0.0 产品架构版本不等于实盘认证或 Production Approved。

## 0.9.0 Research Preview — 2026-08-01

### Added

- 一次性首次启动向导和 Research Preview / Mock Demo / Offline / Data Validation 模式。
- 深色、浅色、跟随系统主题和中/国际红绿习惯。
- 设置、数据源、系统诊断和关于页面。
- Windows Credential Manager 密钥存储，OpenAI/DeepSeek/Mock/Disabled Provider。
- 每日/手动 SQLite 备份、恢复预览、恢复前快照和失败回滚。
- 脱敏诊断包、最近错误和环境状态。
- `release-preview` 发布树、CycloneDX SBOM、许可证和 SHA256 生成。

### Changed

- 统一产品标识为 `0.9.0 Research Preview`。
- 首页使用“历史证据/研究发现/统计异常”，移除交易式“机会”措辞。
- 未校准 Market Regime 统一称为“市场状态评分”。
- AI 默认禁用；持仓证据默认不发送给外部 LLM。
- 不可用模块显式标为数据待配置、验证中、当前不可用或安全门禁阻止。

### Security

- API Key 不进入日志、诊断包或普通备份。
- 诊断包排除数据库并脱敏精确持仓金额字段。
- 保留数据质量 fail-closed、point-in-time、资产专用端点和单位检查。

### Known limitations

真实数据认证、历史危机验证、PostgreSQL 损坏恢复、独立 Windows VM、商业签名和实盘认证均未完成。

## Unreleased — 2026-08-14

### Added

- ROUND14 PIT feature/outcome-separated dataset and LLM alpha locked-OOS research protocol.
- ROUND15 conditional probability alpha 2.0 research protocol with fallback artifact.
- ROUND16 Chinese terminal overview and complete Chinese user guide.
- ROUND17 repository storage inventory and safe cache/temp cleanup manifest.

### Research status

- ROUND14 verdict: ROUND14_LLM_ALPHA_NOT_PROVED.
- ROUND15 verdict: PROBABILITY_FALLBACK_CLASSICAL.
- LLM production influence remains NONE.
- Probability production weight remains 0.
