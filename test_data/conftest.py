import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, date
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from openpyxl import load_workbook

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'backend',ROOT/'databases',ROOT/'MeetSync-LLM'/'src'):
    sys.path.insert(0,str(p))
# Prevent accidental use of dotenv credentials in tests.
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['DATABASE_URL']='postgresql://invalid.invalid/never_connect'

def pytest_addoption(parser):
    parser.addoption('--without-postgres', action='store_true', help='Explicitly skip PostgreSQL integration in restricted environments')

@pytest.fixture(scope='session')
def server_url(tmp_path_factory,request):
    if request.config.getoption('--without-postgres'):
        pytest.skip('PostgreSQL not run: explicit --without-postgres; local sockets blocked')
    explicit=os.getenv('QA_TEST_DATABASE_URL')
    if explicit:
        yield explicit
    else:
        import pgserver
        server=pgserver.get_server(tmp_path_factory.mktemp('postgres'),cleanup_mode='delete')
        yield server.get_uri()

@pytest.fixture
def db(server_url,monkeypatch):
    from services import database
    name='qa_'+uuid.uuid4().hex
    with psycopg.connect(server_url,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    url=make_conninfo(server_url,options=f'-c search_path={name} -c timezone=Europe/Moscow')
    monkeypatch.setattr(database,'DATABASE_URL',url)
    monkeypatch.setenv('DATABASE_URL',url)
    conn=psycopg.connect(url,row_factory=dict_row)
    try:
        conn.execute((ROOT/'databases/schema.sql').read_text())
        conn.commit()
        yield conn
    finally:
        conn.close()
        with psycopg.connect(server_url,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))

@pytest.fixture(scope='session')
def workbook():
    w=load_workbook(ROOT/'qa/data/test_data.xlsx',data_only=True)
    try:
        return {s.title:[dict(zip(next(s.values),r)) for r in list(s.values)[1:]] for s in w}
    finally:
        w.close()

@pytest.fixture
def seeded(db,workbook):
    import repository as repo
    from zoneinfo import ZoneInfo
    users={r['telegram_user_id']:repo.create_user(db,**r) for r in workbook['users']}
    groups={r['telegram_chat_id']:repo.create_group(db,**r) for r in workbook['groups']}
    for r in workbook['intervals']:
        repo.create_interval(db,users[r['telegram_user_id']]['user_id'],r['day'],r['start_time'],r['end_time'],groups[r['telegram_chat_id']]['group_id'] if r['telegram_chat_id'] else None)
    for r in workbook['exceptions']:
        u=users[r['telegram_user_id']]
        repo.create_availability_exception(db,u['user_id'],r['is_free'],r['start_datetime'].replace(tzinfo=ZoneInfo(u['timezone'])),r['end_datetime'].replace(tzinfo=ZoneInfo(u['timezone'])))
    for r in workbook['group_members']:
        repo.add_group_member(db,groups[r['telegram_chat_id']]['group_id'],users[r['telegram_user_id']]['user_id'],r['status'])
    meetings={}
    for r in workbook['meetings']:
        start=r['start_datetime']
        meetings[r['meeting_key']]=repo.create_meeting(db,users[r['created_by_telegram_user_id']]['user_id'],r['duration_minutes'],groups[r['telegram_chat_id']]['group_id'],r['status'],start.replace(tzinfo=ZoneInfo('Europe/Moscow')) if start else None)
    for r in workbook['meeting_participants']:
        repo.add_meeting_participant(db,meetings[r['meeting_key']]['meeting_id'],users[r['telegram_user_id']]['user_id'],r['status'],r['is_required'])
    for r in workbook['relations']:
        repo.set_relation(db,users[r['telegram_user_id']]['user_id'],users[r['target_telegram_user_id']]['user_id'],r['relation_type'])
    db.commit()
    return dict(users=users,groups=groups,meetings=meetings)

@pytest.fixture
def frozen(monkeypatch):
    from services import meeting
    from handlers import callback
    class FixedDate(date):
        @classmethod
        def today(cls): return cls(2026,11,12)
    class FixedDatetime(datetime):
        @classmethod
        def now(cls,tz=None): return cls(2026,11,12,12,tzinfo=tz)
    monkeypatch.setattr(meeting,'date',FixedDate)
    monkeypatch.setattr(meeting,'datetime',FixedDatetime)
    monkeypatch.setattr(callback,'date',FixedDate)
    monkeypatch.setattr(callback,'datetime',FixedDatetime)

@pytest.fixture
def message():
    m=SimpleNamespace(text='',from_user=SimpleNamespace(id=512345678,username='anya'))
    m.answer=AsyncMock(return_value=SimpleNamespace(delete=AsyncMock()))
    m.edit_text=AsyncMock()
    return m

@pytest.fixture
def callback(message):
    return SimpleNamespace(answer=AsyncMock(),message=message,data='',from_user=message.from_user)

@pytest.fixture
async def state():
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.storage.base import StorageKey
    storage=MemoryStorage()
    yield FSMContext(storage,StorageKey(bot_id=1,chat_id=1,user_id=1))
    await storage.close()
