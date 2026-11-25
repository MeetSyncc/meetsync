from __future__ import annotations
import logging
from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Any, Generator, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
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
    *,
    initiator_telegram_user_id: int | None = None,
    chat_id: int | None = None,
    range_start: Any = None,
    range_end: Any = None,
) -> dict[str, Any]:
    """Получает расписания участников и связанные с ними ограничения."""

    from datetime import datetime, timezone

    clean = list({
        str(username).lstrip("@").strip().lower()
        for username in usernames
        if str(username).strip()
    })

    if not clean:
        return {
            "participants": {},
            "access_denied": [],
            "initiator_timezone": "Europe/Moscow",
        }

    with get_connection() as conn:
        users = conn.execute(
            """
            SELECT
                user_id,
                lower(telegram_username) AS username,
                timezone,
                basic_privacy_type
            FROM users
            WHERE lower(telegram_username) = ANY(%s)
            """,
            (clean,),
        ).fetchall()

        user_by_name = {
            row["username"]: row
            for row in users
            if row["username"]
        }

        participant_ids = [row["user_id"] for row in users]

        initiator = None

        if initiator_telegram_user_id is not None:
            initiator = conn.execute(
                """
                SELECT user_id, timezone
                FROM users
                WHERE telegram_user_id = %s
                """,
                (initiator_telegram_user_id,),
            ).fetchone()

        group = None

        if chat_id is not None and chat_id < 0:
            group = conn.execute(
                """
                SELECT group_id
                FROM groups
                WHERE telegram_chat_id = %s
                """,
                (chat_id,),
            ).fetchone()

        relation_rows = []
        group_member_ids = set()

        if participant_ids and initiator:
            relation_rows = conn.execute(
                """
                SELECT user_id, target_id, relation_type
                FROM user_relations
                WHERE (user_id = %s AND target_id = ANY(%s))
                   OR (target_id = %s AND user_id = ANY(%s))
                """,
                (
                    initiator["user_id"],
                    participant_ids,
                    initiator["user_id"],
                    participant_ids,
                ),
            ).fetchall()

        if group:
            memberships = conn.execute(
                """
                SELECT user_id
                FROM group_memberships
                WHERE group_id = %s
                  AND status = 'active'
                """,
                (group["group_id"],),
            ).fetchall()

            group_member_ids = {
                row["user_id"] for row in memberships
            }

        relations = {}

        for row in relation_rows:
            relations.setdefault(row["user_id"], []).append(
                (row["target_id"], row["relation_type"])
            )

        allowed = {}
        denied = []

        for username in clean:
            user = user_by_name.get(username)

            if not user:
                denied.append(username)
                continue

            user_id = user["user_id"]

            if initiator and user_id == initiator["user_id"]:
                allowed[username] = user
                continue

            linked = (
                relations.get(initiator["user_id"], [])
                if initiator else []
            )

            reverse = (
                relations.get(user_id, [])
                if initiator else []
            )

            blocked = (
                any(
                    target == user_id and kind == "blocked"
                    for target, kind in linked
                )
                or any(
                    target == initiator["user_id"] and kind == "blocked"
                    for target, kind in reverse
                )
            ) if initiator else False

            is_friend = (
                any(
                    target == initiator["user_id"] and kind == "friend"
                    for target, kind in reverse
                )
            ) if initiator else False

            same_group = bool(
                group
                and initiator
                and user_id in group_member_ids
                and initiator["user_id"] in group_member_ids
            )

            privacy = user["basic_privacy_type"]

            can_view = (
                not blocked
                and privacy != "unavailable"
                and (
                    privacy == "open"
                    or is_friend
                    or same_group
                )
            )

            if can_view:
                allowed[username] = user
            else:
                denied.append(username)

        initiator_timezone = (
            initiator["timezone"]
            if initiator
            else "Europe/Moscow"
        )

        if not allowed:
            return {
                "participants": {},
                "access_denied": denied,
                "initiator_timezone": initiator_timezone,
            }

        ids = [
            user["user_id"]
            for user in allowed.values()
        ]

        if range_start is None:
            range_start = datetime.min.replace(
                tzinfo=timezone.utc
            )

        if range_end is None:
            range_end = datetime.max.replace(
                tzinfo=timezone.utc
            )

        interval_rows = conn.execute(
            """
            SELECT
                user_id,
                day,
                start_time::text AS start_time,
                end_time::text AS end_time,
                group_id
            FROM intervals
            WHERE user_id = ANY(%s)
              AND (
                    group_id IS NULL
                    OR (
                        group_id = %s
                        AND user_id IN (
                            SELECT user_id
                            FROM group_memberships
                            WHERE group_id = %s
                              AND status = 'active'
                        )
                    )
              )
            ORDER BY user_id, day, start_time
            """,
            (
                ids,
                group["group_id"] if group else None,
                group["group_id"] if group else None,
            ),
        ).fetchall()

        exception_rows = conn.execute(
            """
            SELECT
                user_id,
                is_free,
                start_datetime,
                end_datetime
            FROM availability_exceptions
            WHERE user_id = ANY(%s)
              AND start_datetime < %s
              AND end_datetime > %s
            ORDER BY user_id, start_datetime
            """,
            (
                ids,
                range_end,
                range_start,
            ),
        ).fetchall()

        meeting_rows = conn.execute(
            """
            SELECT
                mp.user_id,
                m.start_datetime,
                m.start_datetime
                    + make_interval(mins => m.duration_minutes)
                    AS end_datetime
            FROM meeting_participants mp
            JOIN meetings m
                ON m.meeting_id = mp.meeting_id
            WHERE mp.user_id = ANY(%s)
              AND mp.status <> 'declined'
              AND m.status = 'confirmed'
              AND m.start_datetime < %s
              AND m.start_datetime
                    + make_interval(mins => m.duration_minutes) > %s
            ORDER BY mp.user_id, m.start_datetime
            """,
            (
                ids,
                range_end,
                range_start,
            ),
        ).fetchall()

    result = {}

    for username, user in allowed.items():
        user_id = user["user_id"]

        result[username] = {
            "user_id": user_id,
            "timezone": user["timezone"],
            "basic_privacy_type": user["basic_privacy_type"],
            "intervals": [
                dict(row)
                for row in interval_rows
                if row["user_id"] == user_id
            ],
            "exceptions": [
                dict(row)
                for row in exception_rows
                if row["user_id"] == user_id
            ],
            "meetings": [
                dict(row)
                for row in meeting_rows
                if row["user_id"] == user_id
            ],
        }

    return {
        "participants": result,
        "access_denied": denied,
        "initiator_timezone": initiator_timezone,
    }


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


def save_availability_exceptions(
    telegram_user_id: int,
    username: Optional[str],
    exceptions: list[dict],
) -> int:
    """Сохраняет разовые изменения доступности пользователя."""

    normalized = []

    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT user_id, timezone
            FROM users
            WHERE telegram_user_id = %s
            """,
            (telegram_user_id,),
        ).fetchone()

        if user is None:
            user_id = _ensure_user(
                conn,
                telegram_user_id,
                username,
                "Europe/Moscow",
            )
            timezone_name = "Europe/Moscow"
        else:
            user_id = user["user_id"]
            timezone_name = user["timezone"] or "Europe/Moscow"

        try:
            user_tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            user_tz = ZoneInfo("Europe/Moscow")

        for item in exceptions:
            if not isinstance(item, dict):
                raise ValueError("Некорректный формат исключения.")

            date_value = item.get("date")
            time_value = item.get("time") or {}

            if not date_value or not isinstance(time_value, dict):
                raise ValueError(
                    "Для исключения нужны конкретная дата и время."
                )

            try:
                exception_date = date.fromisoformat(str(date_value))
            except ValueError as exc:
                raise ValueError(
                    "Дата должна иметь формат ГГГГ-ММ-ДД."
                ) from exc

            start_time = normalize_time(
                time_value.get("start_time")
            )
            end_time = normalize_time(
                time_value.get("end_time")
            )

            if (
                start_time is None
                or end_time is None
                or end_time <= start_time
            ):
                raise ValueError(
                    "Некорректный временной интервал исключения."
                )

            is_free = item.get("is_available")

            if not isinstance(is_free, bool):
                raise ValueError(
                    "Не указано значение доступности исключения."
                )

            start_dt = datetime.combine(
                exception_date,
                start_time,
                tzinfo=user_tz,
            )
            end_dt = datetime.combine(
                exception_date,
                end_time,
                tzinfo=user_tz,
            )

            normalized.append(
                (is_free, start_dt, end_dt)
            )

        for is_free, start_dt, end_dt in normalized:
            conn.execute(
                """
                DELETE FROM availability_exceptions
                WHERE user_id = %s
                  AND start_datetime = %s
                  AND end_datetime = %s
                """,
                (user_id, start_dt, end_dt),
            )

            conn.execute(
                """
                INSERT INTO availability_exceptions (
                    user_id,
                    is_free,
                    start_datetime,
                    end_datetime
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    user_id,
                    is_free,
                    start_dt,
                    end_dt,
                ),
            )

    logger.info(
        "Availability exceptions saved: user=%s, count=%d",
        telegram_user_id,
        len(normalized),
    )

    return len(normalized)