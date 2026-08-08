from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin


class MarketGraphRun(TimestampMixin, Base):
    """A persisted market-network snapshot for one historical interval."""

    __tablename__ = "market_graph_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="valid_market_graph_status",
        ),
        Index("ix_market_graph_runs_end_created", "end_date", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    nodes: Mapped[list["MarketGraphNode"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    edges: Mapped[list["MarketGraphEdge"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    paths: Mapped[list["MarketGraphPath"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class MarketGraphNode(Base):
    """Node metadata, layout position, and graph metrics at snapshot time."""

    __tablename__ = "market_graph_nodes"
    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('stock', 'etf', 'index', 'commodity')",
            name="valid_market_graph_asset_type",
        ),
        UniqueConstraint("run_id", "stock_id", name="uq_market_graph_nodes_run_stock"),
        Index("ix_market_graph_nodes_run_core", "run_id", "core_score"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("market_graph_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(96), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    degree_centrality: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    betweenness_centrality: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    influence: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    association_strength: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    core_score: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    position_x: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    position_y: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)

    run: Mapped[MarketGraphRun] = relationship(back_populates="nodes")


class MarketGraphEdge(Base):
    """A contemporaneous or directed statistical relationship."""

    __tablename__ = "market_graph_edges"
    __table_args__ = (
        CheckConstraint(
            "relationship_type IN ('correlation', 'lead_lag', 'capital_transmission')",
            name="valid_market_graph_relationship",
        ),
        CheckConstraint("weight >= -1 AND weight <= 1", name="valid_graph_weight"),
        CheckConstraint(
            "strength >= 0 AND strength <= 1",
            name="valid_graph_strength",
        ),
        CheckConstraint("lag_days >= 0", name="nonnegative_graph_lag"),
        CheckConstraint("sample_size >= 2", name="valid_graph_sample_size"),
        UniqueConstraint(
            "run_id",
            "source_stock_id",
            "target_stock_id",
            "relationship_type",
            name="uq_market_graph_edges_run_pair_type",
        ),
        Index(
            "ix_market_graph_edges_run_type_strength",
            "run_id",
            "relationship_type",
            "strength",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("market_graph_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    target_stock_id: Mapped[int] = mapped_column(
        ForeignKey("security_master.id"), index=True, nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    strength: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    lag_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    p_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    fdr_q_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 10), nullable=True)
    bonferroni_p_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 10), nullable=True
    )
    significant_fdr: Mapped[bool] = mapped_column(default=False, nullable=False)
    significant_bonferroni: Mapped[bool] = mapped_column(default=False, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    run: Mapped[MarketGraphRun] = relationship(back_populates="edges")


class MarketGraphPath(Base):
    """A ranked three-node statistical transmission chain."""

    __tablename__ = "market_graph_paths"
    __table_args__ = (
        CheckConstraint("path_rank > 0", name="positive_graph_path_rank"),
        CheckConstraint(
            "aggregate_strength >= 0 AND aggregate_strength <= 1",
            name="valid_path_strength",
        ),
        UniqueConstraint("run_id", "path_rank", name="uq_market_graph_paths_run_rank"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("market_graph_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    path_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    node_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    node_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    relationship_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    aggregate_strength: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    total_lag_days: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[MarketGraphRun] = relationship(back_populates="paths")
