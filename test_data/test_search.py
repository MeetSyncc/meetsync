from datetime import time
import pytest
import repository as r
from services.meeting_search import find_common_times

def setup(db,windows):
    for i,ivs in enumerate(windows):
        u=r.create_user(db,i+1,f'u{i}')
        for day,start,end in ivs:
            r.create_interval(db,u['user_id'],day,time.fromisoformat(start),time.fromisoformat(end))
    db.commit()
    return dict(participants=[f'u{i}' for i in range(len(windows))],date_start='2026-11-23',date_end='2026-11-23',time_start='00:00',time_end='23:59',duration=60)

def slot(start,end,day='2026-11-23'):
    return {'start':f'{day}T{start}:00','end':f'{day}T{end}:00'}

@pytest.mark.parametrize('windows,duration,expected',[
 ([[(1,'10:00','13:00')],[(1,'11:00','14:00')]],60,[slot('11:00','12:00'),slot('12:00','13:00')]),
 ([[(1,'10:00','11:00')],[(1,'12:00','13:00')]],30,[]),
 ([[(1,'10:00','11:00')],[(1,'11:00','12:00')]],30,[]),
 ([[(1,'10:00','12:00')],[(1,'11:00','13:00')]],60,[slot('11:00','12:00')]),
 ([[(1,'10:00','11:59')],[(1,'11:00','13:00')]],60,[]),
 ([[(1,'10:00','13:00')],[(1,'11:00','14:00')],[(1,'13:00','15:00')]],30,[]),
 ([[(1,'10:00','11:00'),(1,'12:00','13:00')],[(1,'10:30','12:30')]],60,[]),
 ([[(1,'14:00','16:00'),(1,'10:00','12:00')],[(1,'11:00','15:00')]],30,[slot('11:00','11:30'),slot('11:30','12:00'),slot('14:00','14:30'),slot('14:30','15:00')]),
],ids=[f'MS-{i:02}' for i in range(1,9)])
def test_search_boundaries(db,windows,duration,expected):
    data=setup(db,windows)
    data['duration']=duration
    assert find_common_times(data)==expected

def test_period_clipping(db):
    data=setup(db,[[(1,'13:00','17:00')],[(1,'13:30','16:30')]])
    data.update(time_start='14:00',time_end='16:00')
    assert find_common_times(data)==[slot('14:00','15:00'),slot('15:00','16:00')]

def test_dates_not_confused(db):
    data=setup(db,[[(1,'10:00','12:00')],[(2,'10:00','12:00')]])
    data['date_end']='2026-11-24'
    assert find_common_times(data)==[]

def test_multi_date(db):
    windows=[[(1,'10:00','11:00'),(2,'10:00','11:00')]]*2
    data=setup(db,windows)
    data['date_end']='2026-11-24'
    assert find_common_times(data)==[slot('10:00','11:00'),slot('10:00','11:00','2026-11-24')]

def test_midnight(db):
    data=setup(db,[[(1,'23:00','01:30')],[(2,'00:00','02:30')]])
    data.update(date_end='2026-11-24',time_start='22:00',time_end='02:00')
    assert find_common_times(data)==[slot('00:00','01:00','2026-11-24')]

def test_timezones(db):
    data=setup(db,[[(1,'18:00','22:00')],[(1,'18:00','22:00')]])
    u=r.get_user(db,telegram_user_id=2)
    r.update_user(db,u['user_id'],timezone='Europe/Berlin')
    db.commit()
    assert find_common_times(data)==[slot('20:00','21:00'),slot('21:00','22:00')]

def test_no_duplicate_slots(db):
    data=setup(db,[[(1,'10:00','12:00'),(1,'10:00','12:00')],[(1,'10:00','12:00')]])
    assert find_common_times(data)==[slot('10:00','11:00'),slot('11:00','12:00')]

@pytest.mark.parametrize('duration',[0,-10,True,30.5])
def test_invalid_duration(db,duration):
    data=setup(db,[[(1,'10:00','12:00')]])
    data['duration']=duration
    with pytest.raises((TypeError,ValueError)):
        find_common_times(data)
