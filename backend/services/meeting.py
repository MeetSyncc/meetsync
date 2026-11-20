
import re
from datetime import date, datetime

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from states.state import Meeting
from keyboards.keyboards import make_inline, slots_keyboard


def parse_date_period(value):
    value = value.strip().replace(" ", "").replace("–", "-")

    match = re.fullmatch(r"(\d{2}\.\d{2})(?:-(\d{2}\.\d{2}))?", value)
    if not match:
        return None

    year = date.today().year

    try:
        start = datetime.strptime(match.group(1), "%d.%m").date().replace(year=year)

        if match.group(2):
            end = datetime.strptime(match.group(2), "%d.%m").date().replace(year=year)
        else:
            end = start

    except ValueError:
        return None

    return start, end


def validate_date_period(start, end):
    if end < start:
        return "Ошибка: конечная дата не может быть раньше начальной."

    if start < date.today():
        return "Ошибка: выбранная дата уже прошла. Укажи будущие даты."

    if (end - start).days > 30:
        return "Период поиска слишком большой. Выбери диапазон не больше 30 дней."

    return None


def parse_time_period(value):
    value = value.strip().replace(" ", "").replace("–", "-")

    match = re.fullmatch(r"(\d{2}:\d{2})-(\d{2}:\d{2})", value)
    if not match:
        return None

    try:
        start = datetime.strptime(match.group(1), "%H:%M").time()
        end = datetime.strptime(match.group(2), "%H:%M").time()
    except ValueError:
        return None

    if start == end:
        return None

    return start, end


def period_minutes(start, end):
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute

    if end_minutes < start_minutes:
        end_minutes += 24 * 60

    return end_minutes - start_minutes


async def find_common_times(meeting_data):
    """
    Заглушка для будущего поиска в PostgreSQL.

    Ожидаемый формат результата:
    [
        {
            "start": "2026-11-21T14:00:00",
            "end": "2026-11-21T15:00:00"
        }
    ]
    """
    return []


def filter_future_slots(slots):
    """Проверяет формат вариантов и исключает прошедшее время."""
    result = []

    for slot in slots:
        try:
            start = datetime.fromisoformat(slot["start"])
            end = datetime.fromisoformat(slot["end"])

            if end <= start:
                continue

            now = datetime.now(start.tzinfo) if start.tzinfo else datetime.now()

            if start > now:
                result.append(slot)

        except (KeyError, TypeError, ValueError):
            continue

    return result


async def validate_and_search(message: Message, state: FSMContext, duration: int):
    if not isinstance(duration, int) or duration < 1 or duration > 1440:
        await message.answer("Длительность должна составлять от 1 до 1440 минут.")
        await state.set_state(Meeting.waiting_custom_duration)
        return

    data = await state.get_data()

    if not data.get("participants"):
        await message.answer("Сначала добавь участников.")
        await state.set_state(Meeting.waiting_participants)
        return

    if not data.get("date_start") or not data.get("date_end"):
        await message.answer("Сначала укажи дату поиска.")
        await state.set_state(Meeting.waiting_date)
        return

    if not data.get("time_start") or not data.get("time_end"):
        await message.answer("Сначала укажи время поиска.")
        await state.set_state(Meeting.waiting_time_choice)
        return

    try:
        date_start = date.fromisoformat(data["date_start"])
        date_end = date.fromisoformat(data["date_end"])
        start_time = datetime.strptime(data["time_start"], "%H:%M").time()
        end_time = datetime.strptime(data["time_end"], "%H:%M").time()
    except (TypeError, ValueError):
        await message.answer("Не удалось прочитать дату или время. Введи данные заново.")
        await state.set_state(Meeting.waiting_date)
        return

    date_error = validate_date_period(date_start, date_end)
    if date_error:
        await message.answer(date_error)
        await state.set_state(Meeting.waiting_date)
        return

    if period_minutes(start_time, end_time) < duration:
        await message.answer(
            "Выбранный период меньше длительности встречи. "
            "Увеличь период или сократи длительность.",
            reply_markup=make_inline([
                [("Изменить период", "fix:time")],
                [("Изменить длительность", "fix:duration")],
                [("Отмена", "cancel")],
            ]),
        )
        return

    await state.update_data(duration=duration)

    await message.answer("Проверяю доступность участников...")

    data = await state.get_data()
    slots = await find_common_times(data)
    slots = filter_future_slots(slots)

    if not slots:
        await message.answer(
            "К сожалению, общего времени не нашлось. Что делаем?",
            reply_markup=make_inline([
                [("Расширить период", "notfound:period")],
                [("Сократить длительность", "notfound:duration")],
                [("Уточнить участников", "notfound:participants")],
                [("Отмена", "cancel")],
            ]),
        )
        return

    slots.sort(key=lambda slot: datetime.fromisoformat(slot["start"]))
    slots = slots[:3]

    await state.update_data(slots=slots)
    await state.set_state(Meeting.choosing_slot)

    await message.answer(
        f"Нашёл {len(slots)} вариантов. Выбери удобный:",
        reply_markup=slots_keyboard(slots),
    )


async def send_invitations(meeting_data):
    """
    Заглушка для будущей отправки приглашений через Telegram.
    Потребуются chat_id участников и подключение PostgreSQL.
    """
    return False
