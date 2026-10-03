from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import unittest
import zipfile

from sqlalchemy import select
from fastapi.testclient import TestClient
from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.models import WeeklyPlan, Product, PublicationApproval
from tests.integration import test_design_direction as direction_fixture


class WeekFlowTests(unittest.TestCase):
    setUp = direction_fixture.DirectionTests.setUp
    tearDown = direction_fixture.DirectionTests.tearDown
    png = staticmethod(direction_fixture.DirectionTests.png)
    execute = direction_fixture.DirectionTests.execute

    def draft(self):
        return self.client.post(f"{self.base}/plans", headers=self.csrf, json={"week_start":"2026-12-28",
            "goal":"engagement", "platforms":["facebook_pages"], "cadence":2, "public_context_confirmed":True})

    def content(self):
        return {"audience":"Coffee drinkers", "direction":"A useful week of coffee rituals.",
            "visual_identity":{"typography":"Cairo Bold 76px headlines and Cairo Regular 32px supporting text.",
                               "art_direction":"Warm natural light, tactile surfaces and the exact brand palette.",
                               "palette":["#172d2b","#ffffff"]}, "posts":[
            {"day":1,"hour":11,"platform":"facebook_pages","purpose":"education","title":"The morning cup",
             "concept":"A calm morning coffee ritual","cta":"Tell us your ritual","rationale":"Invites conversation",
             "fact_keys":["profile.brand_name"],
             "visual_concept":{"route":"human_moment","scene":"A person's hands prepare morning coffee beside a sunlit kitchen window, with the actual bag nearby.",
                 "camera":"wide_environment","composition":"asymmetric_editorial","visual_hook":"The shared ritual and hands are the focal point, with space for copy.","background_color":"#ffffff"}},
            {"day":4,"hour":17,"platform":"facebook_pages","purpose":"product","title":"Meet the coffee bag",
             "concept":"Show the actual 250g coffee bag","cta":"Discover the bag","rationale":"Introduces the confirmed product",
             "fact_keys":["profile.brand_name","product.1.name"],
             "visual_concept":{"route":"product_hero","scene":"The coffee bag stands on a sculptural folded paper platform against a clean brand-colored wall.",
                 "camera":"low_angle","composition":"central_sculptural","visual_hook":"An architectural pedestal frames the sealed bag as the sole hero.","background_color":"#172d2b"}}]}

    def prepared_plan(self):
        response=self.draft();self.assertEqual(response.status_code,202,response.text)
        self.execute(lambda *_:{"text":json.dumps(self.content()),"model_calls":1})
        run=self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()
        self.assertEqual(run['status'],'completed',run)
        return self.client.get(f"{self.base}/plans?week_start=2026-12-28").json()['plan']

    def test_gemini_drafts_the_whole_week_once_without_approvals(self):
        first=self.draft();self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(first.json()['id'],self.draft().json()['id'])
        captured=[]
        self.execute(lambda prompt,*_ :captured.append(prompt) or {"text":json.dumps(self.content()),"model_calls":1})
        self.assertEqual(len(captured),1)
        self.assertIn('250g whole beans',captured[0]);self.assertIn('Nile Coffee',captured[0])
        plan=self.client.get(f"{self.base}/plans?week_start=2026-12-28").json()['plan']
        self.assertEqual(plan['strategy']['planner'],'gemini')
        self.assertEqual([item['title'] for item in plan['items']],[p['title'] for p in self.content()['posts']])
        self.assertEqual(plan['status'],'draft');self.assertTrue(all(item['status']=='draft' for item in plan['items']))

    def test_invalid_or_stale_gemini_output_never_replaces_the_week(self):
        response=self.draft();bad=deepcopy(self.content());bad['posts'][0]['fact_keys']=['product.invented.name']
        self.execute(lambda *_:{"text":json.dumps(bad),"model_calls":1})
        run=self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()
        self.assertEqual(run['status'],'failed')
        self.assertEqual(self.client.get(f"{self.base}/plans?week_start=2026-12-28").json()['plan']['id'],self.plan_id)
        with self.sessions() as session,session.begin():session.get(Product,self.product_id).price='200'
        response=self.draft()
        with self.sessions() as session,session.begin():session.get(Product,self.product_id).price='250'
        self.execute(lambda *_:{"text":json.dumps(self.content()),"model_calls":1})
        self.assertEqual(self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()['status'],'failed')

    def test_generate_all_posts_import_replay_and_week_package(self):
        plan=self.prepared_plan();path=f"{self.base}/plans/{plan['id']}"
        body={"photo_asset_id":self.inputs['photo_asset_id'],"product_description":"A real coffee bag","language":"en","provider":"chatgpt","consent":True}
        no_consent=self.client.post(path+'/generate-images',headers=self.csrf,json={**body,"consent":False})
        self.assertEqual(no_consent.status_code,422,no_consent.text)
        response=self.client.post(path+'/generate-images',headers=self.csrf,json=body)
        self.assertEqual(response.status_code,200,response.text);entries=response.json()['entries'];self.assertEqual(len(entries),2)
        again=self.client.post(path+'/generate-images',headers=self.csrf,json=body).json()['entries']
        self.assertEqual([e['run_id'] for e in entries],[e['run_id'] for e in again])
        captured=[]; imported_posts=[]
        for index,entry in enumerate(entries):
            direction=deepcopy(direction_fixture.DIRECTION)
            direction['image_prompt']=self.content()['posts'][index]['visual_concept']['scene']
            self.execute(lambda prompt,*_:captured.append(prompt) or {"text":json.dumps(direction),"model_calls":1})
            runpath=f"{self.base}/agent-runs/{entry['run_id']}"
            packet=self.client.post(runpath+'/browser-packet',headers=self.csrf,json={"provider":"chatgpt","consent":True}).json()
            self.assertIn(self.content()['visual_identity']['typography'],packet['prompt'])
            self.assertIn(self.content()['posts'][index]['visual_concept']['scene'],packet['prompt'])
            self.assertIn('Source-photo elements to discard',packet['prompt'])
            self.assertLessEqual(len(packet['prompt']),12000)
            imported=self.client.post(runpath+'/browser-image',headers=self.csrf,data={"provider":"chatgpt","nonce":packet['nonce']},
                files={"file":('ad.png',self.png((800,1000)),"image/png")})
            self.assertEqual(imported.status_code,201,imported.text)
            imported_posts.append(imported.json())
        state=self.client.get(path+'/images').json();self.assertTrue(state['complete'],state)
        self.assertTrue(all('other_posts' in prompt and 'selected_visual_concept' in prompt for prompt in captured))
        replay=self.client.post(path+'/generate-images',headers=self.csrf,json=body).json()
        self.assertEqual([e['run_id'] for e in replay['entries']],[e['run_id'] for e in entries])
        package=self.client.get(path+'/images/package');self.assertEqual(package.status_code,200,package.text[:100])
        with zipfile.ZipFile(BytesIO(package.content)) as archive:self.assertEqual(len(archive.namelist()),5)
        updated_caption='Owner-confirmed fruit details, without invented farming claims.'
        revised=self.client.post(f"{self.base}/designs/{imported_posts[0]['id']}/revisions",headers=self.csrf,
            json={"scene":imported_posts[0]['scene'],"caption":updated_caption})
        self.assertEqual(revised.status_code,201,revised.text)
        with zipfile.ZipFile(BytesIO(self.client.get(path+'/images/package').content)) as archive:
            self.assertEqual(archive.read('post-1/caption.txt').decode(),updated_caption)
            self.assertEqual(archive.read('post-2/caption.txt').decode(),imported_posts[1]['caption'])
            self.assertEqual(len(archive.namelist()),5)
        with self.sessions() as session:self.assertEqual(len(session.scalars(select(PublicationApproval)).all()),0)

    def test_repeated_scene_with_different_headline_cannot_replace_week(self):
        response=self.draft();repeated=self.content()
        repeated['posts'][1]['visual_concept']=deepcopy(repeated['posts'][0]['visual_concept'])
        self.execute(lambda *_:{'text':json.dumps(repeated),'model_calls':1})
        run=self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['last_error'],'repeated_visual_concept')

    def test_arabic_choice_reaches_each_prompt_and_image_packet_and_is_locked_for_resume(self):
        plan=self.prepared_plan();path=f"{self.base}/plans/{plan['id']}"
        body={"photo_asset_id":self.inputs['photo_asset_id'],"product_description":"A real coffee bag",
              "language":"ar","provider":"chatgpt","consent":True}
        response=self.client.post(path+'/generate-images',headers=self.csrf,json=body)
        self.assertEqual(response.status_code,200,response.text)
        saved=self.client.get(f"{self.base}/plans?week_start=2026-12-28").json()['plan']
        self.assertEqual(saved['strategy']['generation']['config']['inputs']['language'],'ar')
        for index,entry in enumerate(response.json()['entries']):
            captured=[];direction=deepcopy(direction_fixture.DIRECTION)
            direction.update(language='ar',headline='قهوتك كل صباح',cta='اكتشف قهوتك',caption='استمتع بقهوتك المفضلة كل صباح.')
            direction['image_prompt']=self.content()['posts'][index]['visual_concept']['scene']
            self.execute(lambda prompt,*_:captured.append(prompt) or {"text":json.dumps(direction),"model_calls":1})
            self.assertIn('"language": "ar"',captured[0])
            runpath=f"{self.base}/agent-runs/{entry['run_id']}"
            self.assertEqual(self.client.get(runpath).json()['status'],'completed')
            packet=self.client.post(runpath+'/browser-packet',headers=self.csrf,json={"provider":"chatgpt","consent":True})
            self.assertEqual(packet.status_code,200,packet.text)
            self.assertIn('Exact headline: قهوتك كل صباح',packet.json()['prompt'])
            self.assertIn('Language: ar',packet.json()['prompt'])
            self.assertIn('right-to-left',packet.json()['prompt'])
        changed=self.client.post(path+'/generate-images',headers=self.csrf,json={**body,'language':'en'})
        self.assertEqual(changed.status_code,422,changed.text)
        self.assertEqual(changed.json()['detail']['code'],'generation_started')
        invalid=self.client.post(path+'/generate-images',headers=self.csrf,json={**body,'language':'fr'})
        self.assertEqual(invalid.status_code,422)

    def test_gemini_cannot_ignore_the_selected_design_language(self):
        plan=self.prepared_plan();response=self.client.post(f"{self.base}/plans/{plan['id']}/generate-images",
            headers=self.csrf,json={"photo_asset_id":self.inputs['photo_asset_id'],"language":"ar",
                                   "provider":"chatgpt","consent":True})
        self.assertEqual(response.status_code,200,response.text)
        for index,entry in enumerate(response.json()['entries']):
            direction=deepcopy(direction_fixture.DIRECTION)
            if index:direction['language']='ar' # Mislabelled English copy must also fail.
            self.execute(lambda *_:{'text':json.dumps(direction),'model_calls':1})
            run=self.client.get(f"{self.base}/agent-runs/{entry['run_id']}").json()
            self.assertEqual(run['status'],'failed')
            self.assertEqual(run['last_error'],'language_mismatch')

    def test_a_new_scene_cannot_change_the_brand_palette(self):
        response=self.draft();changed=self.content()
        changed['posts'][0]['visual_concept']['background_color']='#00ffff'
        self.execute(lambda *_:{'text':json.dumps(changed),'model_calls':1})
        run=self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()
        self.assertEqual(run['last_error'],'brand_palette_mismatch')

    def test_copy_only_prompt_variation_is_blocked_before_image_handoff(self):
        plan=self.prepared_plan();path=f"{self.base}/plans/{plan['id']}"
        entries=self.client.post(path+'/generate-images',headers=self.csrf,json={
            'photo_asset_id':self.inputs['photo_asset_id'],'provider':'chatgpt','consent':True}).json()['entries']
        first=deepcopy(direction_fixture.DIRECTION)
        first['image_prompt']='Bottle on a wooden table surrounded by fruit, leafy background. '+first['headline']+' '+first['cta']
        self.execute(lambda *_:{'text':json.dumps(first),'model_calls':1})
        changed=deepcopy(first);changed['headline']='Different words';changed['cta']='Buy today'
        changed['image_prompt']=first['image_prompt'].replace(first['headline'],changed['headline']).replace(first['cta'],changed['cta'])
        self.execute(lambda *_:{'text':json.dumps(changed),'model_calls':1})
        run=self.client.get(f"{self.base}/agent-runs/{entries[1]['run_id']}").json()
        self.assertEqual(run['last_error'],'repeated_visual_direction')
        response=self.client.post(f"{self.base}/agent-runs/{entries[1]['run_id']}/browser-packet",headers=self.csrf,
            json={'provider':'chatgpt','consent':True})
        self.assertEqual(response.status_code,422)

    def test_product_observation_is_required_before_image_handoff(self):
        plan=self.prepared_plan();entries=self.client.post(f"{self.base}/plans/{plan['id']}/generate-images",headers=self.csrf,
            json={'photo_asset_id':self.inputs['photo_asset_id'],'provider':'chatgpt','consent':True}).json()['entries']
        direction=deepcopy(direction_fixture.DIRECTION);direction.pop('product_observation')
        self.execute(lambda *_:{'text':json.dumps(direction),'model_calls':1})
        run=self.client.get(f"{self.base}/agent-runs/{entries[0]['run_id']}").json()
        self.assertEqual(run['last_error'],'product_identity_missing')

    def test_next_week_preserves_the_established_brand_treatment(self):
        first=self.prepared_plan()
        response=self.client.post(f"{self.base}/plans",headers=self.csrf,json={
            'week_start':'2027-01-04','goal':'engagement','platforms':['facebook_pages'],'cadence':2,'public_context_confirmed':True})
        self.assertEqual(response.status_code,202,response.text)
        changed=self.content();changed['visual_identity']['typography']='An unrelated serif family and type scale.'
        captured=[]
        self.execute(lambda prompt,*_:captured.append(prompt) or {'text':json.dumps(changed),'model_calls':1})
        second=self.client.get(f"{self.base}/plans?week_start=2027-01-04").json()['plan']
        self.assertEqual(second['strategy']['visual_identity'],first['strategy']['visual_identity'])
        self.assertIn(first['strategy']['visual_identity']['typography'],captured[0])

    def test_old_plan_requires_new_visual_concepts_before_generation(self):
        plan=self.prepared_plan()
        with self.sessions() as session,session.begin():
            row=session.get(WeeklyPlan,plan['id']);strategy=deepcopy(row.strategy);strategy.pop('visual_planning_version');row.strategy=strategy
        response=self.client.post(f"{self.base}/plans/{plan['id']}/generate-images",headers=self.csrf,
            json={'photo_asset_id':self.inputs['photo_asset_id'],'provider':'chatgpt','consent':True})
        self.assertEqual(response.json()['detail']['code'],'new_visual_plan_required')

    def test_foreign_product_photo_is_rejected(self):
        plan=self.prepared_plan()
        other=self.client.post('/api/v1/workspaces',headers=self.csrf,json={"name":"Other"}).json()['workspace_id']
        photo=self.client.post(f'/api/v1/workspaces/{other}/assets',headers=self.csrf,
            files={"file":('other.png',self.png((400,500)),"image/png")}).json()
        response=self.client.post(f"{self.base}/plans/{plan['id']}/generate-images",headers=self.csrf,
            json={"photo_asset_id":photo['id'],"provider":"chatgpt","consent":True})
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(response.json()['detail']['code'],'invalid_asset')

    def test_free_gemini_planner_uses_public_context_without_internal_ids(self):
        settings=replace(self.app.state.settings,runtime=RuntimeConfig(
            execution_mode=ExecutionMode.GEMINI_FREE,model_provider=ModelProvider.GEMINI))
        self.client.close();self.app=create_app(settings,engine=self.engine)
        self.client=TestClient(self.app,base_url='https://testserver')
        login=self.client.post('/api/v1/session',json={'email':'owner@example.test','password':'owner-password-long'})
        self.csrf={'X-CSRF-Token':login.json()['csrf_token']}
        response=self.draft();self.assertEqual(response.status_code,202,response.text)
        captured=[]
        self.execute(lambda prompt,*_:captured.append(prompt) or {'text':json.dumps(self.content()),'model_calls':1})
        self.assertNotIn(self.product_id,captured[0]);self.assertNotIn('2026-12-28',captured[0])
        self.assertEqual(self.client.get(f"{self.base}/agent-runs/{response.json()['id']}").json()['status'],'completed')

    def test_owner_retry_reuses_pending_request_and_preserves_completed_prompts(self):
        failed=self.draft();bad=deepcopy(self.content());bad['posts'][0]['fact_keys']=['invented']
        self.execute(lambda *_:{'text':json.dumps(bad),'model_calls':1})
        retried=self.draft();self.assertNotEqual(failed.json()['id'],retried.json()['id'])
        self.assertEqual(retried.json()['id'],self.draft().json()['id'])
        self.execute(lambda *_:{'text':json.dumps(self.content()),'model_calls':1})
        plan=self.client.get(f'{self.base}/plans?week_start=2026-12-28').json()['plan']
        path=f"{self.base}/plans/{plan['id']}/generate-images"
        body={'photo_asset_id':self.inputs['photo_asset_id'],'provider':'chatgpt','consent':True}
        entries=self.client.post(path,headers=self.csrf,json=body).json()['entries']
        self.execute(lambda *_:{'text':'invalid output','model_calls':1})
        self.execute(lambda *_:{'text':json.dumps(direction_fixture.DIRECTION),'model_calls':1})
        retried_entries=self.client.post(path,headers=self.csrf,json=body).json()['entries']
        self.assertNotEqual(entries[0]['run_id'],retried_entries[0]['run_id'])
        self.assertEqual(entries[1]['run_id'],retried_entries[1]['run_id'])
        replay=self.client.post(path,headers=self.csrf,json=body).json()['entries']
        self.assertEqual([entry['run_id'] for entry in replay],[entry['run_id'] for entry in retried_entries])
