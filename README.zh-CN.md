# Personal Alpha Terminal

个人使用、美股、long-only、中低频、每日运行一次的量化决策终端。

这是一个 **manual-decision quantitative terminal**，不是自动交易机器人。系统只生成可审计的人工执行建议；你本人到 Charles Schwab 手动下单，并把真实成交同步回系统。

## 核心原则

- 数据正确性优先。
- 禁止未来函数和数据泄漏。
- PIT、风险、成本、统计门禁 fail-closed。
- LLM 只做 SHADOW 情报，不选股、不设定概率、不控制组合。
- 不自动下单，不连接 Broker API。

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ai]"
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py daily
```

## 常用命令

```powershell
python main.py doctor
python main.py daily
python main.py refresh
python main.py portfolio-list
python main.py portfolio-show
python main.py intelligence status
python main.py intelligence audit
python main.py operational-policy status
```

## 文档

- 中文完整教程：[docs/USER_GUIDE_zh-CN.md](docs/USER_GUIDE_zh-CN.md)
- 架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 仓库指南：[docs/REPOSITORY_GUIDE.md](docs/REPOSITORY_GUIDE.md)
- 技术债：[docs/TECH_DEBT.md](docs/TECH_DEBT.md)

## 安全

- API Key 只放在用户环境变量中。
- 仓库不保存真实密钥。
- 当前 LLM production influence 为 NONE。
- Probability fallback 为 CLASSICAL，生产权重为 0。
- 自动执行保持 DISABLED。
