# Console architecture

```text
Textual TUI / maintenance CLI / legacy Streamlit
                    ↓
             ApplicationService
        ┌───────────┼────────────┐
 DataService  DecisionService  PaperTradingService
        ↓            ↓              ↓
 provider → normalize → validate → SQLAlchemy transaction
        ↓
 immutable snapshot manifest + independent strict ResearchDataGate
```

TUI 不读取 SQL、不依赖 `streamlit.session_state`。所有写操作由应用服务控制事务。数据价格合同与严格投资决策门禁分层：前者可允许研究/模拟，后者要求 PIT 股票池、公司行动和总回报认证。

每日流程复用现有 durable task runner 和进程锁。失败任务隔离记录，候选生成仍由严格门禁控制。
