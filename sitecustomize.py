"""Narrow runtime compatibility for immutable historical Alembic revisions.

Revision ``6e2a1c4d9b70`` used ``sqlalchemy.TypeEngine`` in a runtime-evaluated
annotation.  SQLAlchemy exposes that class from ``sqlalchemy.types`` instead.
The published revision must remain byte-for-byte immutable, so the compatibility
alias is installed before Alembic imports revision modules.
"""

from __future__ import annotations

import sqlalchemy as _sqlalchemy

if not hasattr(_sqlalchemy, "TypeEngine"):
    _sqlalchemy.TypeEngine = _sqlalchemy.types.TypeEngine  # type: ignore[attr-defined]
