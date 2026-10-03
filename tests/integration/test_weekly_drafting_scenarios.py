"""Owner draft scenarios use isolated databases and a deterministic Gemini transport."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest

from brandpilot.models import AgentRun, Product, WeeklyPlan
from tests.integration import test_weekly_generation as week_fixture


@pytest.fixture
def flow():
    value = week_fixture.WeekFlowTests()
    value.setUp()
    try:
        yield value
    finally:
        value.tearDown()


def start(flow, **choices):
    return flow.client.post(flow.base+'/plans', headers=flow.csrf, json={
        'week_start':'2026-12-28', 'goal':'sales', 'platforms':['facebook_pages'],
        'cadence':3, 'language':'en', 'public_context_confirmed':True, **choices})


def make_posts(flow, count):
    draft=flow.content()
    routes=['product_hero','human_moment','ingredient_story','detail_study','graphic_story']
    cameras=['eye_level','wide_environment','overhead','close_up','low_angle']
    layouts=['central_sculptural','asymmetric_editorial','overhead_grid','immersive_crop','diagonal_motion']
    scenes=['A sealed bag on sculptural paper with an architectural silhouette.',
            'Friends share a drink by a sunny window with generous editorial space.',
            'An overhead grid of ingredient origins tells a harvesting story.',
            'A macro view of package texture explores its finely printed details.',
            'Abstract layered shapes frame the package in a dynamic graphic narrative.']
    draft['posts']=[]
    for index in range(count):
        post=deepcopy(flow.content()['posts'][0])
        post.update(day=index+1, hour=11, title=f'Post {index+1}')
        post['visual_concept'].update(route=routes[index], camera=cameras[index], composition=layouts[index],scene=scenes[index])
        draft['posts'].append(post)
    return draft


@pytest.mark.parametrize('language',['ar','en'])
@pytest.mark.parametrize('count',[1,2,3,4,5])
def test_every_post_count_and_language_without_catalog_or_offer(flow, language, count):
    with flow.sessions() as session, session.begin():
        session.delete(session.get(Product,flow.product_id))
    response=start(flow,language=language,cadence=count)
    assert response.status_code==202,response.text
    with flow.sessions() as session:
        run=session.get(AgentRun,response.json()['id'])
        context=json.loads(run.redacted_prompt.split('Business context:\n')[-1])
        schema=run.checkpoint['response_schema']
        assert context['allowed_purposes']==['education','conversation']
        assert context['language']==language
        assert schema['properties']['posts']['minItems']==count
        assert schema['properties']['posts']['maxItems']==count
        assert schema['$defs']['WeeklyPost']['properties']['purpose']['enum']==['education','conversation']
        assert schema['$defs']['WeeklyPost']['properties']['platform']['enum']==['facebook_pages']
        assert set(schema['$defs']['WeeklyPost']['properties']['fact_keys']['items']['enum'])==set(context['facts'])
    draft=make_posts(flow,count)
    if language=='ar':
        draft['direction']='أفكار متنوعة عن القهوة لهذا الأسبوع'
        for post in draft['posts']:
            post.update(title='قهوتك المفضلة',concept='لحظة قهوة جميلة في الصباح',cta='شاركنا رأيك',rationale='محادثة عن عادات القهوة')
    flow.execute(lambda *_:{'text':json.dumps(draft), 'model_calls':1})
    result=flow.client.get(flow.base+'/agent-runs/'+response.json()['id']).json()
    assert result['status']=='completed',result
    plan=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    assert len(plan['items'])==count
    assert plan['strategy']['language']==language


@pytest.mark.parametrize('case,expected',[
    ('count','wrong_post_count'),('platform','unsupported_platform'),
    ('slot','duplicate_posting_slot'),('fact','unconfirmed_fact'),
    ('product','missing_product_fact'),('offer','missing_offer_fact'),
    ('palette','brand_palette_mismatch'),('repetition','repeated_visual_concept'),
    ('past','missed_schedule'),('language','language_mismatch'),('malformed','invalid_direction')])
def test_invalid_draft_preserves_saved_plan_and_explains_rejection(flow,case,expected):
    with patch('brandpilot.weekly_planning.utc_now',return_value=datetime(2026,12,28,8,tzinfo=timezone.utc)):
        response=start(flow,cadence=2)
    draft=flow.content()
    if case=='count':draft['posts'].pop()
    if case=='platform':draft['posts'][0]['platform']='instagram'
    if case=='slot':draft['posts'][1].update(day=1,hour=11)
    if case=='fact':draft['posts'][0]['fact_keys']=['made.up']
    if case=='product':draft['posts'][0]['purpose']='product'
    if case=='offer':draft['posts'][0]['purpose']='offer'
    if case=='palette':draft['visual_identity']['palette']=['#ff0000']
    if case=='repetition':draft['posts'][1]['visual_concept']=deepcopy(draft['posts'][0]['visual_concept'])
    if case=='past':draft['posts'][0].update(day=0,hour=8)
    if case=='language':draft['posts'][0]['cta']='شاركنا رأيك'
    text='not JSON' if case=='malformed' else json.dumps(draft)
    flow.execute(lambda *_:{'text':text,'model_calls':1})
    run=flow.client.get(flow.base+'/agent-runs/'+response.json()['id']).json()
    assert run['status']=='failed',run
    assert run['last_error']==expected,run
    if case!='malformed':assert run['output']['failure_message']
    assert flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']['id']==flow.plan_id


def test_late_week_three_posts_have_future_slots_and_can_share_a_day(flow):
    with patch('brandpilot.weekly_planning.utc_now',return_value=datetime(2026,12,31,21,30,tzinfo=timezone.utc)):
        response=start(flow,week_start='2026-12-28')
    assert response.status_code==202,response.text
    with flow.sessions() as session:
        run=session.get(AgentRun,response.json()['id'])
        context=json.loads(run.redacted_prompt.split('Business context:\n')[-1])
        assert all(slot['day']>=4 for slot in context['posting_slots'])
    draft=make_posts(flow,3)
    for index,post in enumerate(draft['posts']):post.update(day=5,hour=10+index)
    flow.execute(lambda *_:{'text':json.dumps(draft),'model_calls':1})
    assert flow.client.get(flow.base+'/agent-runs/'+response.json()['id']).json()['status']=='completed'


@pytest.mark.parametrize('choices',[{'language':'fr'},{'cadence':0},{'cadence':6},{'platforms':[]},{'public_context_confirmed':False}])
def test_invalid_owner_choices_do_not_enqueue(flow,choices):
    assert start(flow,**choices).status_code==422


def test_finished_week_rejected_before_model_call(flow):
    with patch('brandpilot.weekly_planning.utc_now',return_value=datetime(2027,1,3,21,30,tzinfo=timezone.utc)):
        response=start(flow)
    assert response.status_code==422,response.text
    assert response.json()['detail']['code']=='week_finished'


def test_no_consent_or_csrf_cannot_draft(flow):
    response=flow.client.post(flow.base+'/plans',json={'week_start':'2026-12-28','goal':'sales','platforms':['facebook_pages']})
    assert response.status_code==403
