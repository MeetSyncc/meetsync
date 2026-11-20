
from datetime import date, time, timedelta, datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from states.state import Meeting
from keyboards.keyboards import (
    main_menu,
    time_keyboard,
    duration_keyboard,
    confirm_keyboard,
    slots_keyboard,
)
from services.meeting import (
    validate_date_period,
    validate_and_search,
    send_invitations,
)

router = Router()


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Действие отменено.",
        reply_markup=main_menu,
    )


@router.callback_query(
    Meeting.waiting_participants,
    F.data == "participants:contacts",
)
async def contacts(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Контакты пока не подключены. Выбери «Ввести вручную»."
    )


@router.callback_query(
    Meeting.waiting_participants,
    F.data == "participants:manual",
)
async def manual_participants(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Введи имена участников через запятую, "
        "например: Alex Smith, Maria Ivanova."
    )


@router.callback_query(
    Meeting.waiting_date,
    F.data.startswith("date:"),
)
async def choose_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    today = date.today()
    choice = callback.data.split(":")[1]

    if choice == "manual":
        await callback.message.answer(
            "Введи дату ДД.ММ или период ДД.ММ-ДД.ММ."
        )
        return

    if choice == "today":
        start = end = today

    elif choice == "tomorrow":
        start = end = today + timedelta(days=1)

    elif choice == "week":
        start = today
        end = today + timedelta(days=6 - today.weekday())

    else:
        return

    error = validate_date_period(start, end)

    if error:
        await callback.message.answer(error)
        return

    await state.update_data(
        date_start=start.isoformat(),
        date_end=end.isoformat(),
    )
    await state.set_state(Meeting.confirming_date)

    await callback.message.answer(
        f"Ищем с {start:%d.%m.%Y} по {end:%d.%m.%Y}. Верно?",
        reply_markup=confirm_keyboard("date"),
    )


@router.callback_query(
    Meeting.confirming_date,
    F.data == "date:confirm",
)
async def confirm_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_time_choice)

    await callback.message.answer(
        "Есть ли предпочтения по времени суток?",
        reply_markup=time_keyboard,
    )


@router.callback_query(
    Meeting.confirming_date,
    F.data == "date:change",
)
async def change_date(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_date)

    await callback.message.answer(
        "Введи даты заново: ДД.ММ или ДД.ММ-ДД.ММ."
    )


@router.callback_query(
    Meeting.waiting_time_choice,
    F.data.startswith("time:"),
)
async def choose_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    choice = callback.data.split(":")[1]

    if choice == "custom":
        await state.set_state(Meeting.waiting_custom_time)
        await callback.message.answer(
            "Введи интервал ЧЧ:ММ-ЧЧ:ММ, "
            "например 14:00-18:00."
        )
        return

    periods = {
        "any": (time(0, 0), time(23, 59), "любое время"),
        "morning": (time(8, 0), time(12, 0), "утро"),
        "day": (time(12, 0), time(18, 0), "день"),
        "evening": (time(18, 0), time(23, 59), "вечер"),
    }

    if choice not in periods:
        return

    start, end, label = periods[choice]

    await state.update_data(
        time_start=start.strftime("%H:%M"),
        time_end=end.strftime("%H:%M"),
        time_label=label,
    )
    await state.set_state(Meeting.waiting_duration_choice)

    await callback.message.answer(
        "Сколько времени нужно на встречу?",
        reply_markup=duration_keyboard,
    )


@router.callback_query(
    Meeting.confirming_time,
    F.data == "time:confirm",
)
async def confirm_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_duration_choice)

    await callback.message.answer(
        "Сколько времени нужно на встречу?",
        reply_markup=duration_keyboard,
    )


@router.callback_query(
    Meeting.confirming_time,
    F.data == "time:change",
)
async def change_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_custom_time)

    await callback.message.answer(
        "Введи интервал заново: ЧЧ:ММ-ЧЧ:ММ."
    )


@router.callback_query(
    Meeting.waiting_duration_choice,
    F.data.startswith("duration:"),
)
async def choose_duration(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    value = callback.data.split(":")[1]

    if value == "custom":
        await state.set_state(Meeting.waiting_custom_duration)
        await callback.message.answer(
            "Введи длительность в минутах, например 90."
        )
        return

    if not value.isdigit():
        await callback.message.answer("Некорректная длительность.")
        return

    await validate_and_search(
        callback.message,
        state,
        int(value),
    )


@router.callback_query(F.data == "notfound:period")
async def extend_period(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_date)

    await callback.message.answer(
        "Укажи расширенный период: ДД.ММ-ДД.ММ."
    )


@router.callback_query(F.data == "notfound:duration")
async def shorter_duration(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_duration_choice)

    await callback.message.answer(
        "Выбери меньшую длительность:",
        reply_markup=duration_keyboard,
    )


@router.callback_query(F.data == "notfound:participants")
async def edit_participants(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_participants)

    await callback.message.answer(
        "Введи участников заново через запятую."
    )


@router.callback_query(F.data == "fix:time")
async def fix_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_custom_time)

    await callback.message.answer(
        "Введи новый интервал: ЧЧ:ММ-ЧЧ:ММ."
    )


@router.callback_query(F.data == "fix:duration")
async def fix_duration(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Meeting.waiting_duration_choice)

    await callback.message.answer(
        "Выбери длительность:",
        reply_markup=duration_keyboard,
    )


@router.callback_query(
    Meeting.choosing_slot,
    F.data.startswith("slot:"),
)
async def choose_slot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    try:
        index = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.message.answer("Некорректный номер варианта.")
        return

    data = await state.get_data()
    slots = data.get("slots", [])

    if not isinstance(slots, list) or not 0 <= index < len(slots):
        await callback.message.answer(
            "Вариант недоступен. Начни поиск заново."
        )
        await state.clear()
        return

    selected = slots[index]

    try:
        start = datetime.fromisoformat(selected["start"])
        end = datetime.fromisoformat(selected["end"])
    except (KeyError, TypeError, ValueError):
        await callback.message.answer(
            "Не удалось прочитать выбранный вариант. Начни поиск заново."
        )
        await state.clear()
        return

    if end <= start:
        await callback.message.answer(
            "Время выбранного варианта некорректно. Начни поиск заново."
        )
        await state.clear()
        return

    await state.update_data(selected_slot=selected)
    await state.set_state(Meeting.confirming_invitation)

    await callback.message.answer(
        f"Ты выбрал: {start:%d.%m.%Y %H:%M}–{end:%H:%M}. "
        "Отправить приглашения?",
        reply_markup=confirm_keyboard("invite"),
    )


@router.callback_query(
    Meeting.confirming_invitation,
    F.data == "invite:back",
)
async def back_to_slots(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    data = await state.get_data()
    slots = data.get("slots", [])

    if not slots:
        await callback.message.answer(
            "Список вариантов не найден. Начни поиск заново.",
            reply_markup=main_menu,
        )
        await state.clear()
        return

    await state.set_state(Meeting.choosing_slot)

    await callback.message.answer(
        "Выбери другой вариант:",
        reply_markup=slots_keyboard(slots),
    )


@router.callback_query(
    Meeting.confirming_invitation,
    F.data == "invite:send",
)
async def send_invites(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    data = await state.get_data()

    if not data.get("selected_slot"):
        await callback.message.answer(
            "Сначала выбери время встречи."
        )
        await state.set_state(Meeting.choosing_slot)
        return

    if not await send_invitations(data):
        await callback.message.answer(
            "Отправка приглашений пока не подключена: "
            "сначала нужны chat_id участников и PostgreSQL."
        )
        return

    await callback.message.answer(
        "Приглашения отправлены. Ожидаем ответы.",
        reply_markup=main_menu,
    )
    await state.clear()
