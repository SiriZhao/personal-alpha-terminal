from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    AssetType,
    PriceType,
    ProviderCapability,
    ProviderRawBar,
    ProviderRawBatch,
    RawVolumeUnit,
    VolumeUnit,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.ports import MarketDataProvider


@dataclass(frozen=True, slots=True)
class LocalArchiveContract:
    asset_type: AssetType
    raw_volume_unit: RawVolumeUnit
    volume_unit: VolumeUnit
    price_type: PriceType
    volume_multiplier: Decimal = Decimal("1")
    raw_share_unit: Decimal = Decimal("1")


class LocalUSArchiveProvider:
    """Read a versioned vendor archive without silently inventing PIT lineage.

    Files live at ``root/<asset_type>/<symbol>.csv``. Stock, ETF and index
    adapters are separate instances; an absent file is an error, never a
    fallback to another asset endpoint.
    """

    source = "local_versioned_archive"

    def __init__(
        self,
        root: Path,
        *,
        provider_id: str,
        contract: LocalArchiveContract,
    ) -> None:
        self.root = root.resolve()
        self.provider_id = provider_id
        self.contract = contract
        self.capabilities = (
            ProviderCapability(
                provider=provider_id,
                market="US",
                asset_type=contract.asset_type,
                endpoint=f"local-archive://{contract.asset_type}",
                raw_volume_unit=contract.raw_volume_unit,
                volume_unit=contract.volume_unit,
                price_type=contract.price_type,
                supported=True,
                volume_multiplier=contract.volume_multiplier,
                raw_share_unit=contract.raw_share_unit,
            ),
        )

    def fetch_raw(self, request: AssetPriceRequest) -> ProviderRawBatch:
        capability = self.capabilities[0]
        if request.market != "US" or request.asset_type != self.contract.asset_type:
            raise ProviderRequestError("local archive request violates its typed capability")
        path = (self.root / request.asset_type / f"{request.symbol}.csv").resolve()
        if self.root not in path.parents:
            raise ProviderRequestError("unsafe local archive path")
        if not path.is_file():
            raise ProviderRequestError(f"local archive file not found: {path.name}")
        rows: list[ProviderRawBar] = []
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "event_time",
                    "available_time",
                    "ingested_time",
                }
                if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                    missing = sorted(required - set(reader.fieldnames or ()))
                    raise ProviderRequestError(
                        f"local archive is missing required columns: {missing}"
                    )
                for item in reader:
                    trade_date = date.fromisoformat(item["date"])
                    if not request.start_date <= trade_date <= request.end_date:
                        continue
                    rows.append(self._parse_row(item, request, trade_date))
        except ProviderRequestError:
            raise
        except (OSError, ValueError, ArithmeticError) as exc:
            raise ProviderRequestError(f"invalid local archive: {exc}") from exc
        return ProviderRawBatch(capability=capability, request=request, rows=tuple(rows))

    def _parse_row(
        self,
        item: dict[str, str],
        request: AssetPriceRequest,
        trade_date: date,
    ) -> ProviderRawBar:
        capability = self.capabilities[0]
        volume_text = item.get("volume", "").strip()
        adjusted_text = item.get("adjusted_close", "").strip()
        return ProviderRawBar(
            symbol=request.symbol,
            market="US",
            asset_type=request.asset_type,
            date=trade_date,
            open=Decimal(item["open"]),
            high=Decimal(item["high"]),
            low=Decimal(item["low"]),
            close=Decimal(item["close"]),
            volume=Decimal(volume_text) if volume_text else None,
            raw_volume_unit=capability.raw_volume_unit,
            price_currency=request.price_currency,
            raw_share_unit=capability.raw_share_unit,
            price_type=capability.price_type,
            adjusted_close=Decimal(adjusted_text) if adjusted_text else None,
            adjustment_method=item.get("adjustment_method") or None,
            open_tradable=_optional_bool(item.get("open_tradable")),
            event_time=datetime.fromisoformat(item["event_time"]),
            available_time=datetime.fromisoformat(item["available_time"]),
            ingested_time=datetime.fromisoformat(item["ingested_time"]),
        )


class USProviderCatalog:
    """Explicit provider roles; verifier and local cache never replace primary silently."""

    def __init__(self) -> None:
        self._providers: dict[tuple[str, AssetType], MarketDataProvider] = {}
        self._roles: dict[tuple[str, AssetType], str] = {}

    def register(
        self,
        provider: MarketDataProvider,
        *,
        asset_type: AssetType,
        role: str,
    ) -> None:
        if role not in {"primary", "verification", "local_cache"}:
            raise ValueError("provider role must be primary, verification, or local_cache")
        matching = [
            item
            for item in provider.capabilities
            if item.market == "US" and item.asset_type == asset_type and item.supported
        ]
        if len(matching) != 1:
            raise ValueError("provider must expose one supported capability for this US asset")
        key = (role, asset_type)
        if key in self._providers:
            raise ValueError(f"provider role is already registered: {key}")
        self._providers[key] = provider
        self._roles[key] = provider.provider_id

    def provider(self, *, role: str, asset_type: AssetType) -> MarketDataProvider:
        try:
            return self._providers[(role, asset_type)]
        except KeyError as exc:
            raise ProviderRequestError(
                f"no explicit US {role} provider for asset type {asset_type}"
            ) from exc

    def fetch_pair(
        self,
        request: AssetPriceRequest,
    ) -> tuple[ProviderRawBatch, ProviderRawBatch]:
        primary = self.provider(role="primary", asset_type=request.asset_type)
        verifier = self.provider(role="verification", asset_type=request.asset_type)
        if primary.provider_id == verifier.provider_id:
            raise ProviderRequestError("certification requires independent provider identities")
        return primary.fetch_raw(request), verifier.fetch_raw(request)

    def status(self) -> dict[str, str]:
        return {
            f"{role}:{asset_type}": provider_id
            for (role, asset_type), provider_id in sorted(self._roles.items())
        }


def _optional_bool(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"invalid boolean: {value!r}")
