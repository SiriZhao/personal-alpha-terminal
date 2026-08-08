from datetime import date
from pathlib import Path

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import PortfolioTransaction, ResearchReport
from personal_alpha_terminal.portfolio.management_engine import (
    SUPPORTED_TRANSACTION_TYPES,
    analyze_portfolio,
)
from personal_alpha_terminal.portfolio.management_report import (
    render_portfolio_management_report,
)
from personal_alpha_terminal.portfolio.management_repository import (
    PortfolioManagementRepository,
)
from personal_alpha_terminal.portfolio.management_schemas import (
    PortfolioManagementResult,
    TransactionDraft,
)
from personal_alpha_terminal.reports.service import ResearchReportService


class PortfolioManagementService:
    def __init__(
        self,
        repository: PortfolioManagementRepository,
        report_service: ResearchReportService,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._report_service = report_service
        self._settings = settings

    def record_transaction(
        self,
        *,
        portfolio_id: int,
        draft: TransactionDraft,
    ) -> PortfolioTransaction:
        self._validate_draft(draft)
        return self._repository.add_transaction(portfolio_id=portfolio_id, draft=draft)

    def set_allocation_targets(
        self,
        *,
        portfolio_id: int,
        effective_date: date,
        targets: tuple[tuple[int | None, str | None, float, str | None], ...],
    ) -> None:
        if not targets:
            raise ValueError("at least one allocation target is required")
        if abs(sum(item[2] for item in targets) - 1.0) > 1e-6:
            raise ValueError("allocation target weights must sum to 1")
        for stock_id, cash_currency, weight, _ in targets:
            if (stock_id is None) == (cash_currency is None):
                raise ValueError("each target must identify exactly one asset or cash currency")
            if not 0 <= weight <= 1:
                raise ValueError("allocation target weight must be between 0 and 1")
        self._repository.replace_targets(
            portfolio_id=portfolio_id,
            effective_date=effective_date,
            targets=targets,
        )

    def analyze(
        self,
        *,
        portfolio_id: int,
        benchmark_stock_id: int,
        start_date: date,
        end_date: date,
    ) -> PortfolioManagementResult:
        data = self._repository.load_data(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_stock_id,
            start_date=start_date,
            end_date=end_date,
            price_max_staleness_days=self._settings.portfolio_price_max_staleness_days,
            fx_max_staleness_days=self._settings.portfolio_fx_max_staleness_days,
        )
        return analyze_portfolio(
            data,
            annual_risk_free_rate=self._settings.portfolio_risk_annual_risk_free_rate,
            minimum_observations=self._settings.portfolio_risk_minimum_observations,
            price_max_staleness_days=self._settings.portfolio_price_max_staleness_days,
            fx_max_staleness_days=self._settings.portfolio_fx_max_staleness_days,
            rebalance_drift_threshold=self._settings.portfolio_rebalance_drift_threshold,
            minimum_rebalance_value=self._settings.portfolio_minimum_rebalance_value,
        )

    def generate_report(
        self,
        *,
        portfolio_id: int,
        benchmark_stock_id: int,
        start_date: date,
        end_date: date,
        output_path: Path,
    ) -> tuple[PortfolioManagementResult, ResearchReport]:
        result = self.analyze(
            portfolio_id=portfolio_id,
            benchmark_stock_id=benchmark_stock_id,
            start_date=start_date,
            end_date=end_date,
        )
        document = render_portfolio_management_report(result)
        report = self._report_service.save(document)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(document.markdown, encoding="utf-8")
        temporary.replace(output_path)
        return result, report

    @staticmethod
    def _validate_draft(draft: TransactionDraft) -> None:
        if draft.transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError("unsupported transaction type")
        if draft.available_time < draft.event_time:
            raise ValueError("available_time must not precede event_time")
        if draft.settlement_date < draft.trade_date:
            raise ValueError("settlement_date must not precede trade_date")
        if len(draft.currency) != 3 or draft.currency != draft.currency.upper():
            raise ValueError("currency must be a three-letter uppercase code")
        if draft.fx_rate_to_base <= 0:
            raise ValueError("fx_rate_to_base must be positive")
        if draft.fee_amount < 0:
            raise ValueError("fee_amount cannot be negative")
        asset_required = draft.transaction_type in {"buy", "sell", "dividend", "split"}
        if asset_required != (draft.stock_id is not None):
            if not (draft.transaction_type == "fee" and draft.stock_id is not None):
                raise ValueError("transaction asset payload does not match transaction type")
        if draft.transaction_type in {"buy", "sell"}:
            if draft.quantity is None or draft.quantity <= 0:
                raise ValueError("buy/sell quantity must be positive")
            if draft.unit_price is None or draft.unit_price <= 0:
                raise ValueError("buy/sell unit price must be positive")
            if draft.cash_amount is not None:
                raise ValueError("buy/sell cash_amount must be omitted")
        elif draft.transaction_type == "split":
            if draft.quantity is None or draft.quantity <= 0:
                raise ValueError("split ratio must be positive")
            if draft.unit_price is not None or draft.cash_amount is not None:
                raise ValueError("split accepts only the ratio in quantity")
        else:
            if draft.cash_amount is None or draft.cash_amount <= 0:
                raise ValueError("cash transaction amount must be positive")
            if draft.quantity is not None or draft.unit_price is not None:
                raise ValueError("cash transaction cannot include quantity or unit price")

