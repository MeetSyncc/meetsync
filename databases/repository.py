"""Database operations for MeetSync.

Functions accept an open psycopg connection and leave transaction ownership to
the caller. Use ``with psycopg.connect(...) as conn`` to commit or roll back.
"""

from __future__ import annotations

import json
from datetime import datetime, time
from typing import Any

from psycopg import Connection, sql
from psycopg.rows import dict_row

# Marker meaning "argument not passed", so None can still be a real value
# (e.g. clearing start_datetime on a meeting).
_UNSET: Any = object()


def _update_row(
    conn: Connection, table: str, pk_column: str, pk_value: Any,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """UPDATE the given columns of one row; skips fields equal to _UNSET.

    Column names come from fixed lists inside this module, never from user input.
    """
    fields = {k: v for k, v in fields.items() if v is not _UNSET}
    if not fields:
        raise ValueError("Nothing to update")
    query = sql.SQL("UPDATE {table} SET {sets} WHERE {pk} = %s RETURNING *").format(
        table=sql.Identifier(table),
        sets=sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields
        ),
        pk=sql.Identifier(pk_column),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, [*fields.values(), pk_value])
        return cur.fetchone()


def create_user(
    conn: Connection,
    telegram_user_id: int,
    telegram_username: str | None = None,
    timezone: str = "Europe/Moscow",
    basic_privacy_type: str = "open",
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO users
                (telegram_user_id, telegram_username, timezone, basic_privacy_type)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (telegram_user_id, telegram_username, timezone, basic_privacy_type),
        )
        return cur.fetchone()


def get_user(
    conn: Connection, user_id: int | None = None, telegram_user_id: int | None = None
) -> dict[str, Any] | None:
    if (user_id is None) == (telegram_user_id is None):
        raise ValueError("Provide exactly one of user_id or telegram_user_id")
    with conn.cursor(row_factory=dict_row) as cur:
        if user_id is not None:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        else:
            cur.execute(
                "SELECT * FROM users WHERE telegram_user_id = %s",
                (telegram_user_id,),
            )
        return cur.fetchone()


def create_group(
    conn: Connection, telegram_chat_id: int, group_name: str | None = None
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO groups (telegram_chat_id, group_name)
            VALUES (%s, %s)
            RETURNING *
            """,
            (telegram_chat_id, group_name),
        )
        return cur.fetchone()


def get_group(
    conn: Connection, group_id: int | None = None, telegram_chat_id: int | None = None
) -> dict[str, Any] | None:
    if (group_id is None) == (telegram_chat_id is None):
        raise ValueError("Provide exactly one of group_id or telegram_chat_id")
    with conn.cursor(row_factory=dict_row) as cur:
        if group_id is not None:
            cur.execute("SELECT * FROM groups WHERE group_id = %s", (group_id,))
        else:
            cur.execute(
                "SELECT * FROM groups WHERE telegram_chat_id = %s",
                (telegram_chat_id,),
            )
        return cur.fetchone()


def add_group_member(
    conn: Connection, group_id: int, user_id: int, status: str = "active",
    joined_at: datetime | None = None,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO group_memberships (group_id, user_id, status, joined_at)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (group_id, user_id, status, joined_at),
        )
        return cur.fetchone()


def get_group_members(
    conn: Connection, group_id: int, status: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM group_memberships WHERE group_id = %s"
    params: list[Any] = [group_id]
    if status is not None:
        query += " AND status = %s"
        params.append(status)
    query += " ORDER BY user_id"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def create_interval(
    conn: Connection, user_id: int, day: int, start_time: time, end_time: time,
    group_id: int | None = None,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO intervals (user_id, group_id, day, start_time, end_time)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, group_id, day, start_time, end_time),
        )
        return cur.fetchone()


def get_intervals(
    conn: Connection, user_id: int, group_id: int | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM intervals WHERE user_id = %s"
    params: list[Any] = [user_id]
    if group_id is None:
        query += " AND group_id IS NULL"
    else:
        query += " AND group_id = %s"
        params.append(group_id)
    query += " ORDER BY day, start_time"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def create_availability_exception(
    conn: Connection, user_id: int, is_free: bool,
    start_datetime: datetime, end_datetime: datetime,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO availability_exceptions
                (user_id, is_free, start_datetime, end_datetime)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, is_free, start_datetime, end_datetime),
        )
        return cur.fetchone()


def get_availability_exceptions(
    conn: Connection, user_id: int, from_datetime: datetime | None = None,
    to_datetime: datetime | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM availability_exceptions WHERE user_id = %s"
    params: list[Any] = [user_id]
    if from_datetime is not None:
        query += " AND end_datetime > %s"
        params.append(from_datetime)
    if to_datetime is not None:
        query += " AND start_datetime < %s"
        params.append(to_datetime)
    query += " ORDER BY start_datetime"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def create_meeting(
    conn: Connection, created_by: int, duration_minutes: int,
    group_id: int | None = None, status: str = "draft",
    start_datetime: datetime | None = None,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO meetings
                (created_by, group_id, status, start_datetime, duration_minutes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (created_by, group_id, status, start_datetime, duration_minutes),
        )
        return cur.fetchone()


def get_meeting(conn: Connection, meeting_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM meetings WHERE meeting_id = %s", (meeting_id,))
        return cur.fetchone()


def add_meeting_participant(
    conn: Connection, meeting_id: int, user_id: int,
    status: str = "invited", is_required: bool = True,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO meeting_participants
                (meeting_id, user_id, status, is_required)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (meeting_id, user_id, status, is_required),
        )
        return cur.fetchone()


def get_meeting_participants(
    conn: Connection, meeting_id: int
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT mp.*, u.telegram_user_id, u.telegram_username
            FROM meeting_participants mp
            JOIN users u USING (user_id)
            WHERE mp.meeting_id = %s
            ORDER BY mp.user_id
            """,
            (meeting_id,),
        )
        return cur.fetchall()


def create_llm_parse_log(
    conn: Connection, input_text: str, parsed_result: dict[str, Any],
    user_timezone: str, model_name: str, status: str,
    user_id: int | None = None, error_message: str | None = None,
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO llm_parse_logs
                (user_id, input_text, parsed_result, user_timezone, model_name,
                 status, error_message)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, input_text, json.dumps(parsed_result), user_timezone,
             model_name, status, error_message),
        )
        return cur.fetchone()


def update_llm_parse_log_rating(
    conn: Connection, log_id: int, is_correct: bool | None
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE llm_parse_logs
            SET is_correct = %s
            WHERE id = %s
            RETURNING *
            """,
            (is_correct, log_id),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# Update / delete functions
# --------------------------------------------------------------------------

def update_user(
    conn: Connection, user_id: int, telegram_username: Any = _UNSET,
    timezone: Any = _UNSET, basic_privacy_type: Any = _UNSET,
) -> dict[str, Any] | None:
    return _update_row(conn, "users", "user_id", user_id, {
        "telegram_username": telegram_username,
        "timezone": timezone,
        "basic_privacy_type": basic_privacy_type,
    })


def update_group_member_status(
    conn: Connection, group_id: int, user_id: int, status: str
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE group_memberships SET status = %s
            WHERE group_id = %s AND user_id = %s
            RETURNING *
            """,
            (status, group_id, user_id),
        )
        return cur.fetchone()


def update_interval(
    conn: Connection, interval_id: int, day: Any = _UNSET,
    start_time: Any = _UNSET, end_time: Any = _UNSET,
) -> dict[str, Any] | None:
    return _update_row(conn, "intervals", "interval_id", interval_id, {
        "day": day, "start_time": start_time, "end_time": end_time,
    })


def delete_interval(conn: Connection, interval_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM intervals WHERE interval_id = %s", (interval_id,))
        return cur.rowcount > 0


def update_availability_exception(
    conn: Connection, exception_id: int, is_free: Any = _UNSET,
    start_datetime: Any = _UNSET, end_datetime: Any = _UNSET,
) -> dict[str, Any] | None:
    return _update_row(
        conn, "availability_exceptions", "exception_id", exception_id,
        {"is_free": is_free, "start_datetime": start_datetime,
         "end_datetime": end_datetime},
    )


def delete_availability_exception(conn: Connection, exception_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM availability_exceptions WHERE exception_id = %s",
            (exception_id,),
        )
        return cur.rowcount > 0


def update_meeting(
    conn: Connection, meeting_id: int, status: Any = _UNSET,
    start_datetime: Any = _UNSET, duration_minutes: Any = _UNSET,
) -> dict[str, Any] | None:
    """Change status / time / duration. To confirm, pass both
    status="confirmed" and start_datetime (the DB requires a start time)."""
    return _update_row(conn, "meetings", "meeting_id", meeting_id, {
        "status": status, "start_datetime": start_datetime,
        "duration_minutes": duration_minutes,
    })


def update_meeting_participant(
    conn: Connection, meeting_id: int, user_id: int,
    status: Any = _UNSET, is_required: Any = _UNSET,
) -> dict[str, Any] | None:
    fields = {"status": status, "is_required": is_required}
    fields = {k: v for k, v in fields.items() if v is not _UNSET}
    if not fields:
        raise ValueError("Nothing to update")
    query = sql.SQL(
        "UPDATE meeting_participants SET {sets} "
        "WHERE meeting_id = %s AND user_id = %s RETURNING *"
    ).format(sets=sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(k)) for k in fields
    ))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, [*fields.values(), meeting_id, user_id])
        return cur.fetchone()


def remove_meeting_participant(
    conn: Connection, meeting_id: int, user_id: int
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM meeting_participants WHERE meeting_id = %s AND user_id = %s",
            (meeting_id, user_id),
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------------
# user_relations (friend / blocked) - used for access-control checks
# --------------------------------------------------------------------------

def set_relation(
    conn: Connection, user_id: int, target_id: int, relation_type: str
) -> dict[str, Any]:
    """Create the link user_id -> target_id, or change its type if it exists."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO user_relations (user_id, target_id, relation_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, target_id)
            DO UPDATE SET relation_type = EXCLUDED.relation_type
            RETURNING *
            """,
            (user_id, target_id, relation_type),
        )
        return cur.fetchone()


def get_relation(
    conn: Connection, user_id: int, target_id: int
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM user_relations WHERE user_id = %s AND target_id = %s",
            (user_id, target_id),
        )
        return cur.fetchone()


def get_relations(
    conn: Connection, user_id: int, relation_type: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM user_relations WHERE user_id = %s"
    params: list[Any] = [user_id]
    if relation_type is not None:
        query += " AND relation_type = %s"
        params.append(relation_type)
    query += " ORDER BY target_id"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def delete_relation(conn: Connection, user_id: int, target_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM user_relations WHERE user_id = %s AND target_id = %s",
            (user_id, target_id),
        )
        return cur.rowcount > 0
