# Current Quant Architecture

`RuntimeContext -> Layered Gates -> USPointInTimeRepository -> ProductionDailyQuantInputAssembler
-> USAdaptiveAlphaCoreV1 -> UnifiedAlphaEngine -> RiskModel -> DynamicRiskBudget ->
PortfolioConstruction -> TradeGenerator -> ActionGate -> immutable TodayResult`

Conditional probability and event studies are supporting evidence only unless separately locked
and approved. Graph/lead-lag stays research/watchlist. AI reads deterministic evidence after the
quant run; it cannot calculate factors, rank assets, set weights, veto risk, or create actions.
