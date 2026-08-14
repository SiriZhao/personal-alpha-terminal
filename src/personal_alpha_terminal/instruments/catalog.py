"""ROUND24 deterministic ETF catalog loader.

The catalog is a committed JSON file (``data/etf_catalog.json``).  It is the
deterministic classification source for ETF attributes; the LLM is never
consulted for instrument classification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_SCHEMA_VERSION = "pat-etf-catalog-v1"
DEFAULT_CATALOG_PATH = Path("data/etf_catalog.json")


class CatalogError(ValueError):
    """Raised when the deterministic catalog is missing or malformed."""


@dataclass(frozen=True, slots=True)
class EtfCatalog:
    schema_version: str
    entries: tuple[dict[str, object], ...]
    source_path: str

    def __post_init__(self) -> None:
        if self.schema_version != CATALOG_SCHEMA_VERSION:
            raise CatalogError(
                "etf catalog schema mismatch: "
                f"expected {CATALOG_SCHEMA_VERSION}, got {self.schema_version}"
            )

    def by_symbol(self) -> dict[str, dict[str, object]]:
        return {str(item["symbol"]): item for item in self.entries}

    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(str(item["symbol"]) for item in self.entries))

    def tradable_symbols(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                str(item["symbol"])
                for item in self.entries
                if not item.get("complex_product", False)
            )
        )

    def complex_product_symbols(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                str(item["symbol"])
                for item in self.entries
                if item.get("complex_product", False)
            )
        )


def load_catalog(path: Path | str | None = None) -> EtfCatalog:
    source = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CatalogError(f"ETF catalog missing at {source}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"ETF catalog malformed at {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError("ETF catalog root must be a JSON object")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CatalogError("ETF catalog entries must be a non-empty list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or "symbol" not in entry:
            raise CatalogError(f"ETF catalog entry {index} lacks a symbol")
    return EtfCatalog(
        schema_version=str(payload.get("schema_version")),
        entries=tuple(entries),
        source_path=str(source),
    )


@lru_cache(maxsize=1)
def default_catalog() -> EtfCatalog:
    return load_catalog()
