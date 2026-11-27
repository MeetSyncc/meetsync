from datetime import time, datetime
import pytest
import psycopg
import repository as r
from services import database as d

@pytest.mark.parametrize('day',[0,8,-1])
def test_invalid_day_rejected(db,day):
    u=r.create_user(db,1)
    with pytest.raises(psycopg.errors.CheckViolation):
        r.create_interval(db,u['user_id'],day,time(10),time(11))

def test_group_scope_and_normalized_lookup(db):
    u=r.create_user(db,1,'AnYa')
    g=r.create_group(db,-1)
    r.create_interval(db,u['user_id'],1,time(10),time(12))
    r.create_interval(db,u['user_id'],1,time(15),time(17),g['group_id'])
    db.commit()
    assert d.get_intervals_by_usernames(['@ANYA'])=={'anya':[dict(day=1,start_time='10:00:00',end_time='12:00:00')]}

def test_save_replaces_global_preserves_group(db):
    u=r.create_user(db,1,'anya')
    g=r.create_group(db,-1)
    r.create_interval(db,u['user_id'],1,time(10),time(12))
    group_iv=r.create_interval(db,u['user_id'],1,time(15),time(17),g['group_id'])
    db.commit()
    slot=[dict(days=['tuesday'],time=dict(start_time='14:00',end_time='16:00'))]
    d.save_availability(1,'anya',slot)
    d.save_availability(1,'anya',slot)
    assert d.get_user_intervals(1)==[dict(day=2,start_time='14:00:00',end_time='16:00:00')]
    assert r.get_intervals(db,u['user_id'],g['group_id'])==[group_iv]

def test_failed_save_rolls_back(db):
    u=r.create_user(db,1,'anya')
    r.create_interval(db,u['user_id'],1,time(10),time(12))
    db.execute("CREATE FUNCTION reject_insert() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END; $$ LANGUAGE plpgsql")
    db.execute('CREATE TRIGGER fail_insert BEFORE INSERT ON intervals FOR EACH ROW EXECUTE FUNCTION reject_insert()')
    db.commit()
    with pytest.raises(psycopg.Error):
        d.save_availability(1,'anya',[dict(days=['tuesday'],time=dict(start_time='14:00',end_time='16:00'))])
    assert d.get_user_intervals(1)==[dict(day=1,start_time='10:00:00',end_time='12:00:00')]

def test_timezone_preserved_on_schedule_save(db):
    r.create_user(db,1,'anya',timezone='Europe/Berlin')
    db.commit()
    d.save_availability(1,'anya',[dict(days=['monday'],time=dict(start_time='18:00',end_time='22:00'))])
    assert r.get_user(db,telegram_user_id=1)['timezone']=='Europe/Berlin'

def test_overnight_schema_and_save_agree(db):
    u=r.create_user(db,1,'anya')
    r.create_interval(db,u['user_id'],1,time(23),time(1))
    db.commit()
    d.save_availability(1,'anya',[dict(days=['monday'],time=dict(start_time='23:00',end_time='01:00'))])
    assert d.get_user_intervals(1)==[dict(day=1,start_time='23:00:00',end_time='01:00:00')]

def test_cancellation_and_decline_persist(db,seeded):
    m=seeded['meetings']['M2']['meeting_id']
    u=seeded['users'][512345679]['user_id']
    r.update_meeting(db,m,status='cancelled')
    r.update_meeting_participant(db,m,u,status='declined',is_required=False)
    assert r.get_meeting(db,m)['status']=='cancelled'
    p=next(p for p in r.get_meeting_participants(db,m) if p['user_id']==u)
    assert (p['status'],p['is_required'])==('declined',False)

def test_exception_boundary_filter(db):
    u=r.create_user(db,1)
    a=datetime.fromisoformat('2026-11-24T13:00:00+03:00')
    b=datetime.fromisoformat('2026-11-24T15:00:00+03:00')
    r.create_availability_exception(db,u['user_id'],False,a,b)
    assert len(r.get_availability_exceptions(db,u['user_id'],a,b))==1
    assert r.get_availability_exceptions(db,u['user_id'],b,None)==[]
    assert r.get_availability_exceptions(db,u['user_id'],None,a)==[]

@pytest.mark.parametrize('day',['monday','ПН','1',1])
def test_normalize_day(day):
    assert d.normalize_day(day)==1
