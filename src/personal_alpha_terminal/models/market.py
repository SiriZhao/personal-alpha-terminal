from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from personal_alpha_terminal.models.factor import FinancialPerShareMetric
    from personal_alpha_terminal.models.portfolio import PortfolioPosition
    from personal_alpha_terminal.models.research import Event, Signal


class Industry(TimestampMixin, Base):
    __tablename__ = "industries"
    __table_args__ = (UniqueConstraint("taxonomy", "code", name="uq_industries_taxonomy_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taxonomy: Mapped[str] = mapped_column(String(32), default="CUSTOM", nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("industries.id"), index=True, nullable=True
    )

    stocks: Mapped[list["Stock"]] = relationship(back_populates="industry")
    parent: Mapped["Industry | None"] = relationship(remote_side=[id])


class Stock(TimestampMixin, Base):
    __tablename__ = "security_master"
    __table_args__ = (
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_market"),
        CheckConstraint(
            "security_type IN ('stock', 'etf', 'index', 'commodity', 'bond', "
            "'money_fund', 'gold')",
            name="valid_asset_type",
        ),
        UniqueConstraint("exchange", "symbol", name="uq_stocks_exchange_symbol"),
        Index("ix_stocks_market_status", "market", "is_active"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="valid_security_currency",
        ),
        CheckConstraint(
            "listing_date IS NULL OR delisting_date IS NULL "
            "OR listing_date <= delisting_date",
            name="valid_security_lifecycle",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        "security_type",
        String(16),
        default="stock",
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    list_date: Mapped[date | None] = mapped_column("listing_date", Date, nullable=True)
    delist_date: Mapped[date | None] = mapped_column("delisting_date", Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="legacy_unknown",
    )
    provider: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="legacy_unknown",
    )
    available_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    ingested_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    industry_id: Mapped[int | None] = mapped_column(
        ForeignKey("industries.id"),
        nullable=True,
        index=True,
    )

    industry: Mapped[Industry | None] = relationship(back_populates="stocks")
    prices: Mapped[list["Price"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
    )
    financials: Mapped[list["Financial"]] = relationship(
        back_populates="stock",
        cascade="all, delete-orphan",
    )
    events: Mapped[list["Event"]] = relationship(back_populates="stock")
    signals: Mapped[list["Signal"]] = relationship(back_populates="stock")
    positions: Mapped[list["PortfolioPosition"]] = relationship(back_populates="stock")

    @property
    def security_type(self) -> str:
        return self.asset_type

    @property
    def listing_date(self) -> date | None:
        return self.list_date

    @property
    def delisting_date(self) -> date | None:
        return self.delist_date


SecurityMaster = Stock


class ProviderCapabilityRecord(TimestampMixin, Base):
    __tablename__ = "provider_capabilities"
    __table_args__ = (
        CheckConstraint("market IN ('A', 'HK', 'US')", name="valid_capability_market"),
        CheckConstraint(
            "asset_type IN ('stock', 'etf', 'index', 'bond')",
            name="valid_capability_asset_type",
        ),
        CheckConstraint(
            "raw_volume_unit IN ('share', 'hand', 'face_value', 'none', 'unknown')",
            name="valid_raw_volume_unit",
        ),
        CheckConstraint(
            "volume_unit IN ('share', 'face_value', 'none')",
            name="valid_normalized_volume_unit",
        ),
        CheckConstraint(
            "price_type IN ('unadjusted_ohlcv', 'index_level_ohlcv', "
            "'clean_price_ohlcv')",
            name="valid_capability_price_type",
        ),
        CheckConstraint("volume_multiplier > 0", name="positive_volume_multiplier"),
        CheckConstraint("raw_share_unit > 0", name="positive_raw_share_unit"),
        UniqueConstraint(
            "provider",
            "market",
            "asset_type",
            name="uq_provider_capabilities_provider_market_asset",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_volume_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    volume_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    price_type: Mapped[str] = mapped_column(String(32), nullable=False)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    volume_multiplier: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    raw_share_unit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint("high >= low", name="high_not_below_low"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="nonnegative_volume"),
        CheckConstraint(
            "asset_type IN ('stock', 'etf', 'index', 'bond')",
            name="valid_price_asset_type",
        ),
        CheckConstraint(
            "volume_unit IN ('share', 'face_value', 'none')",
            name="valid_price_volume_unit",
        ),
        CheckConstraint("share_unit = 1", name="normalized_share_unit"),
        CheckConstraint(
            "length(price_currency) = 3 AND price_currency = upper(price_currency)",
            name="valid_price_currency",
        ),
        CheckConstraint(
            "price_type IN ('unadjusted_ohlcv', 'index_level_ohlcv', "
            "'clean_price_ohlcv')",
            name="valid_price_type",
        ),
        CheckConstraint(
            "data_contract_version = 'market-data-v1'",
            name="valid_data_contract_version",
        ),
        CheckConstraint(
            "(asset_type IN ('stock', 'etf') AND volume_unit = 'share') OR "
            "(asset_type = 'bond' AND volume_unit = 'face_value') OR "
            "(asset_type = 'index' AND volume_unit IN ('share', 'none'))",
            name="asset_volume_unit_match",
        ),
        CheckConstraint(
            "(volume_unit = 'none' AND volume IS NULL) OR volume_unit <> 'none'",
            name="volume_matches_unit",
        ),
        UniqueConstraint(
            "stock_id",
            "trade_date",
            "source",
            name="uq_prices_stock_date_source",
        ),
        Index("ix_prices_stock_date", "stock_id", "trade_date"),
        Index("ix_prices_available_time", "stock_id", "available_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    forward_adjusted_close: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6),
        nullable=True,
    )
    backward_adjusted_close: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6),
        nullable=True,
    )
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False, default="stock")
    volume_unit: Mapped[str] = mapped_column(String(16), nullable=False, default="share")
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    share_unit: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("1")
    )
    price_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unadjusted_ohlcv"
    )
    data_contract_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="market-data-v1"
    )
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="legacy_unknown",
    )
    adjustment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    available_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    open_tradable: Mapped[bool | None] = mapped_column(nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    stock: Mapped[Stock] = relationship(back_populates="prices")


class Financial(Base):
    __tablename__ = "financials"
    __table_args__ = (
        CheckConstraint(
            "period_type IN ('annual', 'quarterly', 'ttm')",
            name="valid_period_type",
        ),
        UniqueConstraint(
            "stock_id",
            "period_end",
            "period_type",
            "source",
            name="uq_financials_stock_period_source",
        ),
        Index("ix_financials_stock_available", "stock_id", "available_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    free_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    roe: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    roic: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    debt_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    pe: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    pb: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    ps: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    peg: Mapped[Decimal | None] = mapped_column(Numeric(16, 6), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    stock: Mapped[Stock] = relationship(back_populates="financials")
    per_share_metric: Mapped["FinancialPerShareMetric | None"] = relationship(
        back_populates="financial",
        cascade="all, delete-orphan",
        uselist=False,
    )
