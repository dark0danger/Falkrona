"""Owner controls exercise saved role history, new ideas and immutable revisions."""
from copy import deepcopy
from io import BytesIO
import json
import zipfile

import pytest
from sqlalchemy import select

from brandpilot.models import AgentRun, BrandingSetup, DesignVersion, Job, WeeklyPlan, WorkspaceAsset
from tests.integration.test_design_direction import DIRECTION
from tests.integration.test_weekly_drafting_scenarios import flow


def finished(flow):
    plan=flow.prepared_plan();path=f"{flow.base}/plans/{plan['id']}"
    entries=flow.client.post(path+'/generate-images',headers=flow.csrf,json={
        'photo_asset_id':flow.inputs['photo_asset_id'],'language':'en','provider':'chatgpt','consent':True}).json()['entries']
    for index,entry in enumerate(entries):
        direction=deepcopy(DIRECTION);direction['image_prompt']=flow.content()['posts'][index]['visual_concept']['scene']
        flow.execute(lambda *_:{'text':json.dumps(direction),'model_calls':1})
        run=f"{flow.base}/agent-runs/{entry['run_id']}"
        packet=flow.client.post(run+'/browser-packet',headers=flow.csrf,json={'provider':'chatgpt','consent':True})
        assert packet.status_code==200,packet.text
        imported=flow.client.post(run+'/browser-image',headers=flow.csrf,data={'provider':'chatgpt','nonce':packet.json()['nonce']},
            files={'file':('ad.png',flow.png((800,1000)), 'image/png')})
        assert imported.status_code==201,imported.text
    return plan,path,flow.client.get(path+'/images').json()


def test_same_bytes_uploaded_for_different_purposes_remain_distinct(flow):
    content=flow.png((500,600))
    product=flow.client.post(flow.base+'/assets',headers=flow.csrf,files={'file':('product.png',content,'image/png')}).json()
    reference=flow.client.post(flow.base+'/branding/assets/reference',headers=flow.csrf,files={'file':('ref.png',content,'image/png')}).json()
    assert product['id']!=reference['id']
    assert product['purpose']=='product' and reference['purpose']=='reference'
    repeat=flow.client.post(flow.base+'/branding/assets/reference',headers=flow.csrf,files={'file':('ref-again.png',content,'image/png')}).json()
    assert repeat['id']==reference['id']
    plan=flow.prepared_plan()
    rejected=flow.client.post(f"{flow.base}/plans/{plan['id']}/generate-images",headers=flow.csrf,json={
        'photo_asset_id':reference['id'],'provider':'chatgpt','consent':True})
    assert rejected.json()['detail']['code']=='invalid_asset'


def test_historical_logo_and_reference_are_never_product_choices(flow):
    reference=flow.client.post(flow.base+'/branding/assets/reference',headers=flow.csrf,
        files={'file':('old-reference.png',flow.png((500,600)),'image/png')}).json()
    flow.prepared_plan()
    with flow.sessions() as session,session.begin():
        asset=session.get(WorkspaceAsset,reference['id']);asset.metadata_json={}
        run=session.scalar(select(AgentRun).where(AgentRun.workspace_id==flow.workspace))
        run.checkpoint={**run.checkpoint,'visual_assets':[{'id':reference['id'],'role':'reference'}]}
    roles={asset['id']:asset['purpose'] for asset in flow.client.get(flow.base+'/assets').json()['assets']}
    assert roles[reference['id']]=='reference'
    assert roles[flow.inputs['logo_asset_id']]=='logo'
    assert roles[flow.inputs['photo_asset_id']]=='product'


def test_delete_post_undo_and_package_keep_all_original_artwork(flow):
    plan,path,state=finished(flow);entry=state['entries'][0]
    asset=entry['image_asset_id'];item=entry['item_id']
    response=flow.client.delete(path+'/posts/'+item,headers=flow.csrf)
    assert response.status_code==200,response.text
    remaining=flow.client.get(path+'/images').json()
    assert remaining['complete'] and len(remaining['entries'])==1
    current=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    assert len(current['items'])==current['strategy']['cadence']==1
    with zipfile.ZipFile(BytesIO(flow.client.get(path+'/images/package').content)) as archive:
        assert len(archive.namelist())==3
    with flow.sessions() as session:
        assert session.get(WorkspaceAsset,asset).status=='ready'
        assert session.get(DesignVersion,entry['imported_design_id']) is not None
    assert flow.client.post(path+'/posts/'+item+'/restore',headers=flow.csrf).status_code==200
    restored=flow.client.get(path+'/images').json()
    assert restored['complete'] and [post['image_asset_id'] for post in restored['entries']]==[post['image_asset_id'] for post in state['entries']]


def test_delete_last_post_cannot_make_empty_plan_publishable(flow):
    plan,path,state=finished(flow)
    for entry in state['entries']:
        assert flow.client.delete(path+'/posts/'+entry['item_id'],headers=flow.csrf).status_code==200
    assert flow.client.get(path+'/images').json()['complete'] is False
    assert flow.client.get(path+'/images/package').status_code==422
    response=flow.client.post(path+'/approve-and-schedule',headers=flow.csrf,json={
        'connection_id':'00000000-0000-0000-0000-000000000000','design_ids':[state['entries'][0]['imported_design_id']], 'facts_reviewed':True})
    assert response.status_code==409 and response.json()['detail']['code']=='plan_unapproved'


def test_delete_plan_no_old_revision_reappears_and_undo_preserves_brand(flow):
    plan,path,state=finished(flow)
    with flow.sessions() as session:brand=deepcopy(session.get(BrandingSetup,flow.workspace).answers)
    assert flow.client.delete(path,headers=flow.csrf).status_code==200
    assert flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan'] is None
    assert flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['deleted_plan_id']==plan['id']
    assert flow.client.get(path+'/images').json()['entries']==[]
    assert flow.client.post(path+'/restore',headers=flow.csrf).status_code==200
    assert flow.client.get(path+'/images').json()==state
    with flow.sessions() as session:assert session.get(BrandingSetup,flow.workspace).answers==brand


def test_deleted_design_is_hidden_in_studio_until_restored(flow):
    plan,path,state=finished(flow);entry=state['entries'][0]
    assert flow.client.delete(path+'/posts/'+entry['item_id'],headers=flow.csrf).status_code==200
    studio=path+'/items/'+entry['item_id']+'/design'
    assert flow.client.get(studio).json()['current'] is None
    assert flow.client.post(path+'/posts/'+entry['item_id']+'/restore',headers=flow.csrf).status_code==200
    assert flow.client.get(studio).json()['current']['id']==entry['imported_design_id']


def test_restore_after_multiple_deletions_keeps_original_posting_order(flow):
    plan,path,state=finished(flow)
    for entry in state['entries']:
        assert flow.client.delete(path+'/posts/'+entry['item_id'],headers=flow.csrf).status_code==200
    for entry in state['entries']:
        assert flow.client.post(path+'/posts/'+entry['item_id']+'/restore',headers=flow.csrf).status_code==200
    current=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    assert [item['id'] for item in current['items']]==[item['id'] for item in plan['items']]


def test_deleting_plan_cancels_unsent_briefs_and_late_handoff_is_rejected(flow):
    plan=flow.prepared_plan();path=f"{flow.base}/plans/{plan['id']}"
    state=flow.client.post(path+'/generate-images',headers=flow.csrf,json={
        'photo_asset_id':flow.inputs['photo_asset_id'],'provider':'chatgpt','consent':True}).json()
    assert flow.client.delete(path,headers=flow.csrf).status_code==200
    with flow.sessions() as session:
        for entry in state['entries']:
            run=session.get(AgentRun,entry['run_id']);assert run.cancel_requested and run.status=='cancelled'
            assert session.get(Job,run.job_id).status=='cancelled'
    response=flow.client.post(flow.base+'/agent-runs/'+state['entries'][0]['run_id']+'/browser-packet',headers=flow.csrf,json={'provider':'chatgpt','consent':True})
    assert response.status_code==422


def test_regenerate_one_changes_concept_and_keeps_peers_language_cta_and_history(flow):
    plan,path,state=finished(flow);first,peer=state['entries']
    original_plan=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    response=flow.client.post(path+'/posts/'+first['item_id']+'/regenerate',headers=flow.csrf,json={'design_id':first['imported_design_id']})
    assert response.status_code==200,response.text
    new_state=response.json();new=new_state['entries'][0]
    assert new_state['entries'][1]==peer and new['run_id']!=first['run_id'] and not new_state['complete']
    updated=flow.client.get(flow.base+'/plans?week_start=2026-12-28').json()['plan']
    old=original_plan['items'][0]['visual_concept'];fresh=updated['items'][0]['visual_concept']
    assert old['route']!=fresh['route']
    assert sum(old[key]!=fresh[key] for key in ('route','camera','composition'))>=2
    assert updated['strategy']['visual_identity']['cta_treatment']==original_plan['strategy']['visual_identity']['cta_treatment']
    duplicate=flow.client.post(path+'/posts/'+first['item_id']+'/regenerate',headers=flow.csrf,json={'design_id':first['imported_design_id']})
    assert duplicate.status_code==422
    direction=deepcopy(DIRECTION);direction['image_prompt']='A macro detail of the sealed bag printed texture on folded white paper with a dramatically different immersive crop.'
    flow.execute(lambda *_:{'text':json.dumps(direction),'model_calls':1})
    runpath=flow.base+'/agent-runs/'+new['run_id']
    with flow.sessions() as session:
        run=session.get(AgentRun,new['run_id'])
        assert run.status=='completed',run.last_error
        assert run.checkpoint['inputs']['language']=='en'
        assert run.checkpoint['campaign']['previous_directions']
        assert run.checkpoint['campaign']['previous_ideas'][0]==old
    packet=flow.client.post(runpath+'/browser-packet',headers=flow.csrf,json={'provider':'chatgpt','consent':True})
    assert packet.status_code==200,packet.text
    assert 'FIXED BRAND CTA:' in packet.json()['prompt']
    assert '"y": 1160' in packet.json()['prompt'] and 'Only CTA wording may change' in packet.json()['prompt']
    imported=flow.client.post(runpath+'/browser-image',headers=flow.csrf,data={'provider':'chatgpt','nonce':packet.json()['nonce']},
        files={'file':('new.png',flow.png((1080,1350)),'image/png')})
    assert imported.status_code==201,imported.text
    ready=flow.client.get(path+'/images').json()
    assert ready['complete'] and ready['entries'][1]==peer
    with flow.sessions() as session:
        assert session.get(DesignVersion,first['imported_design_id']) is not None
        assert session.get(WorkspaceAsset,first['image_asset_id']).status=='ready'


def test_regeneration_cannot_reuse_rejected_prompt_with_new_words(flow):
    plan,path,state=finished(flow);first=state['entries'][0]
    response=flow.client.post(path+'/posts/'+first['item_id']+'/regenerate',headers=flow.csrf,json={'design_id':first['imported_design_id']})
    direction=deepcopy(DIRECTION);direction['headline']='Another headline';direction['image_prompt']=flow.content()['posts'][0]['visual_concept']['scene']
    flow.execute(lambda *_:{'text':json.dumps(direction),'model_calls':1})
    run=flow.client.get(flow.base+'/agent-runs/'+response.json()['entries'][0]['run_id']).json()
    assert run['status']=='failed' and run['last_error']=='repeated_visual_direction'


@pytest.mark.parametrize('action',['delete','regenerate'])
def test_approved_plan_is_protected_from_editing(flow,action):
    plan,path,state=finished(flow)
    with flow.sessions() as session,session.begin():session.get(WeeklyPlan,plan['id']).status='approved'
    target=path+'/posts/'+state['entries'][0]['item_id']
    response=flow.client.delete(target,headers=flow.csrf) if action=='delete' else flow.client.post(target+'/regenerate',headers=flow.csrf,json={'design_id':state['entries'][0]['imported_design_id']})
    assert response.status_code==422 and response.json()['detail']['code']=='plan_scheduled'


def test_mutations_require_csrf_and_workspace_access(flow):
    plan,path,state=finished(flow)
    assert flow.client.delete(path).status_code==403
    assert flow.client.post(path+'/posts/'+state['entries'][0]['item_id']+'/regenerate',json={'design_id':state['entries'][0]['imported_design_id']}).status_code==403
    other=flow.client.post('/api/v1/workspaces',headers=flow.csrf,json={'name':'Other'}).json()['workspace_id']
    response=flow.client.delete('/api/v1/workspaces/'+other+'/plans/'+plan['id'],headers=flow.csrf)
    assert response.status_code in {404,422}
