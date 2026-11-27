"""Real search service, DB read boundary substituted. NOT a PostgreSQL test."""
from datetime import timedelta
import pytest
from services import meeting_search as search

@pytest.mark.parametrize('case_id',[f'E{i}' for i in range(1,13)])
def test_excel_search_service(monkeypatch,workbook,case_id):
    users={r['telegram_user_id']:r for r in workbook['users']}
    inputs={r['telegram_username']:[] for r in workbook['users']}
    for row in workbook['intervals']:
        if row['telegram_chat_id'] is None:
            inputs[users[row['telegram_user_id']]['telegram_username']].append({k:row[k] for k in ['day','start_time','end_time']})
    # Same projection as get_intervals_by_usernames SQL. Exceptions, privacy,
    # meetings and timezone are absent from that production read interface.
    monkeypatch.setattr(search,'get_intervals_by_usernames',lambda names:{name.lower():inputs.get(name.lower(),[]) for name in names})
    rows=[r for r in workbook['expected_results'] if r['case_id']==case_id]
    r=rows[0]
    data=dict(participants=[users[int(x)]['telegram_username'] for x in r['participants'].split(',')],date_start=r['search_from'].date().isoformat(),date_end=(r['search_to']-timedelta(microseconds=1)).date().isoformat(),time_start='00:00',time_end='23:59',duration=r['duration_min'])
    expected=[]
    for row in rows:
        start=row['window_start']
        if start is None: continue
        step=timedelta(minutes=row['duration_min'])
        while start+step<=row['window_end']:
            expected.append({'start':start.isoformat(),'end':(start+step).isoformat()})
            start+=step
    assert search.find_common_times(data)==sorted(expected,key=lambda x:x['start'])[:5]

@pytest.fixture
def input_data(monkeypatch):
    def load(windows,duration=60,**extra):
        data={f'u{i}':[dict(day=d,start_time=s,end_time=e) for d,s,e in ivs] for i,ivs in enumerate(windows)}
        monkeypatch.setattr(search,'get_intervals_by_usernames',lambda names:data)
        return dict(participants=list(data),date_start='2026-11-23',date_end='2026-11-23',time_start='00:00',time_end='23:59',duration=duration,**extra)
    return load

def slot(a,b,day='2026-11-23'):
    return {'start':f'{day}T{a}:00','end':f'{day}T{b}:00'}

@pytest.mark.parametrize('duration',[0,-10,True,30.5])
def test_duration_rejected(input_data,duration):
    with pytest.raises((ValueError,TypeError)):
        search.find_common_times(input_data([[(1,'10:00','12:00')]],duration))

def test_midnight_service(input_data):
    data=input_data([[(1,'23:00','01:30')],[(2,'00:00','02:30')]])
    data.update(date_end='2026-11-24',time_start='22:00',time_end='02:00')
    assert search.find_common_times(data)==[slot('00:00','01:00','2026-11-24')]

def test_duplicates_service(input_data):
    data=input_data([[(1,'10:00','12:00'),(1,'10:00','12:00')],[(1,'10:00','12:00')]])
    assert search.find_common_times(data)==[slot('10:00','11:00'),slot('11:00','12:00')]

def test_bot_search_stub_without_db(frozen,input_data):
    import asyncio
    from services import meeting
    data=input_data([[(1,'10:00','12:00')],[(1,'10:00','12:00')]])
    assert asyncio.run(meeting.find_common_times(data))==search.find_common_times(data)

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
def test_service_boundaries(input_data,windows,duration,expected):
    assert search.find_common_times(input_data(windows,duration))==expected
