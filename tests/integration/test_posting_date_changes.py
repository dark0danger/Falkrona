from datetime import date, datetime, timezone
from io import BytesIO
import json
from unittest.mock import patch
import zipfile

import pytest

from brandpilot.models import WeeklyPlan
from tests.integration.test_owner_design_controls import finished
from tests.integration.test_weekly_drafting_scenarios import flow


def change(flow,path,entry,value,headers=None):
    return flow.client.patch(path+'/posts/'+entry['item_id']+'/schedule',headers=headers or flow.csrf,
        json={'scheduled_at':value,'previous_scheduled_at':entry['scheduled_at']})


def test_date_change_updates_review_and_package_preserving_artwork_and_other_posts(flow):
    plan,path,state=finished(flow);entry=state['entries'][0]
    response=change(flow,path,entry,'2026-12-30T15:30')
    assert response.status_code==200,response.text
    changed=response.json()['entries'][0]
    assert changed['scheduled_at']=='2026-12-30T13:30:00+00:00'
    for field in ('run_id','imported_design_id','image_asset_id','caption'):
        assert changed[field]==entry[field]
    assert response.json()['entries'][1]==state['entries'][1]
    with zipfile.ZipFile(BytesIO(flow.client.get(path+'/images/package').content)) as archive:
        assert json.loads(archive.read('schedule.json'))[0]['scheduled_at']==changed['scheduled_at']
    saved=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    assert next(item for item in saved['items'] if item['id']==entry['item_id'])['scheduled_at']==changed['scheduled_at']
    duplicate=change(flow,path,entry,'2026-12-31T15:30')
    assert duplicate.status_code==422 and duplicate.json()['detail']['code']=='schedule_stale'


@pytest.mark.parametrize('value,code',[
    ('2020-01-01T12:00','missed_schedule'),
    ('2027-01-04T12:00','outside_week'),
    ('2027-01-01T17:00','schedule_conflict'),
    ('2026-12-30T25:30','invalid_schedule'),
])
def test_invalid_date_preserves_the_saved_week(flow,value,code):
    plan,path,state=finished(flow)
    response=change(flow,path,state['entries'][0],value)
    assert response.status_code==422 and response.json()['detail']['code']==code,response.text
    assert flow.client.get(path+'/images').json()==state


@pytest.mark.parametrize('week,value,code',[
    (date(2026,4,20),'2026-04-24T00:30','nonexistent_schedule'),
    (date(2026,10,26),'2026-10-29T23:30','ambiguous_schedule'),
])
def test_clock_change_hours_need_a_different_time(flow,week,value,code):
    plan,path,state=finished(flow)
    with flow.sessions() as session,session.begin():session.get(WeeklyPlan,plan['id']).week_start=week
    with patch('brandpilot.publication.utc_now',return_value=datetime(2026,4,19,tzinfo=timezone.utc)):
        response=change(flow,path,state['entries'][0],value)
    assert response.status_code==422 and response.json()['detail']['code']==code,response.text


def test_approved_plan_posting_times_cannot_be_changed(flow):
    plan,path,state=finished(flow)
    with flow.sessions() as session,session.begin():session.get(WeeklyPlan,plan['id']).status='approved'
    response=change(flow,path,state['entries'][0],'2026-12-30T15:30')
    assert response.status_code==422 and response.json()['detail']['code']=='plan_scheduled'


def test_date_edit_requires_csrf_and_matching_workspace(flow):
    plan,path,state=finished(flow);entry=state['entries'][0]
    assert change(flow,path,entry,'2026-12-30T15:30',headers={'X-CSRF-Token':'invalid'}).status_code==403
    other=flow.client.post('/api/v1/workspaces',headers=flow.csrf,json={'name':'Other'}).json()['workspace_id']
    response=change(flow,path.replace(flow.workspace,other),entry,'2026-12-30T15:30')
    assert response.status_code in {404,422}
