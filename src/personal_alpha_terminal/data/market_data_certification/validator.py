from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from itertools import combinations

from personal_alpha_terminal.data.market_data_certification.schemas import (
    CertificationFinding,
    CertificationGateResult,
    CertificationStatus,
    CorporateActionEvidence,
    InstrumentCertificationResult,
    InstrumentEvidence,
    SourceBar,
    ValidationThresholds,
)
from personal_alpha_terminal.data.market_data_quality.sampling import (
    REAL_MARKET_CERTIFICATION_PLAN,
)


class RealMarketDataCertificationValidator:
    def __init__(self, thresholds: ValidationThresholds | None = None) -> None:
        self._thresholds = thresholds or ValidationThresholds()

    def validate_instrument(
        self,
        evidence: InstrumentEvidence,
    ) -> InstrumentCertificationResult:
        findings: list[CertificationFinding] = []
        expected = set(evidence.expected_sessions)
        if not expected:
            findings.append(self._finding("missing_calendar", "No verified sessions supplied."))

        bars_by_source: dict[str, dict[date, SourceBar]] = defaultdict(dict)
        for bar in evidence.bars:
            if not bar.source.strip() or not bar.provider.strip():
                findings.append(self._finding("missing_bar_lineage", "Bar lineage is empty."))
                continue
            if bar.trade_date in bars_by_source[bar.source]:
                findings.append(
                    self._finding(
                        "duplicate_source_bar",
                        f"Duplicate {bar.source} bar at the intended daily grain.",
                        bar.trade_date,
                    )
                )
            bars_by_source[bar.source][bar.trade_date] = bar
            if bar.trade_date not in expected:
                findings.append(
                    self._finding(
                        "off_calendar_bar",
                        f"{bar.source} returned a bar outside the verified calendar.",
                        bar.trade_date,
                    )
                )
            if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
                findings.append(
                    self._finding(
                        "invalid_ohlcv",
                        f"{bar.source} returned non-positive price or negative volume.",
                        bar.trade_date,
                    )
                )
            if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(
                bar.open, bar.close, bar.high
            ):
                findings.append(
                    self._finding(
                        "invalid_ohlc_order",
                        f"{bar.source} violates OHLC ordering.",
                        bar.trade_date,
                    )
                )

        source_names = sorted(bars_by_source)
        if len(source_names) < 2:
            findings.append(
                self._finding("insufficient_price_sources", "Fewer than two independent sources.")
            )

        status_sources: dict[date, set[str]] = defaultdict(set)
        for item in evidence.trading_status:
            if item.status.lower() in {"suspended", "halted", "delisted"}:
                status_sources[item.session_date].add(item.source)

        for source, source_bars in bars_by_source.items():
            covered = expected & set(source_bars)
            resolved_status_dates = {
                day
                for day in expected - set(source_bars)
                if len(status_sources.get(day, set())) >= 2
            }
            unresolved = {
                day
                for day in expected - set(source_bars)
                if len(status_sources.get(day, set())) < 2
            }
            coverage = self._ratio(len(covered | resolved_status_dates), len(expected))
            if coverage < self._thresholds.minimum_source_coverage or unresolved:
                findings.append(
                    self._finding(
                        "incomplete_source_history",
                        f"{source} coverage={coverage:.2%}; unresolved sessions={len(unresolved)}.",
                        min(unresolved) if unresolved else None,
                    )
                )

        matched_sessions: set[date] = set()
        price_mismatches: set[date] = set()
        volume_mismatches: set[date] = set()
        for left_name, right_name in combinations(source_names, 2):
            left = bars_by_source[left_name]
            right = bars_by_source[right_name]
            common = expected & set(left) & set(right)
            matched_sessions.update(common)
            pair_price_mismatches = {
                day
                for day in common
                if any(
                    self._relative_error(getattr(left[day], field), getattr(right[day], field))
                    > self._thresholds.maximum_price_relative_error
                    for field in ("open", "high", "low", "close")
                )
            }
            pair_volume_mismatches = {
                day
                for day in common
                if self._relative_error(left[day].volume, right[day].volume)
                > self._thresholds.maximum_volume_relative_error
            }
            price_mismatches.update(pair_price_mismatches)
            volume_mismatches.update(pair_volume_mismatches)

        matched_sessions.update(
            day for day in expected if len(status_sources.get(day, set())) >= 2
        )
        match_ratio = self._ratio(len(matched_sessions), len(expected))
        if match_ratio < self._thresholds.minimum_cross_source_match:
            findings.append(
                self._finding(
                    "insufficient_cross_source_overlap",
                    f"Cross-source matched-session ratio is {match_ratio:.2%}.",
                )
            )
        if price_mismatches:
            findings.append(
                self._finding(
                    "price_source_disagreement",
                    f"OHLC disagreement exceeds tolerance on {len(price_mismatches)} sessions.",
                    min(price_mismatches),
                )
            )
        if volume_mismatches:
            findings.append(
                self._finding(
                    "volume_source_disagreement",
                    f"Volume disagreement exceeds tolerance on {len(volume_mismatches)} sessions.",
                    min(volume_mismatches),
                )
            )

        findings.extend(self._validate_actions(evidence, bars_by_source))
        if evidence.delisting_date is not None:
            post_delist = sorted(
                bar.trade_date
                for bar in evidence.bars
                if bar.trade_date > evidence.delisting_date
            )
            if post_delist:
                findings.append(
                    self._finding(
                        "post_delisting_bar",
                        "A provider returned prices after the verified delisting date.",
                        post_delist[0],
                    )
                )

        blocked_codes = {
            "missing_calendar",
            "insufficient_price_sources",
            "insufficient_action_sources",
            "incomplete_source_history",
            "insufficient_cross_source_overlap",
        }
        status = (
            CertificationStatus.BLOCKED
            if any(item.code in blocked_codes for item in findings)
            else CertificationStatus.FAILED
            if findings
            else CertificationStatus.PASSED
        )
        action_types = {item.action_type for item in evidence.actions}
        return InstrumentCertificationResult(
            symbol=evidence.symbol,
            market=evidence.market,
            segment=evidence.segment,
            security_type=evidence.security_type,
            status=status,
            source_count=len(source_names),
            expected_sessions=len(expected),
            matched_sessions=len(matched_sessions),
            price_mismatches=len(price_mismatches),
            volume_mismatches=len(volume_mismatches),
            findings=tuple(findings),
            has_suspension_case=bool(status_sources),
            has_delisting_case=evidence.delisting_date is not None,
            has_split_case="split" in action_types or "reverse_split" in action_types,
            has_dividend_case="cash_dividend" in action_types,
            random_sample=evidence.random_sample,
        )

    def validate_gate(
        self,
        evidence: tuple[InstrumentEvidence, ...],
    ) -> CertificationGateResult:
        results = tuple(self.validate_instrument(item) for item in evidence)
        blockers: list[str] = []
        keys = [(item.market, item.symbol) for item in evidence if item.random_sample]
        if len(keys) != len(set(keys)):
            blockers.append("Random sample contains duplicate market/symbol keys.")
        if len(keys) < self._thresholds.minimum_random_sample:
            blockers.append(
                f"Random sample requires {self._thresholds.minimum_random_sample}, got {len(keys)}."
            )

        segment_counts = Counter(
            item.segment.value for item in evidence if item.random_sample
        )
        for segment, quota in REAL_MARKET_CERTIFICATION_PLAN.segment_quotas.items():
            actual = segment_counts.get(segment.value, 0)
            if actual < quota:
                blockers.append(f"{segment.value} requires {quota}, got {actual}.")

        self._require_cases(
            blockers,
            label="suspension",
            minimum=self._thresholds.minimum_suspension_cases,
            actual=sum(item.has_suspension_case for item in results),
        )
        self._require_cases(
            blockers,
            label="delisted",
            minimum=self._thresholds.minimum_delisted_cases,
            actual=sum(item.has_delisting_case for item in results),
        )
        self._require_cases(
            blockers,
            label="split",
            minimum=self._thresholds.minimum_split_cases,
            actual=sum(item.has_split_case for item in results),
        )
        self._require_cases(
            blockers,
            label="dividend",
            minimum=self._thresholds.minimum_dividend_cases,
            actual=sum(item.has_dividend_case for item in results),
        )
        if any(item.status != CertificationStatus.PASSED for item in results):
            blockers.append("One or more instrument certifications did not pass.")
        status = CertificationStatus.PASSED if not blockers else CertificationStatus.BLOCKED
        return CertificationGateResult(
            status=status,
            results=results,
            blockers=tuple(blockers),
            segment_counts=dict(sorted(segment_counts.items())),
        )

    def _validate_actions(
        self,
        evidence: InstrumentEvidence,
        bars_by_source: dict[str, dict[date, SourceBar]],
    ) -> list[CertificationFinding]:
        findings: list[CertificationFinding] = []
        coverage_sources = {item for item in evidence.action_coverage_sources if item.strip()}
        if len(coverage_sources) < 2:
            findings.append(
                self._finding(
                    "insufficient_action_sources",
                    "Corporate actions are not covered by two independent sources.",
                )
            )
            return findings
        actions_by_key: dict[tuple[str, date], list[CorporateActionEvidence]] = defaultdict(list)
        for action in evidence.actions:
            actions_by_key[(action.action_type, action.effective_date)].append(action)
        for (action_type, effective_date), actions in actions_by_key.items():
            sources = {item.source for item in actions}
            if not coverage_sources <= sources:
                findings.append(
                    self._finding(
                        "corporate_action_source_disagreement",
                        f"{action_type} is not confirmed by every declared action source.",
                        effective_date,
                    )
                )
                continue
            values = [
                item.split_ratio if "split" in action_type else item.cash_amount
                for item in actions
            ]
            populated = [item for item in values if item is not None]
            if len(populated) != len(actions) or any(
                self._relative_error(left, right)
                > self._thresholds.maximum_action_value_relative_error
                for left, right in combinations(populated, 2)
            ):
                findings.append(
                    self._finding(
                        "corporate_action_value_disagreement",
                        f"{action_type} value differs across sources.",
                        effective_date,
                    )
                )
            if "split" in action_type:
                findings.extend(
                    self._validate_split_adjustment(
                        effective_date=effective_date,
                        split_ratio=populated[0] if populated else None,
                        bars_by_source=bars_by_source,
                    )
                )
        return findings

    def _validate_split_adjustment(
        self,
        *,
        effective_date: date,
        split_ratio: Decimal | None,
        bars_by_source: dict[str, dict[date, SourceBar]],
    ) -> list[CertificationFinding]:
        findings: list[CertificationFinding] = []
        if split_ratio is None or split_ratio <= 0:
            return [self._finding("invalid_split_ratio", "Split ratio must be positive.")]
        for source, bars in bars_by_source.items():
            dates = sorted(bars)
            if effective_date not in bars:
                continue
            index = dates.index(effective_date)
            if index == 0:
                continue
            previous = bars[dates[index - 1]]
            current = bars[effective_date]
            expected_raw_ratio = Decimal("1") / split_ratio
            raw_ratio = current.close / previous.close
            if self._relative_error(raw_ratio, expected_raw_ratio) > Decimal("0.20"):
                findings.append(
                    self._finding(
                        "split_raw_price_mismatch",
                        f"{source} raw price does not reflect the recorded split ratio.",
                        effective_date,
                    )
                )
            if previous.adjusted_close is None or current.adjusted_close is None:
                findings.append(
                    self._finding(
                        "missing_adjusted_split_prices",
                        f"{source} lacks adjusted closes around a split.",
                        effective_date,
                    )
                )
            elif abs(current.adjusted_close / previous.adjusted_close - Decimal("1")) > Decimal(
                "0.60"
            ):
                findings.append(
                    self._finding(
                        "split_adjustment_discontinuity",
                        f"{source} adjusted return remains implausibly discontinuous.",
                        effective_date,
                    )
                )
        return findings

    @staticmethod
    def _relative_error(left: Decimal, right: Decimal) -> Decimal:
        denominator = max(abs(left), abs(right), Decimal("0.00000001"))
        return abs(left - right) / denominator

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> Decimal:
        return Decimal(numerator) / Decimal(denominator) if denominator else Decimal("0")

    @staticmethod
    def _finding(
        code: str,
        message: str,
        trade_date: date | None = None,
    ) -> CertificationFinding:
        return CertificationFinding(code, "high", message, trade_date)

    @staticmethod
    def _require_cases(
        blockers: list[str],
        *,
        label: str,
        minimum: int,
        actual: int,
    ) -> None:
        if actual < minimum:
            blockers.append(f"{label} cases require {minimum}, got {actual}.")
