from unittest.mock import AsyncMock
from datetime import date, datetime
import pytest
from services import meeting
from handlers import message as mh, callback as ch, availability as ah
from states.state import Meeting
from states.availability import Availability
from meetsync_llm import ParsingResult
from services import database

async def prepare(state):
    await state.update_data(participants=['anya','boris'],date_start='2026-11-23',date_end='2026-11-23',time_start='18:00',time_end='22:00')
    await state.set_state(Meeting.waiting_duration_choice)

async def test_bot_uses_database_search(db,seeded,frozen,message,state):
    await prepare(state)
    await meeting.validate_and_search(message,state,60)
    assert await state.get_state()==Meeting.choosing_slot.state
    assert len((await state.get_data())['slots'])==3

async def test_cancel_clears_fsm(state,message):
    await prepare(state)
    await mh.cancel(message,state)
    assert await state.get_state() is None
    assert await state.get_data()=={}

async def test_retry_time_after_invalid_input(state,message):
    await state.set_state(Meeting.waiting_custom_time)
    message.text='25:80-26:00'
    await mh.manual_time(message,state)
    assert await state.get_state()==Meeting.waiting_custom_time.state
    assert 'time_start' not in await state.get_data()
    message.text='14:00-18:00'
    await mh.manual_time(message,state)
    assert await state.get_state()==Meeting.confirming_time.state
    assert (await state.get_data())['time_start']=='14:00'

async def test_empty_availability_message(state,message,frozen,monkeypatch):
    await prepare(state)
    lookup=AsyncMock(return_value=[])
    monkeypatch.setattr(meeting,'find_common_times',lookup)
    await meeting.validate_and_search(message,state,60)
    buttons=message.answer.call_args.kwargs['reply_markup'].inline_keyboard
    assert {b.callback_data for row in buttons for b in row}=={'notfound:period','notfound:duration','notfound:participants','cancel'}

async def test_period_too_short(state,message,frozen):
    await prepare(state)
    await state.update_data(time_start='14:00',time_end='15:00')
    await meeting.validate_and_search(message,state,120)
    buttons=message.answer.call_args.kwargs['reply_markup'].inline_keyboard
    assert {b.callback_data for row in buttons for b in row}=={'fix:time','fix:duration','cancel'}

@pytest.mark.parametrize('value',['','abc','0','-10','1441','1.5'])
async def test_invalid_duration_input(value,state,message,monkeypatch):
    search=AsyncMock()
    monkeypatch.setattr(mh,'validate_and_search',search)
    message.text=value
    await mh.custom_duration(message,state)
    search.assert_not_called()
    assert message.answer.called

async def test_unicode_digit_does_not_crash(state,message):
    message.text='²'
    await mh.custom_duration(message,state)
    assert message.answer.called

async def test_overnight_confirmation(state,message):
    await state.set_state(Meeting.waiting_custom_time)
    message.text='22:00-02:00'
    await mh.manual_time(message,state)
    assert await state.get_state()==Meeting.confirming_time.state
    assert meeting.period_minutes(*meeting.parse_time_period(message.text))==240

async def test_missing_availability_is_not_reported_as_no_overlap(db,seeded,state,message,frozen):
    await prepare(state)
    await state.update_data(participants=['anya','egor'])
    await meeting.validate_and_search(message,state,60)
    texts=' '.join(call.args[0] for call in message.answer.call_args_list)
    assert 'egor' in texts.lower() and 'доступност' in texts.lower()

async def test_participant_deduplication(state,message):
    message.text='@Anya, anya; Boris'
    await mh.save_participants(message,state)
    assert (await state.get_data())['participants']==['Anya','Boris']

async def test_llm_to_fsm_to_db(db,state,message,callback,monkeypatch):
    parsed=ParsingResult(status='success',raw_text='по понедельникам с 18 до 22',recurring_slots=[{'days':['monday'],'time':{'start_time':'18:00','end_time':'22:00'}}],summary_ru='Пн 18–22')
    monkeypatch.setattr(ah,'parse_user_availability',AsyncMock(return_value=parsed))
    message.text=parsed.raw_text
    await state.set_state(Availability.waiting_text)
    await ah.process_availability_text(message,state)
    assert await state.get_state()==Availability.confirming.state
    await ah.confirm_availability(callback,state)
    assert await state.get_state() is None
    assert database.get_user_intervals(512345678)==[dict(day=1,start_time='18:00:00',end_time='22:00:00')]

async def test_ambiguous_llm_input_requests_clarification(state,message,monkeypatch):
    parsed=ParsingResult(status='clarification_needed',raw_text='потом',clarification_message='Укажи день и время')
    monkeypatch.setattr(ah,'parse_user_availability',AsyncMock(return_value=parsed))
    await state.set_state(Availability.waiting_text)
    message.text='потом'
    await ah.process_availability_text(message,state)
    assert await state.get_state()==Availability.waiting_text.state
    assert 'availability_raw' not in await state.get_data()
    assert message.answer.call_args.args[0]=='Укажи день и время'

async def test_stale_slot_rejected(state,message,callback,frozen):
    await state.update_data(slots=[dict(start='2026-11-11T10:00:00',end='2026-11-11T11:00:00')])
    await state.set_state(Meeting.choosing_slot)
    callback.data='slot:0'
    await ch.choose_slot(callback,state)
    assert await state.get_state()!=Meeting.confirming_invitation.state

async def test_today_past_period_rejected(state,message,frozen,monkeypatch):
    await prepare(state)
    await state.update_data(date_start='2026-11-12',date_end='2026-11-12',time_start='09:00',time_end='10:00')
    search=AsyncMock(return_value=[])
    monkeypatch.setattr(meeting,'find_common_times',search)
    await meeting.validate_and_search(message,state,60)
    search.assert_not_called()

@pytest.mark.parametrize('value',['15:00-15:00','25:00-26:00','hello'])
def test_invalid_time(value):
    assert meeting.parse_time_period(value) is None

def test_reversed_dates(frozen):
    assert meeting.validate_date_period(date(2026,11,20),date(2026,11,13)) is not None

def test_leap_day(monkeypatch):
    class LeapYear(date):
        @classmethod
        def today(cls): return cls(2028,1,1)
    monkeypatch.setattr(meeting,'date',LeapYear)
    assert meeting.parse_date_period('29.02')==(date(2028,2,29),date(2028,2,29))

async def test_cancel_through_real_router_order():
    from aiogram import Bot, Dispatcher
    from aiogram.types import Update, Message, Chat, User, MessageEntity
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.memory import MemoryStorage
    storage=MemoryStorage()
    dp=Dispatcher(storage=storage)
    dp.include_router(ah.router)
    dp.include_router(mh.router)
    dp.include_router(ch.router)
    bot=Bot(token='123456:TEST_ONLY_NO_NETWORK')
    # Mock transport only; use actual Dispatcher, router filters, FSM and handlers.
    bot.session=AsyncMock()
    ctx=FSMContext(storage,StorageKey(bot_id=123456,chat_id=1,user_id=1))
    await prepare(ctx)
    update=Update(update_id=1,message=Message(message_id=1,date=datetime(2026,11,12),chat=Chat(id=1,type='private'),from_user=User(id=1,is_bot=False,first_name='Test'),text='/cancel',entities=[MessageEntity(type='bot_command',offset=0,length=7)]))
    try:
        await dp.feed_update(bot,update)
        assert await ctx.get_state() is None
        assert await ctx.get_data()=={}
    finally:
        await storage.close()
        await bot.session.close()
