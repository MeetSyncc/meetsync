
import re

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from states.state import Meeting
from keyboards.keyboards import (
    main_menu,
    participants_keyboard,
    date_keyboard,
    confirm_keyboard,
)
from services.meeting import (
    parse_date_period,
    validate_date_period,
    parse_time_period,
    validate_and_search,
)

router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я MeetSync. Помогу найти общее свободное время для встречи.",
        reply_markup=main_menu,
    )


@router.message(Command("help"))
@router.message(F.text == "Помощь")
async def help_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "«Моя доступность» — настройка расписания.\n"
        "«Найти время» — создание встречи.\n"
        "Для отмены отправь /cancel.",
        reply_markup=main_menu,
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu)


@router.message(F.text == "Найти время")
async def find_time_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Meeting.waiting_participants)
    await message.answer(
        "Давай подберём время. Выбери способ добавления участников.\n"
        "Указывай Telegram username через @.",
        reply_markup=participants_keyboard,
    )


@router.message(Meeting.waiting_participants)
async def save_participants(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь имена участников текстом.")
        return

    # Разделяем только по запятым и точкам с запятой.
    # Пробелы внутри ФИО сохраняются.
    raw_names = re.split(r"[,;]+", message.text)

    names = []
    seen = set()

    for item in raw_names:
        name = item.strip()

        if not name:
            continue

        name = name.lstrip("@").strip()

        if not name:
            continue

        normalized = name.casefold()

        if normalized not in seen:
            names.append(name)
            seen.add(normalized)

    if not names:
        await message.answer(
            "Не удалось распознать участников. "
            "Введи имена через запятую."
        )
        return

    if len(names) > 20:
        await message.answer("Можно добавить не больше 20 участников.")
        return

    await state.update_data(participants=names)
    await state.set_state(Meeting.waiting_date)

    await message.answer(
        "Участники добавлены:\n"
        + "\n".join("• " + name for name in names)
        + "\n\nНа какие дни искать время?",
        reply_markup=date_keyboard,
    )


@router.message(Meeting.waiting_date)
async def manual_date(message: Message, state: FSMContext):
    parsed = parse_date_period(message.text or "")

    if not parsed:
        await message.answer(
            "Введи дату ДД.ММ или период ДД.ММ-ДД.ММ, "
            "например 10.11-15.11."
        )
        return

    start, end = parsed
    error = validate_date_period(start, end)

    if error:
        await message.answer(error)
        return

    await state.update_data(
        date_start=start.isoformat(),
        date_end=end.isoformat(),
    )
    await state.set_state(Meeting.confirming_date)

    await message.answer(
        f"Ищем с {start:%d.%m.%Y} по {end:%d.%m.%Y}. Верно?",
        reply_markup=confirm_keyboard("date"),
    )


@router.message(Meeting.waiting_custom_time)
async def manual_time(message: Message, state: FSMContext):
    parsed = parse_time_period(message.text or "")

    if not parsed:
        await message.answer(
            "Введи время в формате ЧЧ:ММ-ЧЧ:ММ, "
            "например 14:00-18:00."
        )
        return

    start, end = parsed

    await state.update_data(
        time_start=start.strftime("%H:%M"),
        time_end=end.strftime("%H:%M"),
        time_label="свой период",
    )
    await state.set_state(Meeting.confirming_time)

    await message.answer(
        f"Ищем время с {start:%H:%M} до {end:%H:%M}. Верно?",
        reply_markup=confirm_keyboard("time"),
    )


@router.message(Meeting.waiting_custom_duration)
async def custom_duration(message: Message, state: FSMContext):
    value = (message.text or "").strip()

    if not value.isdigit() or not 1 <= int(value) <= 1440:
        await message.answer(
            "Введи целое число минут от 1 до 1440."
        )
        return

    await validate_and_search(message, state, int(value))


@router.message(StateFilter(None))
async def unknown(message: Message):
    await message.answer(
        "Не понял сообщение. Используй кнопки меню или /help. "
        "Для отмены — /cancel.",
        reply_markup=main_menu,
    )
