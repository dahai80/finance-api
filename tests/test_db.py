import pytest
import pytest_asyncio
import asyncpg

from config import settings


@pytest_asyncio.fixture
async def pg():
    pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_pg_schema_exists(pg):
    async with pg.acquire() as conn:
        rows = await conn.fetch(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'finance_control'"
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_ipo_table_exists(pg):
    async with pg.acquire() as conn:
        rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'finance_control' AND table_name = 'fc_ipo_factory'"
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_workflow_seed(pg):
    async with pg.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT task_id FROM finance_control.fc_workflow_config WHERE task_id = 'ipo_sync_daily'"
        )
        assert row is not None
        assert row["task_id"] == "ipo_sync_daily"
