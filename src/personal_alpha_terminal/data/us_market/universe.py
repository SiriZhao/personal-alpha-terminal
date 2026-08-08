from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps

from personal_alpha_terminal.data.market_data_quality.schemas import UniverseCandidate


@dataclass(frozen=True, slots=True)
class USUniverseRules:
    minimum_price: float = 5.0
    minimum_average_dollar_volume: float = 10_000_000.0
    minimum_listing_sessions: int = 252
    allowed_exchanges: tuple[str, ...] = ("NYSE", "NASDAQ")
    allowed_asset_types: tuple[str, ...] = ("stock", "etf")

    def __post_init__(self) -> None:
        if self.minimum_price <= 0 or self.minimum_average_dollar_volume <= 0:
            raise ValueError("universe price and liquidity thresholds must be positive")
        if self.minimum_listing_sessions < 1:
            raise ValueError("minimum_listing_sessions must be positive")


@dataclass(frozen=True, slots=True)
class USUniverseObservation:
    candidate: UniverseCandidate
    latest_price: float | None
    average_dollar_volume: float | None
    observed_sessions: int
    data_quality_passed: bool
    special_security: bool = False


@dataclass(frozen=True, slots=True)
class USUniverseBuildResult:
    members: tuple[UniverseCandidate, ...]
    exclusions: dict[int, tuple[str, ...]]
    rules_fingerprint: str


def build_us_research_universe(
    observations: tuple[USUniverseObservation, ...],
    rules: USUniverseRules,
) -> USUniverseBuildResult:
    """Deterministic filter; membership sources remain attached to each candidate."""

    members: list[UniverseCandidate] = []
    exclusions: dict[int, tuple[str, ...]] = {}
    seen: set[int] = set()
    for item in sorted(observations, key=lambda value: value.candidate.stock_id):
        candidate = item.candidate
        if candidate.stock_id in seen:
            raise ValueError("universe observations contain duplicate stock ids")
        seen.add(candidate.stock_id)
        reasons: list[str] = []
        if candidate.market != "US":
            reasons.append("non_us_market")
        if candidate.exchange.upper() not in rules.allowed_exchanges:
            reasons.append("unsupported_exchange")
        if candidate.asset_type.lower() not in rules.allowed_asset_types:
            reasons.append("unsupported_security_type")
        if item.special_security:
            reasons.append("special_security")
        if item.latest_price is None or item.latest_price < rules.minimum_price:
            reasons.append("price_below_threshold_or_missing")
        if (
            item.average_dollar_volume is None
            or item.average_dollar_volume < rules.minimum_average_dollar_volume
        ):
            reasons.append("liquidity_below_threshold_or_missing")
        if item.observed_sessions < rules.minimum_listing_sessions:
            reasons.append("insufficient_listing_history")
        if not item.data_quality_passed:
            reasons.append("data_quality_not_passed")
        if reasons:
            exclusions[candidate.stock_id] = tuple(reasons)
        else:
            members.append(candidate)
    fingerprint = sha256(
        dumps(
            {
                "rules": asdict(rules),
                "member_ids": [item.stock_id for item in members],
                "exclusions": {str(key): value for key, value in sorted(exclusions.items())},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return USUniverseBuildResult(tuple(members), exclusions, fingerprint)
