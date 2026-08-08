import csv
import importlib
import io
import re
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment
from personal_alpha_terminal.data.production_market_data.schemas import (
    SecurityMasterBatch,
    SecurityMasterRecord,
)

HKEX_FULL_LIST_URL = (
    "https://www.hkex.com.hk/eng/services/trading/securities/"
    "securitieslists/ListOfSecurities.xlsx"
)
NASDAQ_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
)
NASDAQ_OTHER_LISTED_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
)


class AKShareASecurityMasterAdapter:
    source = "sse_szse_official_security_lists"
    provider = "akshare.security_master.a"

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch:
        if as_of_date != date.today():
            raise ValueError(
                "AKShare current-list endpoints cannot reconstruct a historical snapshot"
            )
        library = self._load_library()
        ingested = datetime.now(UTC)
        records: list[SecurityMasterRecord] = []
        for board, segment in (
            ("主板A股", MarketSegment.SSE_MAIN),
            ("科创板", MarketSegment.STAR),
        ):
            frame = library.stock_info_sh_name_code(symbol=board)
            for row in frame.to_dict(orient="records"):
                records.append(
                    self._record(
                        symbol=str(row["证券代码"]).zfill(6),
                        name=str(row["证券简称"]),
                        exchange="SSE",
                        segment=segment,
                        listing_date=self._optional_date(row.get("上市日期")),
                        provider=f"akshare.stock_info_sh_name_code:{board}",
                        ingested=ingested,
                    )
                )

        frame = library.stock_info_sz_name_code(symbol="A股列表")
        for row in frame.to_dict(orient="records"):
            board = str(row["板块"]).strip()
            segment = (
                MarketSegment.CHINEXT if board == "创业板" else MarketSegment.SZSE_MAIN
            )
            records.append(
                self._record(
                    symbol=str(row["A股代码"]).zfill(6),
                    name=str(row["A股简称"]),
                    exchange="SZSE",
                    segment=segment,
                    listing_date=self._optional_date(row.get("A股上市日期")),
                    provider="akshare.stock_info_sz_name_code:A股列表",
                    ingested=ingested,
                )
            )
        return SecurityMasterBatch(
            market="A",
            snapshot_date=as_of_date,
            source=self.source,
            provider=self.provider,
            available_time=ingested,
            ingested_time=ingested,
            records=tuple(records),
            research_eligible=True,
            certification_basis="SSE/SZSE current official security-list endpoints",
        )

    @staticmethod
    def _record(
        *,
        symbol: str,
        name: str,
        exchange: str,
        segment: MarketSegment,
        listing_date: date | None,
        provider: str,
        ingested: datetime,
    ) -> SecurityMasterRecord:
        return SecurityMasterRecord(
            symbol=symbol,
            name=name,
            market="A",
            exchange=exchange,
            currency="CNY",
            timezone="Asia/Shanghai",
            listing_date=listing_date,
            delisting_date=None,
            security_type="stock",
            is_active=True,
            segment=segment,
            source="official_exchange_list",
            provider=provider,
            available_time=ingested,
            ingested_time=ingested,
        )

    @staticmethod
    def _optional_date(value: object) -> date | None:
        if value is None or str(value).strip() in {"", "NaT", "nan"}:
            return None
        parsed = datetime.fromisoformat(str(value).split(" ", maxsplit=1)[0])
        return parsed.date()

    @staticmethod
    def _load_library() -> ModuleType:
        return importlib.import_module("akshare")


class AKShareAETFSecurityMasterAdapter:
    """Current A-market ETF discovery feed; not an official historical master."""

    source = "eastmoney_current_etf_list"
    provider = "akshare.fund_etf_spot_em"

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch:
        if as_of_date != date.today():
            raise ValueError("current A ETF endpoint cannot reconstruct a historical snapshot")
        library = importlib.import_module("akshare")
        frame = library.fund_etf_spot_em()
        ingested = datetime.now(UTC)
        records: list[SecurityMasterRecord] = []
        available_times: list[datetime] = []
        for row in frame.to_dict(orient="records"):
            symbol = str(row["代码"]).split(".", maxsplit=1)[0].zfill(6)
            if symbol.startswith(("5", "6")):
                exchange = "SSE"
            elif symbol.startswith(("1", "2")):
                exchange = "SZSE"
            else:
                continue
            available = row.get("更新时间")
            if isinstance(available, datetime):
                available_time = normalize_utc(
                    available
                    if available.tzinfo is not None
                    else available.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
                )
            else:
                available_time = ingested
            if available_time.date() > as_of_date:
                raise ValueError("A ETF list contains future-dated provider rows")
            available_times.append(available_time)
            records.append(
                SecurityMasterRecord(
                    symbol=symbol,
                    name=str(row["名称"]).strip(),
                    market="A",
                    exchange=exchange,
                    currency="CNY",
                    timezone="Asia/Shanghai",
                    listing_date=None,
                    delisting_date=None,
                    security_type="etf",
                    is_active=True,
                    segment=MarketSegment.A_ETF,
                    source=self.source,
                    provider=self.provider,
                    available_time=available_time,
                    ingested_time=ingested,
                )
            )
        return SecurityMasterBatch(
            market="A",
            snapshot_date=as_of_date,
            source=self.source,
            provider=self.provider,
            available_time=max(available_times),
            ingested_time=ingested,
            records=tuple(records),
            research_eligible=False,
            certification_basis=(
                "Current Eastmoney ETF discovery feed lacks an immutable official "
                "point-in-time membership archive"
            ),
        )


class HKEXSecurityMasterAdapter:
    source = "hkex_full_list_of_securities"
    provider = "hkex.ListOfSecurities.xlsx"

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch:
        pandas = importlib.import_module("pandas")
        raw = pandas.read_excel(HKEX_FULL_LIST_URL, header=None)
        first_column = [str(value) for value in raw.iloc[:10, 0].tolist()]
        update_text = next(
            (value for value in first_column if "Updated as at" in value),
            "",
        )
        match = re.search(r"(\d{2}/\d{2}/\d{4})", update_text)
        if match is None:
            raise ValueError("HKEX full list does not expose a parseable update date")
        source_date = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        if source_date > as_of_date:
            raise ValueError(
                f"HKEX security list is future-dated ({source_date}) for {as_of_date}"
            )
        header_rows = [
            index
            for index, value in enumerate(first_column)
            if value.strip() == "Stock Code"
        ]
        if len(header_rows) != 1:
            raise ValueError("HKEX full list does not expose a unique header row")
        header_index = header_rows[0]
        frame = raw.iloc[header_index + 1 :].copy()
        frame.columns = raw.iloc[header_index].tolist()
        ingested = datetime.now(UTC)
        records: list[SecurityMasterRecord] = []
        for row in frame.to_dict(orient="records"):
            category = str(row.get("Category", "")).strip()
            subcategory = str(row.get("Sub-Category", "")).strip()
            is_main_board = category == "Equity" and "Main Board" in subcategory
            is_etf = (
                category == "Exchange Traded Products"
                and subcategory == "Exchange Traded Funds"
            )
            if not is_main_board and not is_etf:
                continue
            symbol = str(row["Stock Code"]).split(".", maxsplit=1)[0].zfill(5)
            records.append(
                SecurityMasterRecord(
                    symbol=symbol,
                    name=str(row["Name of Securities"]).strip(),
                    market="HK",
                    exchange="HKEX",
                    currency=str(row["Trading Currency"]).strip().upper(),
                    timezone="Asia/Hong_Kong",
                    listing_date=None,
                    delisting_date=None,
                    security_type="etf" if is_etf else "stock",
                    is_active=True,
                    segment=(MarketSegment.HK_ETF if is_etf else MarketSegment.HK_MAIN),
                    source=self.source,
                    provider=self.provider,
                    available_time=datetime.combine(source_date, datetime.min.time(), UTC),
                    ingested_time=ingested,
                )
            )
        return SecurityMasterBatch(
            market="HK",
            snapshot_date=as_of_date,
            source=self.source,
            provider=self.provider,
            available_time=datetime.combine(source_date, datetime.min.time(), UTC),
            ingested_time=ingested,
            records=tuple(records),
            research_eligible=True,
            certification_basis="HKEX Full List of Securities with embedded publication date",
        )


class AKShareHKSecurityMasterAdapter:
    """Current HK universe fallback with explicit non-exchange lineage."""

    source = "sina_hk_current_equity_list"
    provider = "akshare.stock_hk_spot"

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch:
        if as_of_date != date.today():
            raise ValueError("current HK endpoint cannot reconstruct a historical snapshot")
        library = importlib.import_module("akshare")
        frame = library.stock_hk_spot()
        ingested = datetime.now(UTC)
        records: list[SecurityMasterRecord] = []
        source_times: list[datetime] = []
        for row in frame.to_dict(orient="records"):
            source_time = datetime.strptime(
                str(row["日期时间"]),
                "%Y/%m/%d %H:%M:%S",
            ).replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
            source_time = normalize_utc(source_time)
            if source_time.date() > as_of_date:
                raise ValueError("HK current list contains future-dated provider rows")
            source_times.append(source_time)
            records.append(
                SecurityMasterRecord(
                    symbol=str(row["代码"]).zfill(5),
                    name=str(row["英文名称"] or row["中文名称"]).strip(),
                    market="HK",
                    exchange="HKEX",
                    currency="HKD",
                    timezone="Asia/Hong_Kong",
                    listing_date=None,
                    delisting_date=None,
                    security_type="stock",
                    is_active=True,
                    segment=MarketSegment.HK_MAIN,
                    source=self.source,
                    provider=self.provider,
                    available_time=source_time,
                    ingested_time=ingested,
                )
            )
        return SecurityMasterBatch(
            market="HK",
            snapshot_date=as_of_date,
            source=self.source,
            provider=self.provider,
            available_time=max(source_times),
            ingested_time=ingested,
            records=tuple(records),
            research_eligible=False,
            certification_basis=(
                "Current quote list lacks authoritative Main Board classification and "
                "historical-universe provenance"
            ),
        )


class NasdaqTraderSecurityMasterAdapter:
    source = "nasdaq_trader_symbol_directory"
    provider = "nasdaqtrader.symboldirectory"

    def fetch_current(self, *, as_of_date: date) -> SecurityMasterBatch:
        ingested = datetime.now(UTC)
        records: list[SecurityMasterRecord] = []
        for url, exchange in (
            (NASDAQ_LISTED_URL, "NASDAQ"),
            (NASDAQ_OTHER_LISTED_URL, "NYSE"),
        ):
            text, available = self._download(url)
            if available.date() > as_of_date:
                raise ValueError(
                    f"Nasdaq Trader directory is future-dated ({available.date()}) "
                    f"for {as_of_date}"
                )
            reader = csv.DictReader(io.StringIO(text), delimiter="|")
            for row in reader:
                symbol_key = "Symbol" if exchange == "NASDAQ" else "ACT Symbol"
                symbol = str(row.get(symbol_key, "")).strip().upper()
                if not symbol or symbol.startswith("File Creation Time"):
                    continue
                if str(row.get("Test Issue", "N")).strip() != "N":
                    continue
                is_etf = str(row.get("ETF", "N")).strip() == "Y"
                if exchange == "NYSE" and str(row.get("Exchange", "")).strip() != "N":
                    continue
                records.append(
                    SecurityMasterRecord(
                        symbol=symbol,
                        name=str(row.get("Security Name", symbol)).strip(),
                        market="US",
                        exchange=exchange,
                        currency="USD",
                        timezone="America/New_York",
                        listing_date=None,
                        delisting_date=None,
                        security_type="etf" if is_etf else "stock",
                        is_active=True,
                        segment=(
                            MarketSegment.US_ETF
                            if is_etf
                            else MarketSegment.NASDAQ
                            if exchange == "NASDAQ"
                            else MarketSegment.NYSE
                        ),
                        source=self.source,
                        provider=url,
                        available_time=available,
                        ingested_time=ingested,
                    )
                )
        return SecurityMasterBatch(
            market="US",
            snapshot_date=as_of_date,
            source=self.source,
            provider=self.provider,
            available_time=max(item.available_time for item in records),
            ingested_time=ingested,
            records=tuple(records),
            research_eligible=True,
            certification_basis="Nasdaq Trader Symbol Directory with file creation time",
        )

    @staticmethod
    def _download(url: str) -> tuple[str, datetime]:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            text = response.read().decode("utf-8")
        creation_line = next(
            (line for line in text.splitlines() if line.startswith("File Creation Time")),
            None,
        )
        if creation_line is None:
            raise ValueError(f"Nasdaq Trader file has no creation timestamp: {url}")
        value = creation_line.split("|", maxsplit=1)[0].split(": ", maxsplit=1)[1]
        local_time = datetime.strptime(value, "%m%d%Y%H:%M").replace(
            tzinfo=ZoneInfo("America/New_York")
        )
        return text, normalize_utc(local_time)


class ArchivedSecurityMasterCSVAdapter:
    """Load an immutable historical universe without backdating a current list."""

    REQUIRED_COLUMNS = {
        "snapshot_date",
        "symbol",
        "name",
        "market",
        "exchange",
        "currency",
        "timezone",
        "listing_date",
        "delisting_date",
        "security_type",
        "is_active",
        "segment",
        "source",
        "provider",
        "available_time",
    }

    def __init__(self, *, trusted_archive: bool = False) -> None:
        self._trusted_archive = trusted_archive

    def read(
        self,
        path: Path,
        *,
        expected_snapshot_date: date,
    ) -> SecurityMasterBatch:
        ingested = datetime.now(UTC)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = self.REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing:
                raise ValueError(
                    "archived security master is missing columns: "
                    + ", ".join(sorted(missing))
                )
            rows = list(reader)
        if not rows:
            raise ValueError("archived security master cannot be empty")
        snapshot_dates = {date.fromisoformat(row["snapshot_date"]) for row in rows}
        if snapshot_dates != {expected_snapshot_date}:
            raise ValueError(
                "archived security master does not match expected snapshot date"
            )
        markets = {row["market"].strip().upper() for row in rows}
        if len(markets) != 1 or next(iter(markets)) not in {"A", "HK", "US"}:
            raise ValueError("archived security master must contain exactly one market")
        sources = {row["source"].strip() for row in rows}
        providers = {row["provider"].strip() for row in rows}
        if "" in sources or "" in providers or len(sources) != 1 or len(providers) != 1:
            raise ValueError("archived security master requires one explicit lineage")
        records = tuple(self._record(row, ingested) for row in rows)
        available_time = max(item.available_time for item in records)
        if available_time > ingested:
            raise ValueError("archived security master is not available yet")
        market = next(iter(markets))
        return SecurityMasterBatch(
            market=market,  # type: ignore[arg-type]
            snapshot_date=expected_snapshot_date,
            source=next(iter(sources)),
            provider=next(iter(providers)),
            available_time=available_time,
            ingested_time=ingested,
            records=records,
            research_eligible=self._trusted_archive,
            certification_basis=(
                "Operator-verified immutable historical archive"
                if self._trusted_archive
                else "Archive provenance has not been independently verified"
            ),
        )

    @staticmethod
    def _record(row: dict[str, str], ingested: datetime) -> SecurityMasterRecord:
        def optional_date(value: str) -> date | None:
            return date.fromisoformat(value) if value.strip() else None

        active_value = row["is_active"].strip().lower()
        if active_value not in {"true", "false", "1", "0"}:
            raise ValueError("is_active must be true/false or 1/0")
        available_time = normalize_utc(datetime.fromisoformat(row["available_time"]))
        return SecurityMasterRecord(
            symbol=row["symbol"].strip(),
            name=row["name"].strip(),
            market=row["market"].strip().upper(),  # type: ignore[arg-type]
            exchange=row["exchange"].strip().upper(),
            currency=row["currency"].strip().upper(),
            timezone=row["timezone"].strip(),
            listing_date=optional_date(row["listing_date"]),
            delisting_date=optional_date(row["delisting_date"]),
            security_type=row["security_type"].strip().lower(),
            is_active=active_value in {"true", "1"},
            segment=MarketSegment(row["segment"].strip()),
            source=row["source"].strip(),
            provider=row["provider"].strip(),
            available_time=available_time,
            ingested_time=ingested,
        )
