import os
import sys
from pathlib import Path

import pytest
import psycopg

_repo_root = Path(__file__).resolve().parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))


@pytest.fixture(scope="session")
def database_url() -> str:
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.skip("DATABASE_URL not set; skipping db integration tests")
    return dsn


@pytest.fixture(autouse=True)
def clean_db():
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        yield
        return
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE agent_runs CASCADE;")
                cur.execute("TRUNCATE TABLE projects RESTART IDENTITY CASCADE;")
    yield


def pytest_collection_modifyitems(config, items):
    if os.getenv("POSTGRES_DSN", "") or os.getenv("DATABASE_URL", "") or os.getenv("POSTGRES_HOST", ""):
        return
    for item in items:
        if getattr(item, "fspath", None) and item.fspath.basename in {"test_api_chunks.py"}:
            item.add_marker(pytest.mark.skip(reason="DATABASE_URL not set; skipping db integration tests"))
