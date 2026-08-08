from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_alpha_terminal.models.base import Base, TimestampMixin


class DailyPipelineRun(TimestampMixin, Base):
    """One auditable execution of the local daily research pipeline."""

    __tablename__ = "daily_pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name="valid_daily_pipeline_status",
        ),
        Index("ix_daily_pipeline_runs_date_started", "run_date", "start_time"),
        Index("ix_daily_pipeline_runs_status_started", "status", "start_time"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    data_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    tasks: Mapped[list["DailyTaskRun"]] = relationship(
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
        order_by="DailyTaskRun.sequence",
    )


class DailyTaskRun(Base):
    """Execution state for one isolated task within a daily pipeline run."""

    __tablename__ = "daily_task_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
            name="valid_daily_task_status",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_daily_task_attempts"),
        CheckConstraint("max_attempts >= 1", name="positive_daily_task_max_attempts"),
        UniqueConstraint(
            "pipeline_run_id",
            "task_name",
            name="uq_daily_task_runs_pipeline_task",
        ),
        Index("ix_daily_task_runs_status_started", "status", "start_time"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    pipeline_run_id: Mapped[int] = mapped_column(
        ForeignKey("daily_pipeline_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    pipeline_run: Mapped[DailyPipelineRun] = relationship(back_populates="tasks")
