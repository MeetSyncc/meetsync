from aiogram.fsm.state import State, StatesGroup


class Availability(StatesGroup):
    waiting_text = State()          # ждём свободный текст от пользователя
    confirming = State()            # показали summary_ru, ждём «Да / Изменить / Отмена»
    waiting_manual = State()        # fallback: ручной ввод (заглушка под будущую форму)
