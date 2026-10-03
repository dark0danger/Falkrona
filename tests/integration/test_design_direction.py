from dataclasses import replace
from io import BytesIO
import json
import base64
import unittest

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.creative_worker import CreativeDirectionHandler, HermesCreativeExecutor
from brandpilot.database import build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.models import AgentRun, Product, WeeklyPlan
from brandpilot.worker import Worker
from tests.integration import test_phase8_studio_api as studio_fixture
from tests.integration.branding_fixture import complete_branding


DIRECTION = {"design_idea": "A natural product scene with upper text space", "image_prompt": "Preserve the real bottle and label. Soft natural light; complete ad with exact logo, headline and CTA.",
             "layout": "editorial", "headline_align": "start", "missing_information": [],
             "headline": "Fresh coffee. Good company.", "cta": "Find your favorite", "caption": "Discover our coffee bag.", "language": "en",
             "product_observation": {"identity": "The real coffee bag, sealed shape and printed label.",
                 "source_scene_to_discard": ["Original backdrop and staging", "Original camera framing"]}}


class DirectionTests(unittest.TestCase):
    tearDown = studio_fixture.StudioApiTests.tearDown
    png = staticmethod(studio_fixture.StudioApiTests.png)
    def setUp(self):
        studio_fixture.StudioApiTests.setUp(self)
        settings = replace(self.client.app.state.settings,
            runtime=RuntimeConfig(execution_mode=ExecutionMode.PAID_OPT_IN, model_provider=ModelProvider.GEMINI),
            gemini_model="fixture-model")
        self.client.close()
        self.app = create_app(settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.first = self.client.post(self.design_path, headers=self.csrf).json()
        image = Image.new("RGBA", (120, 80), "white")
        image.paste("#172d2b", (0, 0, 60, 80))
        image.putpixel((119, 79), (0, 0, 0, 0))
        buffer = BytesIO(); image.save(buffer, "PNG")
        logo = self.client.post(f"{self.base}/branding/assets/logo", headers=self.csrf,
            files={"file": ("logo.png", buffer.getvalue(), "image/png")}).json()
        complete_branding(self.client, self.base, self.csrf, logo=logo["id"])
        photo = self.client.post(f"{self.base}/assets", headers=self.csrf,
            files={"file": ("photo.png", self.png((400, 500)), "image/png")}).json()
        self.inputs = {"logo_asset_id": logo["id"], "photo_asset_id": photo["id"], "language": "auto",
                       "product_image_confirmed": True, "logo_includes_name": False, "product_description": "A real coffee bag"}
        self.sessions = build_session_factory(self.engine)
        with self.sessions() as session, session.begin():
            product = Product(workspace_id=self.workspace, sku="coffee", name="Coffee bag", description="250g whole beans",
                              price="180", currency="EGP", availability="available")
            session.add(product); session.flush(); self.product_id = product.id
            plan = session.get(WeeklyPlan, self.plan_id)
            items = json.loads(json.dumps(plan.items))
            items[0]["factual_refs"].append({"kind": "product", "id": product.id, "field": "name", "value": product.name})
            plan.items = items
        self.path = f"{self.base}/designs/{self.first['id']}/direction"

    def execute(self, executor, scene_executor=None):
        if scene_executor is None:
            from brandpilot.local_scene import LocalSceneExecutor
            def fixture_segmenter(image, points):
                mask = Image.new("L", image.size)
                ImageDraw.Draw(mask).ellipse((image.width * .3, image.height * .1, image.width * .7, image.height * .9), fill=255)
                return mask
            scene_executor = LocalSceneExecutor(fixture_segmenter)
        store = JobStore(self.sessions, workspace_id=self.workspace)
        handler = CreativeDirectionHandler(self.sessions, store, self.app.state.phase4, self.app.state.settings.runtime, executor, scene_executor)
        worker = Worker("creative-test", store, self.app.state.storage, creative_handler=handler)
        self.assertTrue(worker.process_one())

    def test_context_worker_composition_export_metadata_and_isolation(self):
        self.assertEqual(self.client.post(self.path, json=self.inputs).status_code, 403)
        response = self.client.post(self.path, headers=self.csrf, json=self.inputs)
        self.assertEqual(response.status_code, 202, response.text)
        run = response.json()
        repeated = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        self.assertEqual(run["id"], repeated["id"])
        captured = []
        def executor(prompt, model, progress):
            progress(); captured.append(prompt)
            return {"text": json.dumps(DIRECTION), "model_calls": 1, "usage": {"input_tokens": 800, "output_tokens": 100}}
        self.execute(executor)
        self.assertIn("250g whole beans", captured[0]); self.assertIn('"price": "180"', captured[0])
        self.assertIn("Nile Coffee", captured[0]); self.assertIn("logo_palette", captured[0])
        finished = self.client.get(f"{self.base}/agent-runs/{run['id']}").json()
        self.assertEqual(finished["status"], "completed", finished)
        packet = self.client.post(f"{self.base}/agent-runs/{run['id']}/browser-packet", headers=self.csrf,
            json={"provider": "gemini", "consent": True}).json()
        self.assertEqual([a["role"] for a in packet["attachments"]], ["logo", "product"])
        self.assertIn("product identity ONLY", packet["prompt"])
        self.assertIn("A generic drink or serving glass must not replace it", packet["prompt"])
        self.assertNotIn("generated_asset_id", finished["output"])
        regen = self.client.post(f"{self.base}/agent-runs/{run['id']}/browser-image", headers=self.csrf,
            data={"provider": "gemini", "nonce": packet["nonce"]},
            files={"file": ("generated.png", self.png((800, 1000)), "image/png")})
        self.assertEqual(regen.status_code, 201, regen.text)
        self.assertEqual(regen.json()["creative_direction"]["image_prompt"], DIRECTION["image_prompt"])
        self.assertEqual(regen.json()["scene"]["layout"], "editorial")
        self.assertEqual(regen.json()["caption"], DIRECTION["caption"])
        layers = {layer["role"]: layer for layer in regen.json()["scene"]["slides"][0]["layers"]}
        self.assertEqual(layers["headline"]["text"], "")
        self.assertNotIn("logo", layers)  # Complete ad must receive no duplicate overlays.
        self.assertNotEqual(layers["photo"]["asset_id"], self.inputs["photo_asset_id"])
        self.assertEqual(regen.json()["creative_direction"]["product_asset_id"], self.inputs["photo_asset_id"])
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"}).json()["workspace_id"]
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{other}/agent-runs/{run['id']}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/workspaces/{other}/agent-runs/{run['id']}/cancel", headers=self.csrf).status_code, 404)

    def test_price_change_invalidates_completed_direction(self):
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        self.execute(lambda *_: {"text": json.dumps(DIRECTION), "model_calls": 1})
        with self.sessions() as session, session.begin():
            session.get(Product, self.product_id).price = "200"
        response = self.client.post(f"{self.base}/agent-runs/{run['id']}/browser-packet", headers=self.csrf,
                                    json={"provider": "gemini", "consent": True})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "direction_stale")

    def test_planner_never_calls_local_renderer_or_resends(self):
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        calls = []
        def forbidden_local(*args):
            self.fail("Local rendering must never run")
        self.execute(lambda *_: calls.append(True) or {"text": json.dumps(DIRECTION), "model_calls": 1}, forbidden_local)
        saved = self.client.get(f"{self.base}/agent-runs/{run['id']}").json()
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["checkpoint"]["stage"], "awaiting_image_app")
        store = JobStore(self.sessions, workspace_id=self.workspace)
        self.assertFalse(Worker("replacement", store, self.app.state.storage).process_one())
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.client.get(self.design_path).json()["current"]["id"], self.first["id"])

    def test_live_regeneration_cannot_bypass_scene_generation(self):
        attempt = self.client.post(f"{self.base}/designs/{self.first['id']}/regenerate", headers=self.csrf, json=self.inputs)
        self.assertEqual(attempt.status_code, 422)
        self.assertEqual(attempt.json()["detail"]["code"], "generated_scene_required")

    def prepared_packet(self):
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        self.execute(lambda *_: {"text": json.dumps(DIRECTION), "model_calls": 1})
        path = f"{self.base}/agent-runs/{run['id']}"
        self.assertEqual(self.client.post(path + "/browser-packet", headers=self.csrf,
            json={"provider": "gemini", "consent": False}).status_code, 422)
        packet = self.client.post(path + "/browser-packet", headers=self.csrf,
            json={"provider": "gemini", "consent": True}).json()
        return run, path, packet

    def test_import_consent_binding_validation_and_replay(self):
        run, path, packet = self.prepared_packet()
        data = {"provider": "gemini", "nonce": packet["nonce"]}
        files = {"file": ("ad.png", self.png((800, 1000)), "image/png")}
        self.assertEqual(self.client.post(path + "/browser-image", data=data, files=files).status_code, 403)
        for override in ({"nonce": "wrong"}, {"provider": "chatgpt"}):
            response = self.client.post(path + "/browser-image", headers=self.csrf, data={**data, **override}, files=files)
            self.assertEqual(response.json()["detail"]["code"], "invalid_handoff")
        bad = self.client.post(path + "/browser-image", headers=self.csrf, data=data,
            files={"file": ("bad.png", self.png((800, 800)), "image/png")})
        self.assertEqual(bad.json()["detail"]["code"], "invalid_image")
        first = self.client.post(path + "/browser-image", headers=self.csrf, data=data, files=files)
        self.assertEqual(first.status_code, 201, first.text)
        duplicate = self.client.post(path + "/browser-image", headers=self.csrf, data=data, files=files)
        self.assertEqual(first.json()["id"], duplicate.json()["id"])
        changed = self.client.post(path + "/browser-image", headers=self.csrf, data=data,
            files={"file": ("other.png", self.png((1080, 1350)), "image/png")})
        self.assertEqual(changed.json()["detail"]["code"], "image_already_imported")
        download = self.client.get("/api/v1/browser-helper")
        self.assertEqual(download.status_code, 200)
        import zipfile
        with zipfile.ZipFile(BytesIO(download.content)) as helper:
            manifest = json.loads(helper.read("manifest.json"))
            self.assertEqual(manifest["version"], "0.1.5")
            self.assertIn("provider-dom.js", helper.namelist())
            self.assertNotIn("cookies", manifest["permissions"])
            self.assertNotIn("host_permissions", manifest)

    def test_expired_stale_and_cross_workspace_imports_are_rejected(self):
        from datetime import datetime, timedelta, timezone
        run, path, packet = self.prepared_packet()
        data = {"provider": "gemini", "nonce": packet["nonce"]}
        files = {"file": ("ad.png", self.png((800, 1000)), "image/png")}
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "Other"}).json()["workspace_id"]
        cross = self.client.post(f"/api/v1/workspaces/{other}/agent-runs/{run['id']}/browser-image",
            headers=self.csrf, data=data, files=files)
        self.assertEqual(cross.json()["detail"]["code"], "direction_unavailable")
        with self.sessions() as session, session.begin():
            row = session.get(AgentRun, run["id"])
            row.checkpoint = {**row.checkpoint, "browser_handoff": {**row.checkpoint["browser_handoff"],
                "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}}
        expired = self.client.post(path + "/browser-image", headers=self.csrf, data=data, files=files)
        self.assertEqual(expired.json()["detail"]["code"], "handoff_expired")
        reopened = self.client.post(path + "/browser-packet", headers=self.csrf,
            json={"provider": "gemini", "consent": True}).json()
        with self.sessions() as session, session.begin():
            session.get(Product, self.product_id).price = "210"
        stale = self.client.post(path + "/browser-image", headers=self.csrf,
            data={**data, "nonce": reopened["nonce"]}, files=files)
        self.assertEqual(stale.json()["detail"]["code"], "direction_stale")
        self.assertEqual(self.client.get(self.design_path).json()["current"]["id"], self.first["id"])

    def test_browser_direction_needs_only_one_gemini_call(self):
        self.app.state.phase4._max_model_calls = 1
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        self.execute(lambda *_: {"text": json.dumps(DIRECTION), "model_calls": 1})
        saved = self.client.get(f"{self.base}/agent-runs/{run['id']}").json()
        self.assertEqual(saved["status"], "completed", saved)
        self.assertEqual(saved["output"]["image_api_calls"], 0)

    def test_uploaded_reference_enters_context_and_changes_invalidate_direction(self):
        from PIL.PngImagePlugin import PngInfo
        reference_image = Image.new("RGBA", (900, 700), "orange")
        metadata = PngInfo(); metadata.add_text("Owner_note", "Private metadata must stay local")
        encoded = BytesIO(); reference_image.save(encoded, "PNG", pnginfo=metadata)
        reference = self.client.post(f"{self.base}/branding/assets/reference", headers=self.csrf,
            files={"file": ("example.png", encoded.getvalue(), "image/png")}).json()
        complete_branding(self.client, self.base, self.csrf, logo=self.inputs["logo_asset_id"], reference=reference["id"])
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        captured = []
        visual_inputs = []
        class Executor(HermesCreativeExecutor):
            def __call__(self, prompt, model, progress, schema=None, images=None):
                progress(); captured.append(prompt); visual_inputs.extend(images or [])
                return {"text": json.dumps(DIRECTION), "model_calls": 1}
        self.execute(Executor(api_key="fixture"))
        self.assertIn('"design_reference"', captured[0])
        self.assertIn('"style": "Clean and simple"', captured[0])
        self.assertEqual({image["role"] for image in visual_inputs}, {"logo", "product", "reference"})
        self.assertTrue(all(image["data_url"].startswith("data:image/png;base64,") for image in visual_inputs))
        for image in visual_inputs:
            with Image.open(BytesIO(base64.b64decode(image["data_url"].split(",", 1)[1]))) as preview:
                self.assertLessEqual(max(preview.size), 512)
                self.assertNotIn("Owner_note", preview.info)
        another = self.client.post(f"{self.base}/branding/assets/reference", headers=self.csrf,
            files={"file": ("other-example.png", self.png((120, 150)), "image/png")}).json()
        complete_branding(self.client, self.base, self.csrf, logo=self.inputs["logo_asset_id"], reference=another["id"])
        rejected = self.client.post(f"{self.base}/agent-runs/{run['id']}/browser-packet", headers=self.csrf,
            json={"provider": "gemini", "consent": True})
        self.assertEqual(rejected.json()["detail"]["code"], "direction_stale")

    def test_budget_or_malformed_output_never_promotes_a_design(self):
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        calls = []
        self.execute(lambda *_: calls.append(True) or {"text": '{"publish":true}', "model_calls": 1})
        result = self.client.get(f"{self.base}/agent-runs/{run['id']}").json()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.client.get(self.design_path).json()["current"]["id"], self.first["id"])
        self.assertEqual(len(calls), 1)
        self.inputs["product_description"] = "A new brief"
        self.app.state.phase4._max_input_tokens = 1
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        self.execute(lambda *_: calls.append(True))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.client.get(f"{self.base}/agent-runs/{run['id']}").json()["last_error"], "quota_exhausted")

    def test_free_mode_blocks_private_context_and_requires_public_attestation(self):
        # Reconfigure both the endpoint's admission service and worker policy via a new app.
        settings = replace(self.app.state.settings, runtime=RuntimeConfig(
            execution_mode=ExecutionMode.GEMINI_FREE, model_provider=ModelProvider.GEMINI))
        self.client.close(); self.app = create_app(settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        no_attestation = self.client.post(self.path, headers=self.csrf, json=self.inputs)
        self.assertEqual(no_attestation.json()["detail"]["code"], "public_context_required")
        private = self.client.post(self.path, headers=self.csrf,
            json={**self.inputs, "public_context_confirmed": True, "product_description": "Customer email: private@example.test"})
        self.assertEqual(private.status_code, 422)
        self.assertIn("Private", private.json()["detail"]["message"])
        public = self.client.post(self.path, headers=self.csrf, json={**self.inputs, "public_context_confirmed": True})
        self.assertEqual(public.status_code, 202, public.text)

    def test_cancelled_or_expired_attempt_is_not_resent_and_explicit_retry_is_new(self):
        from datetime import datetime, timedelta, timezone
        run = self.client.post(self.path, headers=self.csrf, json=self.inputs).json()
        store = JobStore(self.sessions, workspace_id=self.workspace, lease_seconds=1)
        claimed = store.claim_next("terminated-worker")
        self.assertIsNotNone(claimed)
        self.assertIsNone(store.claim_next("replacement-worker", now=datetime.now(timezone.utc) + timedelta(seconds=3)))
        self.assertEqual(self.client.get(f"{self.base}/agent-runs/{run['id']}").json()["status"], "failed")
        retry = self.client.post(self.path, headers=self.csrf, json={**self.inputs, "retry_failed": True}).json()
        self.assertNotEqual(retry["id"], run["id"])
        self.assertEqual(self.client.post(f"{self.base}/agent-runs/{retry['id']}/cancel", headers=self.csrf).json()["status"], "cancelled")
        calls = []
        worker = Worker("after-cancel", store, self.app.state.storage, creative_handler=CreativeDirectionHandler(
            self.sessions, store, self.app.state.phase4, self.app.state.settings.runtime, lambda *_: calls.append(True)))
        self.assertFalse(worker.process_one())
        self.assertEqual(calls, [])
