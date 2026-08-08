# 终端数据质量说明

每次同步生成不可变 JSON manifest，记录 Provider、adapter、请求时间、市场、资产类型、代码、日期范围、时区、币种、复权/公司行动策略、原始/接收/拒绝/重复行数、失败与过期资产、schema/app 版本和 SHA256。

`CERTIFIED` 在 Console Preview 中仅表示 required 资产通过本地 OHLCV 合同，并可用于研究和模拟估值。它不表示历史成分股、退市证券、公司行动或 point-in-time total-return 已达到生产投资决策标准。严格 ResearchDataGate 仍可保持 `BLOCKED`。

Optional 资产失败会产生 `PARTIAL`；required 资产失败或缓存过期会产生 `BLOCKED/PROVIDER_ERROR`。
