from datetime import date

from sqlalchemy import JSON, BigInteger, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from personal_alpha_terminal.models.base import Base, TimestampMixin


class ResearchReport(TimestampMixin, Base):
    __tablename__ = "research_reports"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    subject_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    data_sources: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    methodology: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    risk_factors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    generated_by: Mapped[str] = mapped_column(
        String(32),
        default="deterministic",
        nullable=False,
    )
