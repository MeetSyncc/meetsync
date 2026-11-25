
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from keyboards.keyboards import main_menu
from services.database import save_availability
from services.llm_parser import parse_user_availability
from states.availability import Availability

logger = logging.getLogger(__name__)
router = Router(name="availability")


def confirm_availability_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, верно",
                    callback_data="avail:confirm",
                ),
                InlineKeyboardButton(
                    text="Изменить",
                    callback_data="avail:change",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="avail:cancel",
                )
            ],
        ]
    )


@router.message(Command("availability"))
@router.message(F.text == "Моя доступность")
async def start_availability(
    message: Message,
    state: FSMContext,
) -> None:
    await state.clear()
    await state.set_state(Availability.waiting_text)

    await message.answer(
        "Напиши, в какие дни и часы ты обычно свободен.\n\n"
        "Примеры:\n"
        "• по будням с 18:00 до 21:00\n"
        "• вторник и четверг после 17:00\n"
        "• суббота весь день, воскресенье до 15:00\n\n"
        "Можно писать как удобно — я разберу."
    )


@router.message(Availability.waiting_text)
async def process_availability_text(
    message: Message,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer("Пришли текстовое описание расписания.")
        return

    wait_msg = await message.answer("Разбираю расписание...")

    try:
        result = await parse_user_availability(message.text)

    except ValueError as exc:
        logger.error("LLM configuration error: %s", exc)

        await wait_msg.delete()
        await message.answer(
            "LLM не настроен. Проверь GROQ_API_KEY в файле .env "
            "и перезапусти бота."
        )
        return

    except Exception:
        logger.exception("LLM call failed")

        await wait_msg.delete()
        await message.answer(
            "Не удалось обработать расписание. "
            "Попробуй ещё раз немного позже."
        )
        return

    await wait_msg.delete()

    if result.status == "success":
        raw = result.model_dump()

        await state.update_data(
            availability_raw=raw,
            summary_ru=result.summary_ru,
        )
        await state.set_state(Availability.confirming)

        await message.answer(
            "Вот что я понял:\n\n"
            f"{result.summary_ru}\n\n"
            "Пока сохраняются только регулярные интервалы. "
            "Разовые исключения ещё не поддерживаются.\n\n"
            "Всё верно?",
            reply_markup=confirm_availability_keyboard(),
        )
        return

    if result.status == "clarification_needed":
        await message.answer(
            result.clarification_message
            or "Уточни, пожалуйста, конкретные дни и временные интервалы."
        )
        return

    if result.fallback_to_manual:
        await state.set_state(Availability.waiting_manual)

        await message.answer(
            (result.error_message or "Не удалось разобрать расписание.")
            + "\n\nПопробуй описать расписание ещё раз. "
            "Для отмены отправь /cancel."
        )
        return

    await message.answer(
        result.error_message
        or "Ошибка разбора. Попробуй ещё раз."
    )


@router.callback_query(
    Availability.confirming,
    F.data == "avail:confirm",
)
async def confirm_availability(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    raw = data.get("availability_raw") or {}
    recurring = raw.get("recurring_slots") or []

    if not recurring:
        await callback.answer(
            "В расписании нет регулярных интервалов.",
            show_alert=True,
        )
        return

    await callback.answer("Сохраняю расписание...")

    try:
        await asyncio.to_thread(
            save_availability,
            telegram_user_id=callback.from_user.id,
            username=callback.from_user.username,
            recurring_slots=recurring,
        )

    except Exception:
        logger.exception("Failed to save availability")

        await callback.message.answer(
            "Не удалось сохранить расписание в PostgreSQL. "
            "Проверь подключение к базе данных и попробуй подтвердить ещё раз."
        )
        return

    await state.clear()

    await callback.message.edit_text(
        "Готово! Доступность сохранена:\n\n"
        f"{data.get('summary_ru', '')}"
    )

    await callback.message.answer(
        "Что дальше?",
        reply_markup=main_menu,
    )


@router.callback_query(
    Availability.confirming,
    F.data == "avail:change",
)
async def change_availability(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.set_state(Availability.waiting_text)

    await callback.message.edit_text(
        "Напиши расписание заново."
    )


@router.callback_query(F.data == "avail:cancel")
async def cancel_availability_cb(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()

    await callback.message.edit_text(
        "Действие отменено."
    )

    await callback.message.answer(
        "Главное меню",
        reply_markup=main_menu,
    )


@router.message(Command("cancel"), StateFilter(Availability))
async def cancel_availability_msg(
    message: Message,
    state: FSMContext,
) -> None:
    current = await state.get_state()

    if current and current.startswith("Availability:"):
        await state.clear()

        await message.answer(
            "Действие отменено.",
            reply_markup=main_menu,
        )


@router.message(Availability.waiting_manual)
async def manual_stub(
    message: Message,
    state: FSMContext,
) -> None:
    await message.answer(
        "Ручной ввод пока в разработке. "
        "Попробуй описать доступность обычным текстом "
        "или отправь /cancel."
    )
    await state.set_state(Availability.waiting_text)
