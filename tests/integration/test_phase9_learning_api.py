from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine, build_session_factory, set_workspace_context
from brandpilot.learning import applicable_preferences
from brandpilot.phase4 import Phase4Service
from brandpilot.settings import AppSettings
from tests.integration.branding_fixture import complete_branding


class LearningApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'learning.db'}")
        Base.metadata.create_all(self.engine)
        settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:", storage_root=root / "storage",
            runtime=RuntimeConfig(execution_mode=ExecutionMode.OFFLINE_TEST, model_provider=ModelProvider.NONE),
            app_secret_key=b"a" * 32, credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
        )
        self.client = TestClient(create_app(settings, engine=self.engine), base_url="https://testserver")
        setup = self.client.post("/api/v1/setup/owner", headers={"X-Setup-Token": settings.owner_setup_token},
                                 json={"email": "owner@example.test", "password": "owner-password-long", "workspace_name": "A"})
        self.assertEqual(setup.status_code, 201, setup.text)
        self.workspace = setup.json()["workspace_id"]
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.base = f"/api/v1/workspaces/{self.workspace}"
        proposal = self.client.post(f"{self.base}/brand/proposals", headers=self.csrf,
                                    json={"fields": {"brand_name": "TepeS", "category": "juice"}})
        self.client.post(f"{self.base}/brand/versions/{proposal.json()['version']}/confirm", headers=self.csrf)
        complete_branding(self.client, self.base, self.csrf)
        plan = self.plan("2026-12-28", ["facebook_pages", "instagram"])
        self.plan_id = plan["id"]
        self.items = plan["items"]
        self.design = self.client.post(
            f"{self.base}/plans/{self.plan_id}/items/{self.items[0]['id']}/design", headers=self.csrf).json()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def plan(self, week: str, platforms: list[str]) -> dict:
        response = self.client.post(f"{self.base}/plans", headers=self.csrf, json={
            "week_start": week, "goal": "awareness", "platforms": platforms, "cadence": 2})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def submit(self, *, scope="future", category="layout", kind="preference",
               instruction="Keep the product centered", design_id=None) -> dict:
        response = self.client.post(f"{self.base}/designs/{design_id or self.design['id']}/feedback",
                                    headers=self.csrf, json={"original_text": "Please fix this design",
                                                             "interpretation": instruction, "category": category,
                                                             "kind": kind, "scope": scope})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def approve(self, feedback: dict, supersedes_id=None):
        return self.client.post(f"{self.base}/feedback/{feedback['id']}/approve", headers=self.csrf,
                                json={"supersedes_id": supersedes_id})

    def rules(self, *, platform=None, campaign=None, post=None):
        sessions = build_session_factory(self.engine)
        with sessions() as session, session.begin():
            set_workspace_context(session, self.workspace)
            return applicable_preferences(session, self.workspace, platform=platform,
                                          campaign_key=campaign, post_key=post)

    def test_feedback_is_scoped_reviewed_versioned_and_reversible(self):
        self.assertEqual(self.client.post(f"{self.base}/designs/{self.design['id']}/feedback",
                                          json={"original_text": "x", "interpretation": "y",
                                                "category": "layout", "scope": "future"}).status_code, 403)
        local = self.submit(scope="post", instruction="Move this label once")
        self.assertEqual(local["status"], "local_only")
        self.assertEqual(self.approve(local).status_code, 409)
        self.assertFalse(self.rules(post=self.items[0]["id"]))
        fact = self.submit(kind="fact", category="copy", instruction="Claim the new offer")
        hypothesis = self.submit(kind="hypothesis", category="tone", instruction="This post may convert")
        self.assertEqual(self.approve(fact).status_code, 422)
        self.assertEqual(self.approve(hypothesis).status_code, 422)
        self.assertEqual(self.client.post(f"{self.base}/feedback/{hypothesis['id']}/reject",
                                          headers=self.csrf).json()["status"], "rejected")

        global_note = self.submit(instruction="Use a centered product")
        self.assertFalse(self.rules())
        global_rule = self.approve(global_note)
        self.assertEqual(global_rule.status_code, 200, global_rule.text)
        global_id = global_rule.json()["id"]
        platform_note = self.submit(scope="platform", instruction="Use an edge-aligned product")
        platform_rule = self.approve(platform_note).json()
        campaign_note = self.submit(scope="campaign", instruction="Use a close product crop")
        campaign_rule = self.approve(campaign_note).json()

        campaign = "2026-12-28"
        platform = self.items[0]["platform"]
        other_platform = "instagram" if platform == "facebook_pages" else "facebook_pages"
        # Twenty corrections across scope, platform, campaign, post, and unavailable context.
        cases = [
            (None, None, None, global_id),
            (platform, None, None, platform_rule["id"]),
            (other_platform, None, None, global_id),
            (platform, campaign, None, campaign_rule["id"]),
            (other_platform, campaign, None, campaign_rule["id"]),
            (None, campaign, None, campaign_rule["id"]),
            (platform, "2027-01-04", None, platform_rule["id"]),
            (other_platform, "2027-01-04", None, global_id),
            (None, "2027-01-04", None, global_id),
            (platform, campaign, self.items[0]["id"], campaign_rule["id"]),
            (other_platform, campaign, self.items[1]["id"], campaign_rule["id"]),
            (platform, None, self.items[0]["id"], platform_rule["id"]),
            (None, campaign, "unknown", campaign_rule["id"]),
            ("unknown", campaign, None, campaign_rule["id"]),
            ("unknown", None, None, global_id),
            (None, None, "unknown", global_id),
            (platform, "unknown", "unknown", platform_rule["id"]),
            (other_platform, "unknown", "unknown", global_id),
            ("unknown", "unknown", "unknown", global_id),
            (None, "unknown", self.items[0]["id"], global_id),
        ]
        for index, (candidate_platform, candidate_campaign, candidate_post, expected) in enumerate(cases):
            with self.subTest(case=index):
                self.assertEqual(self.rules(platform=candidate_platform,
                                            campaign=candidate_campaign, post=candidate_post)[0]["id"], expected)

        conflict = self.submit(instruction="Use a smaller product")
        self.assertEqual(self.approve(conflict).status_code, 409)
        self.assertEqual(self.approve(conflict, "not-the-active-id").status_code, 409)
        replacement = self.approve(conflict, global_id)
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertEqual(replacement.json()["version"], 2)
        self.assertEqual(self.rules()[0]["instruction"], "Use a smaller product")
        self.assertEqual(self.client.post(f"{self.base}/learning/{replacement.json()['id']}/revert",
                                          headers=self.csrf).status_code, 200)
        self.assertFalse(self.rules())
        self.assertEqual(self.client.get(f"{self.base}/learning").json()[0]["status"], "superseded")

        later = self.plan("2027-01-04", [platform, other_platform])
        for item in later["items"]:
            selected = {rule["instruction"] for rule in item["preferences"]}
            if item["platform"] == platform:
                self.assertIn("Use an edge-aligned product", selected)
            else:
                self.assertNotIn("Use an edge-aligned product", selected)
            self.assertNotIn("Use a smaller product", selected)

    def test_workspace_and_design_revision_boundaries(self):
        another = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"}).json()["workspace_id"]
        other_base = f"/api/v1/workspaces/{another}"
        body = {"original_text": "x", "interpretation": "y", "category": "layout",
                "kind": "preference", "scope": "future"}
        self.assertEqual(self.client.post(f"{other_base}/designs/{self.design['id']}/feedback",
                                          headers=self.csrf, json=body).status_code, 404)
        note = self.submit()
        self.assertEqual(self.client.post(f"{other_base}/feedback/{note['id']}/approve",
                                          headers=self.csrf, json={}).status_code, 404)
        self.assertEqual(self.client.get(f"{other_base}/learning").json(), [])
        self.assertEqual(self.client.get(f"{other_base}/designs/{self.design['id']}/feedback").json(), [])
        self.assertEqual(self.client.get(f"{self.base}/designs/{self.design['id']}/feedback").json()[0]["id"], note["id"])
        self.client.close()
        self.client = TestClient(self.client.app, base_url="https://testserver")
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get(f"{self.base}/designs/{self.design['id']}/feedback").json()[0]["id"], note["id"])

    def test_twenty_distinct_corrections_keep_their_intended_scope(self):
        platform = self.items[0]["platform"]
        campaign = "2026-12-28"
        for scope in ("post", "campaign", "platform", "future"):
            for category in ("imagery", "copy", "layout", "color", "typography"):
                with self.subTest(scope=scope, category=category):
                    instruction = f"{scope} correction for {category}"
                    note = self.submit(scope=scope, category=category, instruction=instruction)
                    if scope == "post":
                        self.assertEqual(note["status"], "local_only")
                        continue
                    accepted = self.approve(note)
                    self.assertEqual(accepted.status_code, 200, accepted.text)
                    matching = self.rules(
                        platform=platform if scope == "platform" else "not-this-platform",
                        campaign=campaign if scope == "campaign" else "2027-01-04")
                    self.assertIn(instruction, [row["instruction"] for row in matching])
        isolated = self.rules(platform="not-this-platform", campaign="2027-01-04")
        self.assertEqual({row["instruction"] for row in isolated},
                         {f"future correction for {category}" for category in
                          ("imagery", "copy", "layout", "color", "typography")})

    def test_free_gemini_tool_context_withholds_local_preferences(self):
        note = self.submit(instruction="Keep a private layout preference local")
        self.assertEqual(self.approve(note).status_code, 200)
        sessions = build_session_factory(self.engine)
        app = self.client.app
        free = Phase4Service(sessions, app.state.accounts, app.state.storage,
                             RuntimeConfig(execution_mode=ExecutionMode.GEMINI_FREE,
                                           model_provider=ModelProvider.GEMINI))
        paid = Phase4Service(sessions, app.state.accounts, app.state.storage,
                             RuntimeConfig(execution_mode=ExecutionMode.PAID_OPT_IN,
                                           model_provider=ModelProvider.OPENAI,
                                           openai_paid_enabled=True))
        with patch.object(Phase4Service, "_tool_run", return_value=SimpleNamespace(id="fixture-run")):
            self.assertEqual(free.get_brand_context(self.workspace, "fixture-job")["preferences"], [])
            self.assertEqual(paid.get_brand_context(self.workspace, "fixture-job")["preferences"][0]["instruction"],
                             "Keep a private layout preference local")
