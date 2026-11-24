from __future__ import annotations
import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional
from datetime import time
import psycopg
from psycopg.rows import dict_row
from config import DATABASE_URL

logger = logging.getLogger(__name__)


DAY_MAP = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 7,

    "понедельник": 1,
    "вторник": 2,
    "среда": 3,
    "четверг": 4,
    "пятница": 5,
    "суббота": 6,
    "воскресенье": 7,

    "пн": 1,
    "вт": 2,
    "ср": 3,
    "чт": 4,
    "пт": 5,
    "сб": 6,
    "вс": 7,
}

DAY_NAMES = {value: key for key, value in DAY_MAP.items() if len(key) > 2}


def normalize_day(value) -> Optional[int]:
    if isinstance(value, int):
        return value if 1 <= value <= 7 else None

    normalized = str(value).strip().lower()

    if normalized.isdigit():
        number = int(normalized)
        return number if 1 <= number <= 7 else None

    return DAY_MAP.get(normalized)


def normalize_time(value) -> Optional[time]:
    if isinstance(value, time):
        return value

    if not value:
        return None

    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Транзакция: commit при успехе, rollback при ошибке."""
    conn = psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )

    try:
        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def _ensure_user(
    conn: psycopg.Connection,
    telegram_user_id: int,
    username: Optional[str],
    timezone: str,
) -> int:
    row = conn.execute(
        """
        INSERT INTO users (
            telegram_user_id,
            telegram_username,
            timezone
        )
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_user_id)
        DO UPDATE SET
            telegram_username = COALESCE(
                EXCLUDED.telegram_username,
                users.telegram_username
            ),
            timezone = COALESCE(
                EXCLUDED.timezone,
                users.timezone
            )
        RETURNING user_id
        """,
        (telegram_user_id, username, timezone),
    ).fetchone()

    return row["user_id"]


def ensure_user(
    telegram_user_id: int,
    username: Optional[str] = None,
    timezone: str = "Europe/Moscow",
) -> int:
    """Создаёт или обновляет пользователя. Возвращает user_id."""
    with get_connection() as conn:
        return _ensure_user(
            conn,
            telegram_user_id,
            username,
            timezone,
        )


def save_availability(
    telegram_user_id: int,
    username: Optional[str],
    recurring_slots: list[dict],
    timezone: str = "Europe/Moscow",
) -> int:
    """
    Сохраняет регулярную доступность пользователя.

    Старые глобальные интервалы заменяются новыми.
    Создание пользователя и обновление интервалов
    выполняются в одной транзакции.
    """

    normalized_slots = []

    for slot in recurring_slots:
        if not isinstance(slot, dict):
            continue

        days = slot.get("days") or []
        time_info = slot.get("time") or {}

        if isinstance(days, str):
            days = [days]

        if not isinstance(days, list):
            continue

        start = normalize_time(time_info.get("start_time"))
        end = normalize_time(time_info.get("end_time"))

        if not start or not end:
            continue

        # Интервал должен завершаться позже в тот же день.
        if end <= start:
            continue

        for day in days:
            day_num = normalize_day(day)

            if day_num is None:
                continue

            normalized_slots.append(
                (day_num, start, end)
            )

    if not normalized_slots:
        raise ValueError(
            "Не удалось получить корректные регулярные интервалы. "
            "Проверь формат дней и времени из результата LLM."
        )

    with get_connection() as conn:
        user_id = _ensure_user(
            conn,
            telegram_user_id,
            username,
            timezone,
        )

        conn.execute(
            """
            DELETE FROM intervals
            WHERE user_id = %s
              AND group_id IS NULL
            """,
            (user_id,),
        )

        for day_num, start, end in normalized_slots:
            conn.execute(
                """
                INSERT INTO intervals (
                    user_id,
                    group_id,
                    day,
                    start_time,
                    end_time
                )
                VALUES (%s, NULL, %s, %s, %s)
                """,
                (user_id, day_num, start, end),
            )

    logger.info(
        "Availability saved: telegram_user_id=%s, intervals=%d",
        telegram_user_id,
        len(normalized_slots),
    )

    return user_id


def get_user_intervals(
    telegram_user_id: int,
) -> list[dict[str, Any]]:
    """Возвращает текущие глобальные интервалы пользователя."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                i.day,
                i.start_time::text AS start_time,
                i.end_time::text AS end_time
            FROM intervals i
            JOIN users u ON u.user_id = i.user_id
            WHERE u.telegram_user_id = %s
              AND i.group_id IS NULL
            ORDER BY i.day, i.start_time
            """,
            (telegram_user_id,),
        ).fetchall()

        return list(rows)


def get_intervals_by_usernames(
    usernames: list[str],
) -> dict[str, list[dict]]:
    """
    Возвращает интервалы пользователей:

    {
        "username": [
            {
                "day": 1,
                "start_time": "18:00:00",
                "end_time": "21:00:00"
            }
        ]
    }
    """

    if not usernames:
        return {}

    clean = list({
        username.lstrip("@").strip().lower()
        for username in usernames
        if username.strip()
    })

    if not clean:
        return {}

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                lower(u.telegram_username) AS username,
                i.day,
                i.start_time::text AS start_time,
                i.end_time::text AS end_time
            FROM intervals i
            JOIN users u ON u.user_id = i.user_id
            WHERE lower(u.telegram_username) = ANY(%s)
              AND i.group_id IS NULL
            ORDER BY
                u.telegram_username,
                i.day,
                i.start_time
            """,
            (clean,),
        ).fetchall()

    result = {username: [] for username in clean}

    for row in rows:
        username = row["username"]

        if username in result:
            result[username].append({
                "day": row["day"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
            })

    return result


def healthcheck() -> bool:
    """Проверяет доступность PostgreSQL."""

    try:
        with get_connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:
        logger.error("DB healthcheck failed: %s", exc)
        return False


def create_meeting(
    creator_telegram_id: int,
    creator_username: str | None,
    participants: list[str],
    start_datetime,
    duration: int,
) -> dict:
    """
    Создаёт встречу и добавляет её участников.
    Возвращает ID встречи и список приглашённых пользователей.
    """

    usernames = list({
        name.lstrip("@").strip().lower()
        for name in participants
        if name.strip()
    })

    if not usernames:
        raise ValueError("Список участников пуст.")

    with get_connection() as conn:
        creator_id = _ensure_user(
            conn,
            creator_telegram_id,
            creator_username,
            "Europe/Moscow",
        )

        creator = conn.execute(
            """
            SELECT timezone
            FROM users
            WHERE user_id = %s
            """,
            (creator_id,),
        ).fetchone()

        from zoneinfo import ZoneInfo
        if start_datetime.tzinfo is None:
            start_datetime = start_datetime.replace(
                tzinfo=ZoneInfo(creator["timezone"])
            )

        rows = conn.execute(
            """
            SELECT user_id, telegram_user_id, telegram_username
            FROM users
            WHERE LOWER(telegram_username) = ANY(%s)
            """,
            (usernames,),
        ).fetchall()
        found = {
            row["telegram_username"].lower(): row
            for row in rows
            if row["telegram_username"]
        }
        if len(found) != len(usernames):
            missing = set(usernames) - set(found)
            raise ValueError(
                "Не зарегистрированы в боте: "
                + ", ".join("@" + name for name in missing)
            )

        # Создаём встречу.
        meeting = conn.execute(
            """
            INSERT INTO meetings (
                created_by,
                status,
                start_datetime,
                duration_minutes
            )
            VALUES (%s, 'proposed', %s, %s)
            RETURNING meeting_id
            """,
            (creator_id, start_datetime, duration),
        ).fetchone()

        meeting_id = meeting["meeting_id"]

        # Организатор автоматически подтверждает участие.
        conn.execute(
            """
            INSERT INTO meeting_participants (
                meeting_id,
                user_id,
                status
            )
            VALUES (%s, %s, 'accepted')
            """,
            (meeting_id, creator_id),
        )

        # Добавляем остальных участников.
        invitees = []

        for user in found.values():
            if user["user_id"] == creator_id:
                continue

            conn.execute(
                """
                INSERT INTO meeting_participants (
                    meeting_id,
                    user_id,
                    status
                )
                VALUES (%s, %s, 'invited')
                ON CONFLICT (meeting_id, user_id) DO NOTHING
                """,
                (meeting_id, user["user_id"]),
            )

            invitees.append(user)

        return {
            "meeting_id": meeting_id,
            "invitees": invitees,
            "creator_telegram_id": creator_telegram_id,
        }


def respond_to_meeting_invitation(
    meeting_id: int,
    telegram_user_id: int,
    response: str,
) -> dict | None:
    """
    Сохраняет ответ участника.
    response: accepted или declined.
    """

    if response not in ("accepted", "declined"):
        raise ValueError("Некорректный ответ.")

    with get_connection() as conn:
        result = conn.execute(
            """
            UPDATE meeting_participants mp
            SET status = %s
            FROM users u
            WHERE mp.user_id = u.user_id
              AND mp.meeting_id = %s
              AND u.telegram_user_id = %s
              AND mp.status = 'invited'
            RETURNING mp.meeting_id
            """,
            (response, meeting_id, telegram_user_id),
        ).fetchone()

        if not result:
            return None

        meeting = conn.execute(
            """
            SELECT
                m.meeting_id,
                m.status,
                m.created_by,
                u.telegram_user_id AS creator_telegram_id
            FROM meetings m
            JOIN users u ON u.user_id = m.created_by
            WHERE m.meeting_id = %s
            """,
            (meeting_id,),
        ).fetchone()

        if not meeting:
            return None

        if response == "accepted":
            remaining = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM meeting_participants
                WHERE meeting_id = %s
                  AND is_required = TRUE
                  AND status <> 'accepted'
                """,
                (meeting_id,),
            ).fetchone()

            if remaining["count"] == 0:
                conn.execute(
                    """
                    UPDATE meetings
                    SET status = 'confirmed'
                    WHERE meeting_id = %s
                      AND status = 'proposed'
                    """,
                    (meeting_id,),
                )
                meeting["status"] = "confirmed"

        return {
            "meeting_id": meeting_id,
            "response": response,
            "creator_telegram_id": meeting["creator_telegram_id"],
            "status": meeting["status"],
        }