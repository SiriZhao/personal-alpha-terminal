"""SQLAlchemy domain models and shared metadata."""

from personal_alpha_terminal.models.alpha_discovery import (
    AlphaCombinationResult,
    AlphaDiscoveryRun,
    AlphaFactorEvaluation,
)
from personal_alpha_terminal.models.backtest import (
    BacktestDailyResult,
    BacktestRebalance,
    BacktestRun,
    BacktestSummaryMetric,
)
from personal_alpha_terminal.models.base import Base
from personal_alpha_terminal.models.conditional_probability import (
    ConditionalProbabilityResult,
    ConditionalProbabilityRun,
)
from personal_alpha_terminal.models.console import DataSnapshotManifest
from personal_alpha_terminal.models.decision import (
    DecisionHistory,
    QuantDecisionRecommendation,
    QuantDecisionRun,
)
from personal_alpha_terminal.models.event_study import (
    EventDefinition,
    EventOccurrence,
    EventStudyObservation,
    EventStudyRun,
    EventStudyStatistic,
)
from personal_alpha_terminal.models.factor import (
    FactorBacktestPeriod,
    FactorBacktestSummary,
    FactorResearchRun,
    FactorScore,
    FinancialPerShareMetric,
)
from personal_alpha_terminal.models.governance import (
    ExperimentRecord,
    ExperimentResultRecord,
    PortfolioReconciliationRecord,
)
from personal_alpha_terminal.models.intelligence import (
    IntelligenceDecisionLineage,
    IntelligenceEvent,
    IntelligenceEventEvidence,
    IntelligenceExtractionCache,
    IntelligenceFeature,
    IntelligenceHypothesis,
    IntelligenceNarrative,
    IntelligenceNarrativeExposure,
    IntelligenceRawInformation,
    IntelligenceRelationship,
    IntelligenceResearchResult,
)
from personal_alpha_terminal.models.lead_lag import (
    LeadLagAnalysisRun,
    LeadLagMetric,
    LeadLagPairResult,
)
from personal_alpha_terminal.models.market import (
    Financial,
    Industry,
    Price,
    ProviderCapabilityRecord,
    SecurityMaster,
    Stock,
)
from personal_alpha_terminal.models.market_data_quality import (
    CorporateAction,
    ExchangeSession,
    MarketDataQualityResult,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
)
from personal_alpha_terminal.models.market_graph import (
    MarketGraphEdge,
    MarketGraphNode,
    MarketGraphPath,
    MarketGraphRun,
)
from personal_alpha_terminal.models.market_regime import (
    MarketRegimeObservation,
    MarketRegimeRun,
)
from personal_alpha_terminal.models.pipeline import DailyPipelineRun, DailyTaskRun
from personal_alpha_terminal.models.portfolio import (
    Portfolio,
    PortfolioAllocationTarget,
    PortfolioPosition,
    PortfolioTransaction,
)
from personal_alpha_terminal.models.portfolio_risk import (
    FxRate,
    PortfolioRiskMetric,
    PortfolioRiskRun,
    PortfolioStressResult,
)
from personal_alpha_terminal.models.quant_core_closure import (
    DelistingHistory,
    ListingHistory,
    ModelApprovalRecord,
    PITTotalReturnPointRecord,
    SymbolAlias,
    TradingStatus,
    UniverseDefinition,
    UniverseMembership,
)
from personal_alpha_terminal.models.relationship import (
    RelationshipAnalysisRun,
    RelationshipAnomaly,
    RelationshipCorrelation,
)
from personal_alpha_terminal.models.report import ResearchReport
from personal_alpha_terminal.models.research import Event, Signal
from personal_alpha_terminal.models.scenario import (
    AssetRiskFactorExposure,
    ScenarioAssetImpact,
    ScenarioDefinitionModel,
    ScenarioRiskFactor,
    ScenarioSimulationRun,
)
from personal_alpha_terminal.models.us_quant import (
    BacktestManifestRecord,
    FundamentalVintage,
    ManualRebalanceFillRecord,
    ManualRebalanceTicketRecord,
    ModelRegistryRecord,
    PITTotalReturnVersion,
    ResearchDataCertification,
    SecurityIdentifierHistory,
)

__all__ = [
    "AlphaCombinationResult",
    "AlphaDiscoveryRun",
    "AlphaFactorEvaluation",
    "AssetRiskFactorExposure",
    "Base",
    "BacktestDailyResult",
    "BacktestRebalance",
    "BacktestRun",
    "BacktestSummaryMetric",
    "BacktestManifestRecord",
    "ConditionalProbabilityResult",
    "ConditionalProbabilityRun",
    "DecisionHistory",
    "DelistingHistory",
    "CorporateAction",
    "DailyPipelineRun",
    "DailyTaskRun",
    "Event",
    "EventDefinition",
    "EventOccurrence",
    "EventStudyObservation",
    "EventStudyRun",
    "EventStudyStatistic",
    "ExperimentRecord",
    "ExperimentResultRecord",
    "ExchangeSession",
    "Financial",
    "FundamentalVintage",
    "FinancialPerShareMetric",
    "FxRate",
    "FactorBacktestPeriod",
    "FactorBacktestSummary",
    "FactorResearchRun",
    "FactorScore",
    "Industry",
    "IntelligenceEvent",
    "IntelligenceEventEvidence",
    "IntelligenceExtractionCache",
    "IntelligenceFeature",
    "IntelligenceDecisionLineage",
    "IntelligenceHypothesis",
    "IntelligenceNarrative",
    "IntelligenceNarrativeExposure",
    "IntelligenceRawInformation",
    "IntelligenceRelationship",
    "IntelligenceResearchResult",
    "LeadLagAnalysisRun",
    "LeadLagMetric",
    "LeadLagPairResult",
    "ListingHistory",
    "MarketGraphEdge",
    "MarketGraphNode",
    "MarketGraphPath",
    "MarketGraphRun",
    "MarketDataQualityResult",
    "MarketDataQualityRun",
    "MarketRegimeObservation",
    "MarketRegimeRun",
    "MarketUniverseMember",
    "MarketUniverseSnapshot",
    "ManualRebalanceFillRecord",
    "ManualRebalanceTicketRecord",
    "ModelRegistryRecord",
    "ModelApprovalRecord",
    "PITTotalReturnVersion",
    "PITTotalReturnPointRecord",
    "DataSnapshotManifest",
    "Portfolio",
    "PortfolioAllocationTarget",
    "PortfolioPosition",
    "PortfolioTransaction",
    "PortfolioRiskMetric",
    "PortfolioRiskRun",
    "PortfolioReconciliationRecord",
    "PortfolioStressResult",
    "Price",
    "ProviderCapabilityRecord",
    "QuantDecisionRecommendation",
    "QuantDecisionRun",
    "RelationshipAnalysisRun",
    "RelationshipAnomaly",
    "RelationshipCorrelation",
    "ResearchReport",
    "ResearchDataCertification",
    "Signal",
    "ScenarioAssetImpact",
    "ScenarioDefinitionModel",
    "ScenarioRiskFactor",
    "ScenarioSimulationRun",
    "SecurityMaster",
    "SecurityIdentifierHistory",
    "Stock",
    "SymbolAlias",
    "TradingStatus",
    "UniverseDefinition",
    "UniverseMembership",
]
