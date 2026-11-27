from aiogram.fsm.state import State, StatesGroup

class Meeting(StatesGroup):
    waiting_participants = State()
    waiting_date = State()
    confirming_date = State()
    waiting_time_choice = State()
    waiting_custom_time = State()
    confirming_time = State()
    waiting_duration_choice = State()
    waiting_custom_duration = State()
    choosing_slot = State()
    confirming_invitation = State()
