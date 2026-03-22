import os
from contextlib import contextmanager

import psycopg


def get_database_url() -> str:
    dsn = os.getenv("POSTGRES_DSN", "")
    if dsn:
        return dsn

    dsn = os.getenv("DATABASE_URL", "")
    if dsn:
        return dsn

    host = os.getenv("POSTGRES_HOST", "")
    if not host:
        raise RuntimeError("DATABASE_URL is not set")

    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "root")
    password = os.getenv("POSTGRES_PASSWORD", "root")
    db = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@contextmanager
def connect(*, timeout_seconds: int = 5):
    dsn = get_database_url()
    with psycopg.connect(dsn, connect_timeout=timeout_seconds) as conn:
        yield conn
