from datetime import UTC, date, datetime, time

from personal_alpha_terminal.data.market_data.policies import policy_for_market
from personal_alpha_terminal.data.market_data_quality.history import (
    HistoricalQualityAnalyzer,
)
from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.sampling import (
    DEFAULT_SAMPLING_PLAN,
    select_stratified_sample,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    QualityReport,
    RunStatus,
    SamplingPlan,
)


class MarketDataQualityService:
    def __init__(
        self,
        repository: MarketDataQualityRepository,
        analyzer: HistoricalQualityAnalyzer | None = None,
    ) -> None:
        self._repository = repository
        self._analyzer = analyzer or HistoricalQualityAnalyzer()

    def run(
        self,
        *,
        history_start: date = date(2010, 1, 1),
        history_end: date | None = None,
        seed: int = 20260731,
        plan: SamplingPlan = DEFAULT_SAMPLING_PLAN,
    ) -> tuple[int, QualityReport]:
        end_date = history_end or date.today()
        if history_start > end_date:
            raise ValueError("history_start cannot be later than history_end.")

        current_time = datetime.now(UTC)
        snapshot_cutoff = (
            current_time
            if end_date >= current_time.date()
            else datetime.combine(end_date, time.max, tzinfo=UTC)
        )
        snapshots = self._repository.latest_snapshot_ids(
            end_date,
            available_by=snapshot_cutoff,
        )
        blockers: list[str] = []
        missing_markets = sorted({"A", "HK", "US"} - set(snapshots))
        if missing_markets:
            blockers.append(
                "Missing traceable universe snapshots for markets: " + ", ".join(missing_markets)
            )

        candidates = self._repository.candidates(list(snapshots.values()))
        invalid_security_lineage = [
            item
            for item in candidates
            if item.source in {"", "unknown", "legacy_unknown"}
            or item.provider in {"", "unknown", "legacy_unknown"}
            or item.available_time is None
            or item.ingested_time is None
        ]
        if invalid_security_lineage:
            blockers.append(
                "Security master lineage is incomplete for "
                f"{len(invalid_security_lineage)} universe members."
            )
        sample = select_stratified_sample(candidates, plan=plan, seed=seed)
        blockers.extend(sample.shortages)

        results = []
        for candidate in sample.selected:
            sessions = self._repository.calendar_sessions(
                exchange=candidate.exchange,
                start_date=history_start,
                end_date=end_date,
            )
            bars = self._repository.price_history(
                stock_id=candidate.stock_id,
                start_date=history_start,
                end_date=end_date,
                source=policy_for_market(candidate.market).primary_source,
            )
            actions = self._repository.corporate_actions(
                stock_id=candidate.stock_id,
                start_date=history_start,
                end_date=end_date,
            )
            results.append(
                self._analyzer.analyze(
                    instrument=candidate,
                    bars=bars,
                    sessions=sessions,
                    corporate_actions=actions,
                    start_date=history_start,
                    end_date=end_date,
                )
            )

        stock_ids = [item.stock_id for item in sample.selected]
        source_counts, provider_counts = self._repository.lineage_counts(stock_ids)
        if not results:
            status = RunStatus.BLOCKED
        elif blockers:
            status = RunStatus.BLOCKED
        elif any(not item.passed for item in results):
            status = RunStatus.FAILED
        else:
            status = RunStatus.PASSED

        report = QualityReport(
            generated_at=datetime.now(UTC),
            history_start=history_start,
            history_end=end_date,
            status=status,
            sample=sample,
            instrument_results=tuple(results),
            source_counts=source_counts,
            provider_counts=provider_counts,
            blockers=tuple(blockers),
        )
        run_id = self._repository.persist_report(
            report=report,
            snapshot_ids=list(snapshots.values()),
            random_seed=seed,
            minimum_sample_size=plan.minimum_total,
        )
        return run_id, report
