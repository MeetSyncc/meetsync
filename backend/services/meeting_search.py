"""
Поиск общих свободных слотов по интервалам из PostgreSQL.
Подключается в services/meeting.py вместо заглушки find_common_times.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from services.database import get_intervals_by_usernames


def _time_to_min(t: str | time) -> int:
    if isinstance(t, time):
        return t.hour * 60 + t.minute
    h, m = map(int, t.split(":")[:2])
    return h * 60 + m


def _min_to_str(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _intersect_intervals(a_start: int, a_end: int, b_start: int, b_end: int) -> tuple[int, int] | None:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if start < end:
        return start, end
    return None


def find_common_times(meeting_data: dict[str, Any]) -> list[dict[str, str]]:
    """
    meeting_data ожидает:
      participants: list[str]  — username без @
      date_start, date_end: ISO date strings
      time_start, time_end: "HH:MM"
      duration: int (минуты)

    Возвращает до 5 слотов вида {"start": "ISO", "end": "ISO"}.
    """
    participants = [p.lstrip("@") for p in meeting_data.get("participants") or []]
    if not participants:
        return []

    duration = int(meeting_data.get("duration") or 60)
    date_start = date.fromisoformat(meeting_data["date_start"])
    date_end = date.fromisoformat(meeting_data["date_end"])
    pref_start = _time_to_min(meeting_data.get("time_start", "00:00"))
    pref_end = _time_to_min(meeting_data.get("time_end", "23:59"))

    # Интервалы всех участников: {username: [{day, start_time, end_time}, ...]}
    all_intervals = get_intervals_by_usernames(participants)

    # Если у кого-то нет интервалов — пересечения нет
    for p in participants:
        if not all_intervals.get(p.lower()):
            return []

    results: list[dict[str, str]] = []
    current = date_start

    while current <= date_end and len(results) < 5:
        # ISO weekday: Monday=1 ... Sunday=7 (как в schema)
        day_num = current.isoweekday()

        # Собираем интервалы всех участников на этот день, обрезанные предпочтением
        day_windows: list[list[tuple[int, int]]] = []
        for p in participants:
            user_day = []
            for iv in all_intervals.get(p.lower(), []):
                if iv["day"] != day_num:
                    continue
                s = max(_time_to_min(iv["start_time"]), pref_start)
                e = min(_time_to_min(iv["end_time"]), pref_end)
                if s < e:
                    user_day.append((s, e))
            if not user_day:
                day_windows = []
                break
            day_windows.append(user_day)

        if not day_windows:
            current += timedelta(days=1)
            continue

        # Последовательное пересечение окон всех участников
        common = day_windows[0]
        for other in day_windows[1:]:
            new_common = []
            for a_s, a_e in common:
                for b_s, b_e in other:
                    inter = _intersect_intervals(a_s, a_e, b_s, b_e)
                    if inter and (inter[1] - inter[0]) >= duration:
                        new_common.append(inter)
            common = new_common
            if not common:
                break

        # Нарезаем слоты нужной длительности
        for s, e in sorted(common):
            slot_start = s
            while slot_start + duration <= e and len(results) < 5:
                slot_end = slot_start + duration
                start_dt = datetime.combine(current, time(slot_start // 60, slot_start % 60))
                end_dt = datetime.combine(current, time(slot_end // 60, slot_end % 60))
                results.append({
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat(),
                })
                slot_start += duration  # следующий возможный слот

        current += timedelta(days=1)

    return results
