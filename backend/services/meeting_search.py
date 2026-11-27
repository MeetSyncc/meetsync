"""
Поиск общих свободных слотов с учётом часовых поясов,
регулярной доступности, исключений и существующих встреч.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.database import get_intervals_by_usernames


class AvailabilityDataMissingError(Exception):
    """Нет данных о доступности одного или нескольких участников."""

    def __init__(self, usernames: list[str]):
        self.usernames = usernames
        super().__init__("Не хватает данных о доступности участников.")


def _parse_date(value: str | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _get_timezone(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(value or "Europe/Moscow")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Europe/Moscow")


def _to_utc(value: datetime, tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(timezone.utc)


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []

    intervals = sorted(intervals)
    result = [intervals[0]]

    for start, end in intervals[1:]:
        last_start, last_end = result[-1]

        if start <= last_end:
            result[-1] = (last_start, max(last_end, end))
        else:
            result.append((start, end))

    return result


def _subtract_interval(
    intervals: list[tuple[datetime, datetime]],
    busy_start: datetime,
    busy_end: datetime,
) -> list[tuple[datetime, datetime]]:
    result = []

    for start, end in intervals:
        if busy_end <= start or busy_start >= end:
            result.append((start, end))
            continue

        if start < busy_start:
            result.append((start, busy_start))

        if busy_end < end:
            result.append((busy_end, end))

    return result


def _intersect_intervals(
    first: list[tuple[datetime, datetime]],
    second: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    result = []

    for first_start, first_end in first:
        for second_start, second_end in second:
            start = max(first_start, second_start)
            end = min(first_end, second_end)

            if start < end:
                result.append((start, end))

    return _merge_intervals(result)


def _get_search_windows(
    date_start: date,
    date_end: date,
    time_start: time,
    time_end: time,
    tz: ZoneInfo,
) -> list[tuple[datetime, datetime]]:
    windows = []
    current = date_start

    while current <= date_end:
        start = datetime.combine(current, time_start, tzinfo=tz)

        end_date = current
        if time_end < time_start:
            end_date += timedelta(days=1)

        end = datetime.combine(end_date, time_end, tzinfo=tz)

        windows.append((
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        ))

        current += timedelta(days=1)

    return _merge_intervals(windows)


def _has_availability_data(user_data: dict[str, Any]) -> bool:
    """Проверяет, указал ли пользователь хотя бы один период доступности."""

    if user_data.get("intervals"):
        return True

    return any(
        item.get("is_free")
        for item in user_data.get("exceptions", [])
    )


def _get_participant_availability(
    user_data: dict[str, Any],
    search_start: datetime,
    search_end: datetime,
) -> list[tuple[datetime, datetime]]:
    tz = _get_timezone(user_data.get("timezone"))

    # Формируем регулярные интервалы в часовом поясе участника.
    intervals = []

    local_start = (
        search_start - timedelta(days=1)
    ).astimezone(tz).date()

    local_end = (
        search_end + timedelta(days=1)
    ).astimezone(tz).date()

    current = local_start

    while current <= local_end:
        for item in user_data.get("intervals", []):
            if item["day"] != current.isoweekday():
                continue

            start_time = _parse_time(item["start_time"])
            end_time = _parse_time(item["end_time"])

            start = datetime.combine(current, start_time, tzinfo=tz)
            end = datetime.combine(current, end_time, tzinfo=tz)

            start = start.astimezone(timezone.utc)
            end = end.astimezone(timezone.utc)

            if start < end:
                intervals.append((start, end))

        current += timedelta(days=1)

    intervals = _merge_intervals(intervals)

    # Добавляем разовые периоды, когда участник свободен.
    free_exceptions = []

    for item in user_data.get("exceptions", []):
        if not item["is_free"]:
            continue

        start = _to_utc(item["start_datetime"], tz)
        end = _to_utc(item["end_datetime"], tz)

        if start < end:
            free_exceptions.append((start, end))

    intervals = _merge_intervals(intervals + free_exceptions)

    # Убираем разовые периоды занятости.
    for item in user_data.get("exceptions", []):
        if item["is_free"]:
            continue

        start = _to_utc(item["start_datetime"], tz)
        end = _to_utc(item["end_datetime"], tz)

        intervals = _subtract_interval(intervals, start, end)

    # Убираем время подтверждённых встреч.
    for item in user_data.get("meetings", []):
        start = _to_utc(item["start_datetime"], tz)
        end = _to_utc(item["end_datetime"], tz)

        intervals = _subtract_interval(intervals, start, end)

    return intervals


def find_common_times(
    meeting_data: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Ищет до пяти общих слотов заданной длительности.

    Учитывает часовые пояса, регулярные интервалы,
    исключения и подтверждённые встречи.

    Возвращает слоты с часовым поясом инициатора.
    """

    participants = list({
        str(p).lstrip("@").strip().lower()
        for p in meeting_data.get("participants") or []
        if str(p).strip()
    })

    if not participants:
        return []

    duration = int(meeting_data.get("duration") or 60)

    if duration < 1 or duration > 1440:
        raise ValueError("Некорректная длительность встречи.")

    date_start = _parse_date(meeting_data["date_start"])
    date_end = _parse_date(meeting_data["date_end"])

    if date_end < date_start:
        return []

    time_start = _parse_time(
        meeting_data.get("time_start", "00:00")
    )
    time_end = _parse_time(
        meeting_data.get("time_end", "23:59")
    )

    # Получаем данные участников и проверяем права доступа.
    # Добавляем запас по датам для учёта часовых поясов.
    data = get_intervals_by_usernames(
        participants,
        initiator_telegram_user_id=meeting_data.get(
            "initiator_telegram_user_id"
        ),
        chat_id=meeting_data.get("chat_id"),
        range_start=datetime.combine(
            date_start - timedelta(days=2),
            time.min,
            tzinfo=timezone.utc,
        ),
        range_end=datetime.combine(
            date_end + timedelta(days=3),
            time.min,
            tzinfo=timezone.utc,
        ),
    )

    access_denied = data.get("access_denied", [])

    if access_denied:
        raise PermissionError(
            f"Нет доступа к расписанию участников: {access_denied}"
        )

    participants_data = data.get("participants", {})

    # Проверяем наличие данных у каждого участника.
    missing_availability = []

    for username in participants:
        participant = participants_data.get(username)

        if participant is None:
            missing_availability.append(username)
            continue

        if not _has_availability_data(participant):
            missing_availability.append(username)

    if missing_availability:
        raise AvailabilityDataMissingError(
            missing_availability
        )

    # Введённое время считается временем инициатора.
    initiator_tz = _get_timezone(
        data.get("initiator_timezone")
    )

    search_windows = _get_search_windows(
        date_start,
        date_end,
        time_start,
        time_end,
        initiator_tz,
    )

    if not search_windows:
        return []

    search_start = search_windows[0][0]
    search_end = search_windows[-1][1]

    # Получаем скорректированную доступность каждого участника.
    common = None

    for username in participants:
        availability = _get_participant_availability(
            participants_data[username],
            search_start,
            search_end,
        )

        common = (
            availability
            if common is None
            else _intersect_intervals(common, availability)
        )

        if not common:
            return []

    # Ограничиваем пересечение выбранными датами и временем.
    common = _intersect_intervals(common, search_windows)

    # Формируем слоты заданной длительности.
    results = []

    for start, end in common:
        slot_start = start

        while (
            slot_start + timedelta(minutes=duration) <= end
            and len(results) < 5
        ):
            slot_end = slot_start + timedelta(minutes=duration)

            results.append({
                "start": slot_start.astimezone(
                    initiator_tz
                ).isoformat(),
                "end": slot_end.astimezone(
                    initiator_tz
                ).isoformat(),
            })

            slot_start = slot_end

        if len(results) >= 5:
            break

    return results
