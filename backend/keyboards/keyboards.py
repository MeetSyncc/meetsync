
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

WEEKDAYS_RU = [
    "Пн",
    "Вт",
    "Ср",
    "Чт",
    "Пт",
    "Сб",
    "Вс",
]


main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Моя доступность")],
        [KeyboardButton(text="Найти время")],
        [KeyboardButton(text="Помощь")],
    ],
    resize_keyboard=True,
)


def make_inline(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=title, callback_data=data)
                for title, data in row
            ]
            for row in rows
        ]
    )


participants_keyboard = make_inline([
    [("Список контактов", "participants:contacts")],
    [("Ввести вручную", "participants:manual")],
    [("Отмена", "cancel")],
])


date_keyboard = make_inline([
    [("Сегодня", "date:today"), ("Завтра", "date:tomorrow")],
    [("На этой неделе", "date:week")],
    [("Выбрать дату вручную", "date:manual")],
    [("Отмена", "cancel")],
])


time_keyboard = make_inline([
    [("Любое время", "time:any")],
    [
        ("Утро", "time:morning"),
        ("День", "time:day"),
        ("Вечер", "time:evening"),
    ],
    [("Свой период", "time:custom")],
    [("Отмена", "cancel")],
])


duration_keyboard = make_inline([
    [
        ("30 минут", "duration:30"),
        ("1 час", "duration:60"),
    ],
    [("3 часа", "duration:180")],
    [("Свой вариант", "duration:custom")],
    [("Отмена", "cancel")],
])


def confirm_keyboard(prefix):
    if prefix == "invite":
        return make_inline([
            [
                ("Отправить", "invite:send"),
                ("Назад", "invite:back"),
            ],
            [("Отмена", "cancel")],
        ])

    return make_inline([
        [
            ("Да, верно", f"{prefix}:confirm"),
            ("Изменить", f"{prefix}:change"),
        ],
        [("Отмена", "cancel")],
    ])


def slots_keyboard(slots):
    rows = []

    for index, slot in enumerate(slots):
        start = datetime.fromisoformat(slot["start"])
        end = datetime.fromisoformat(slot["end"])

        # Если часовой пояс не указан, считаем время московским.
        if start.tzinfo is None:
            start = start.replace(tzinfo=MOSCOW_TZ)
        else:
            start = start.astimezone(MOSCOW_TZ)

        if end.tzinfo is None:
            end = end.replace(tzinfo=MOSCOW_TZ)
        else:
            end = end.astimezone(MOSCOW_TZ)

        weekday = WEEKDAYS_RU[start.weekday()]

        title = (
            f"{index + 1}. {weekday}, "
            f"{start:%d.%m %H:%M}–{end:%H:%M} МСК"
        )

        rows.append([
            (title, f"slot:{index}")
        ])

    rows.append([("Отмена", "cancel")])

    return make_inline(rows)
