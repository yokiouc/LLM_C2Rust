"""Database connection management."""

from contextlib import contextmanager

import psycopg

from .config import get_database_url


@contextmanager
def connect(*, timeout_seconds: int = 5):
    """Open a psycopg connection using the configured database URL."""
    dsn = get_database_url()
    with psycopg.connect(dsn, connect_timeout=timeout_seconds) as conn:
        yield conn
