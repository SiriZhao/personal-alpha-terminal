"""ROUND 7: permanent identifiers and symbol-history resolution.

A ticker is not a stable historical identity.  ``instrument_id`` is the internal
stable identity, ``provider_permanent_id`` is the provider's permanent id, and
symbol history maps ticker vintages to the same instrument so a ticker change is
never treated as a new company.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.research_dataset import HistoricalSecurity


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    instrument_id: str
    provider_permanent_id: str
    ticker_history: tuple[tuple[str, date, date | None], ...]

    def document(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "provider_permanent_id": self.provider_permanent_id,
            "ticker_history": [
                {
                    "ticker": ticker,
                    "valid_from": start.isoformat(),
                    "valid_to": end.isoformat() if end else None,
                }
                for ticker, start, end in self.ticker_history
            ],
        }

    @property
    def identity_hash(self) -> str:
        return fingerprint(self.document())


@dataclass(frozen=True, slots=True)
class IdentifierRegistryResult:
    instruments: tuple[InstrumentIdentity, ...]
    blockers: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return {
            "instrument_count": len(self.instruments),
            "instruments": [item.document() for item in self.instruments],
            "blockers": list(self.blockers),
        }


def build_instrument_registry(
    securities: tuple[HistoricalSecurity, ...],
) -> IdentifierRegistryResult:
    """Group security vintages by the provider's permanent identity.

    A permanent_security_id may carry several ticker vintages over time; all of
    them belong to one instrument.  Overlapping ticker vintages for the same
    permanent id are a blocker (ambiguous history).
    """
    by_permanent: dict[str, list[HistoricalSecurity]] = {}
    for item in securities:
        key = item.provider_security_id or item.cusip or item.figi or item.permanent_security_id
        by_permanent.setdefault(key, []).append(item)

    blockers: list[str] = []
    instruments: list[InstrumentIdentity] = []
    for permanent_id, vintages in sorted(by_permanent.items()):
        ordered = sorted(vintages, key=lambda item: (item.ticker_valid_from, item.ticker))
        history: list[tuple[str, date, date | None]] = []
        for index, vintage in enumerate(ordered):
            if index > 0:
                previous = history[-1]
                previous_end = previous[2]
                if previous_end is None or vintage.ticker_valid_from < previous_end:
                    blockers.append(
                        f"OVERLAPPING_TICKER_VINTAGE:{permanent_id}:{vintage.ticker}"
                    )
            history.append(
                (
                    vintage.ticker,
                    vintage.ticker_valid_from,
                    vintage.ticker_valid_to,
                )
            )
        instruments.append(
            InstrumentIdentity(
                instrument_id=permanent_id,
                provider_permanent_id=permanent_id,
                ticker_history=tuple(history),
            )
        )
    return IdentifierRegistryResult(tuple(instruments), tuple(sorted(set(blockers))))


def resolve_ticker_on(
    registry: IdentifierRegistryResult,
    ticker: str,
    as_of: date,
) -> tuple[str, ...]:
    """Return every instrument id whose ticker history covers ``ticker`` on ``as_of``."""
    matches: list[str] = []
    for instrument in registry.instruments:
        for symbol, start, end in instrument.ticker_history:
            if symbol == ticker and start <= as_of and (end is None or as_of <= end):
                matches.append(instrument.instrument_id)
                break
    return tuple(sorted(matches))


def symbol_history(
    registry: IdentifierRegistryResult,
    instrument_id: str,
) -> tuple[tuple[str, date, date | None], ...]:
    for instrument in registry.instruments:
        if instrument.instrument_id == instrument_id:
            return instrument.ticker_history
    return ()
