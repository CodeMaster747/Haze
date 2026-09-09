"""Database engine and session handling."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from haze import config, log
from haze.db.models import SCHEMA_VERSION, Base, Meta

_log = log.get("db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def db_path() -> Path:
    return config.state_dir() / "haze.db"


async def init() -> None:
    """Create the engine and the schema. Idempotent."""
    global _engine, _sessionmaker
    if _engine is not None:
        return

    config.ensure_state_dir()
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path()}", future=True)

    async with _engine.begin() as conn:
        # WAL: the CLI reads the peer list while the agent holds the database
        # open. Without it, `haze peers` would block behind the agent's writes.
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
        await _check_table_shapes(conn)

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)

    async with session() as s:
        existing = await s.scalar(select(Meta).where(Meta.key == "schema_version"))
        if existing is None:
            s.add(Meta(key="schema_version", value=str(SCHEMA_VERSION)))
            await s.commit()
        elif int(existing.value) != SCHEMA_VERSION:
            # No migrations in v1 by design (see models.py). Fail loudly with
            # the remedy rather than running against a schema we do not
            # understand.
            raise RuntimeError(
                f"{db_path()} was written by schema v{existing.value}, this agent speaks "
                f"v{SCHEMA_VERSION}. Delete the file and re-pair your peers."
            )


async def _check_table_shapes(conn: AsyncConnection) -> None:
    """Verify each table has the columns this agent expects.

    `create_all` checks a table's *name*, not its shape: a table left behind by
    an older build is silently skipped, and the mismatch surfaces much later as
    `no such column` from whichever query happened to touch it first. Since
    adding a table deliberately does not bump SCHEMA_VERSION (see models.py),
    this is the only thing standing between that case and a confusing crash.
    """
    for table in Base.metadata.sorted_tables:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table.name})")
        found = {row[1] for row in result}
        if not found:  # pragma: no cover - create_all just made it
            continue
        missing = {c.name for c in table.columns} - found
        if missing:
            raise RuntimeError(
                f"{db_path()} has a '{table.name}' table without "
                f"{', '.join(sorted(missing))}. It was written by a different build of "
                f"Haze. Delete the file and re-pair your peers."
            )


async def close() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("database not initialised; call haze.db.session.init() first")
    async with _sessionmaker() as s:
        yield s
