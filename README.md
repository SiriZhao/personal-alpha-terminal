# Personal Alpha Terminal

Personal Alpha Terminal 是面向个人账户的中低频美股量化研究与人工决策终端。量化代码负责数据检查、模型、组合和风险门禁；AI 仅可解释已生成结果。程序不连接 Charles Schwab 或其他券商，也不会自动下单。

历史结果不保证未来表现，不构成投资建议。缺少可靠数据、PIT 公司行动、生产批准模型或风险结果时，系统会输出 `NO ACTION / BLOCKED`。

## 每日使用

1. 双击发布目录中的 `QuantTerminal.exe`，默认直接进入 Today 驾驶舱。
2. `HEALTHY` 表示该层正常；`DEGRADED` 表示可研究但能力受限；`UNSAFE/BLOCKED` 表示不得生成可执行操作。
3. 组合为空时，使用 `portfolio-init` 创建真实组合账本，再用 `portfolio-import` 导入通用或 Charles Schwab 持仓 CSV。
4. `ACCEPT` 仅把候选记为 `Pending Manual Execution`；`REJECT` 和 `WATCH` 只记录人工决定。
5. 用户在 Charles Schwab 自行成交后，使用 `mark-executed` 录入实际价格、数量和可选费用。项目没有券商 API。
6. 出现 `DATA UNSAFE` 时先运行 `doctor`，检查 Provider、缓存新鲜度、交易日历和数据库；不要依据旧行情操作。
7. AI API 为可选项。没有 API Key 时量化核心照常运行；密钥不得写入仓库或日志。

维护命令可通过发布版 EXE 运行：

```text
QuantTerminal.exe doctor
QuantTerminal.exe portfolio-init --name "My Portfolio" --cash 100000
QuantTerminal.exe portfolio-import positions.csv --portfolio-id 1
QuantTerminal.exe portfolio-list
QuantTerminal.exe accept <recommendation_id>
QuantTerminal.exe reject <recommendation_id>
QuantTerminal.exe watch <recommendation_id>
QuantTerminal.exe mark-executed <recommendation_id> --price 100 --quantity 10 --fees 0
```

## 数据、日志与备份

用户数据与程序目录分离，默认保存在：

```text
%LOCALAPPDATA%\PersonalAlphaTerminal
```

其中 `data/` 包含数据库，`config.yaml` 与 `config.env` 包含本机配置，`cache/` 是行情缓存，`logs/` 保存轮转日志，`backups/` 保存本地备份。备份时应复制 `data/`、配置文件与 `backups/`；不要把 API Key 放入普通共享压缩包。

日志分为 `app.log`、`data.log` 和 `error.log`，每个文件限制 5 MB 并保留 3 个轮转备份。日报保留 180 天，诊断包和更新临时文件保留 30 天。市场快照、组合、数据库和配置不参与自动清理。

## 数据边界

- Yahoo Finance 是免费主行情源；Stooq 是美股股票/ETF 历史价格备用源。免费源不能替代专业 PIT 股票池、公司行动与退市数据。
- 双源不可用、数据过期、异常、未来时间戳、Provider 冲突或公司行动未认证时，门禁会降级或阻止 Action。
- Nasdaq 23H 采用集中 feature flag；Night 默认仅为信息层且执行关闭。历史数据不会套用未来市场结构。
- 只有 `PRODUCTION_APPROVED` Alpha 才可进入 Daily Decision；技术指标、相关性或 AI 说明不能直接生成仓位。

## 源码验证

源码开发要求 Python 3.12–3.14。正式用户无需安装 Python；发布版为 Windows onedir 构建。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[console,market-data,research,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

架构与安全边界见 `docs/architecture/` 和 `docs/user-guide/`。最终产品化结果见 `docs/development/FINAL_PRODUCTIZATION_REPORT.md`。
