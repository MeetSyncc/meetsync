"""Database connection helper for MeetSync.

The connection string is read from the DATABASE_URL environment variable, so
passwords never live in the code. Example:

    DATABASE_URL=postgresql://postgres:mypassword@localhost:5432/meetsync

Usage (commits on success, rolls back on error, closes at the end):

    from db import get_connection
    import repository

    with get_connection() as conn:
        user = repository.create_user(conn, telegram_user_id=12345)
"""

from __future__ import annotations

import os
import psycopg


def get_connection() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Example: "
            "postgresql://postgres:password@localhost:5432/meetsync"
        )
    return psycopg.connect(url)
