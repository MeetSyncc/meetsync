from datetime import timedelta
import pytest
from services.meeting_search import find_common_times

@pytest.mark.parametrize('case_id',[f'E{i}' for i in range(1,13)])
def test_excel_slots(db,seeded,workbook,case_id):
    rows=[r for r in workbook['expected_results'] if r['case_id']==case_id]
    r=rows[0]
    names=[seeded['users'][int(x)]['telegram_username'] for x in r['participants'].split(',')]
    data=dict(participants=names,date_start=r['search_from'].date().isoformat(),date_end=(r['search_to']-timedelta(microseconds=1)).date().isoformat(),time_start='00:00',time_end='23:59',duration=r['duration_min'])
    # Adapt the documented expected windows to this service's slot contract.
    # Never merge actual slots into windows: that would conceal holes or extras.
    expected=[]
    for row in rows:
        start=row['window_start']
        if start is None: continue
        step=timedelta(minutes=row['duration_min'])
        while start+step<=row['window_end']:
            expected.append({'start':start.isoformat(),'end':(start+step).isoformat()})
            start+=step
    expected=sorted(expected,key=lambda x:x['start'])[:5]
    assert find_common_times(data)==expected
