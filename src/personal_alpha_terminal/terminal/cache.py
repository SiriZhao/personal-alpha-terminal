from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, timedelta
from pathlib import Path

import pandas as pd

from personal_alpha_terminal.terminal.providers import ProviderResult


@dataclass(frozen=True, slots=True)
class CacheLineage:
    symbol: str
    provider: str
    endpoint: str
    requested_at: str
    completed_at: str
    adjustment_policy: str
    start_date: str
    end_date: str
    row_count: int
    content_hash: str
    cache_hash: str
    schema_version: str = "terminal-canonical-v2"
    verified_sources: tuple[str, ...] = ()
    provider_disagreement: float | None = None


class DailyPriceCache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _price_path(self, symbol: str) -> Path:
        return self.directory / f"{symbol.replace('^', 'INDEX_')}_daily.parquet"

    def _manifest_path(self, symbol: str) -> Path:
        return self.directory / f"{symbol.replace('^', 'INDEX_')}_daily.manifest.json"

    def load(self, symbol: str) -> tuple[pd.DataFrame, CacheLineage] | None:
        price_path, manifest_path = self._price_path(symbol), self._manifest_path(symbol)
        if not price_path.exists() or not manifest_path.exists():
            return None
        try:
            frame = pd.read_parquet(price_path)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            lineage = CacheLineage(**payload)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError(f"cache corruption for {symbol}: {error}") from error
        return frame, lineage

    def save(self, result: ProviderResult) -> CacheLineage:
        self.directory.mkdir(parents=True, exist_ok=True)
        frame = (
            result.frame.sort_values("date")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True)
        )
        cache_hash = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
        lineage = CacheLineage(
            symbol=result.symbol,
            provider=result.provider,
            endpoint=result.endpoint,
            requested_at=result.requested_at.astimezone(UTC).isoformat(),
            completed_at=result.completed_at.astimezone(UTC).isoformat(),
            adjustment_policy=result.adjustment_policy,
            start_date=str(frame["date"].min().date()),
            end_date=str(frame["date"].max().date()),
            row_count=len(frame),
            content_hash=result.content_hash,
            cache_hash=cache_hash,
            verified_sources=result.verified_sources,
            provider_disagreement=result.provider_disagreement,
        )
        price_path = self._price_path(result.symbol)
        manifest_path = self._manifest_path(result.symbol)
        temporary_price = price_path.with_suffix(".parquet.tmp")
        temporary_manifest = manifest_path.with_suffix(".json.tmp")
        frame.to_parquet(temporary_price, index=False)
        temporary_manifest.write_text(
            json.dumps(asdict(lineage), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_price.replace(price_path)
        temporary_manifest.replace(manifest_path)
        return lineage

    def merge_and_save(self, symbol: str, result: ProviderResult) -> CacheLineage:
        existing = self.load(symbol)
        if existing is None:
            return self.save(result)
        prior, _lineage = existing
        merged = pd.concat([prior, result.frame], ignore_index=True)
        merged = (
            merged.sort_values("date")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True)
        )
        return self.save(
            ProviderResult(
                symbol=result.symbol,
                frame=merged,
                provider=result.provider,
                endpoint=result.endpoint,
                requested_at=result.requested_at,
                completed_at=result.completed_at,
                adjustment_policy=result.adjustment_policy,
                content_hash=result.content_hash,
                exchange=result.exchange,
                asset_type=result.asset_type,
                verified_sources=result.verified_sources,
                provider_disagreement=result.provider_disagreement,
            )
        )

    @staticmethod
    def incremental_start(frame: pd.DataFrame, default_start: date) -> date:
        if frame.empty:
            return default_start
        latest_value = pd.Timestamp(frame["date"].max()).date()
        latest = date(latest_value.year, latest_value.month, latest_value.day)
        return max(default_start, latest - timedelta(days=7))
