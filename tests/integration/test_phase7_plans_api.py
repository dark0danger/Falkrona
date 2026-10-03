from datetime import date
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.settings import AppSettings


class Phase7PlansApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'plans.db'}")
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
        self.assertEqual(login.status_code, 200, login.text)
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.base = f"/api/v1/workspaces/{self.workspace}"
        self.week = "2026-12-28"

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def confirm_profile(self, *, offer="coffee catering"):
        proposal = self.client.post(f"{self.base}/brand/proposals", headers=self.csrf, json={"fields": {
            "brand_name": "Nile Coffee", "category": "coffee catering",
            "audience": "office teams", "offer": offer,
        }})
        self.assertEqual(proposal.status_code, 201, proposal.text)
        version = proposal.json()["version"]
        confirmed = self.client.post(f"{self.base}/brand/versions/{version}/confirm", headers=self.csrf)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        return version

    def generate(self, **overrides):
        body = {"week_start": self.week, "goal": "leads",
                "platforms": ["facebook_pages", "instagram"], "cadence": 2, **overrides}
        return self.client.post(f"{self.base}/plans", headers=self.csrf, json=body)

    def test_offline_manual_revision_approval_and_history(self):
        self.assertIsNone(self.client.get(f"{self.base}/plans", params={"week_start": self.week}).json()["plan"])
        no_profile = self.generate()
        self.assertEqual(no_profile.status_code, 422)
        self.assertEqual(no_profile.json()["detail"]["code"], "profile_required")
        self.confirm_profile()
        no_csrf = self.client.post(f"{self.base}/plans", json={"week_start": self.week, "goal": "leads", "platforms": ["facebook_pages"]})
        self.assertEqual(no_csrf.status_code, 403)
        created = self.generate()
        self.assertEqual(created.status_code, 201, created.text)
        plan = created.json()
        self.assertEqual(plan["strategy"]["publication_mode"], "manual_only")
        self.assertEqual(len(plan["items"]), 2)
        item = plan["items"][0]
        edited = self.client.patch(f"{self.base}/plans/{plan['id']}/items/{item['id']}", headers=self.csrf,
                                   json={"title": "A practical coffee question", "scheduled_at": "2026-12-31T11:00", "locked": True})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["items"][0]["title"], "A practical coffee question")
        self.assertTrue(any(entry["scheduled_at"] == "2026-12-31T09:00:00+00:00" for entry in edited.json()["items"]))
        strategy = self.client.patch(f"{self.base}/plans/{plan['id']}/strategy", headers=self.csrf,
                                     json={"direction": "Help office teams compare coffee catering options."})
        self.assertEqual(strategy.status_code, 200, strategy.text)
        approved = self.client.post(f"{self.base}/plans/{plan['id']}/approve", headers=self.csrf)
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(self.client.patch(f"{self.base}/plans/{plan['id']}/strategy", headers=self.csrf,
                                           json={"direction": "changed"}).status_code, 409)
        replanned = self.generate()
        self.assertEqual(replanned.status_code, 201, replanned.text)
        new_plan = replanned.json()
        self.assertEqual(new_plan["revision"], 2)
        self.assertEqual({item["id"] for item in new_plan["items"]}, {item["id"] for item in approved.json()["items"]})
        listed = self.client.get(f"{self.base}/plans", params={"week_start": self.week}).json()
        self.assertEqual(listed["plan"]["id"], new_plan["id"])
        self.assertEqual(listed["last_approved"]["id"], plan["id"])

    def test_changed_profile_conflicts_and_workspace_boundary(self):
        self.confirm_profile()
        first = self.generate().json()
        self.assertEqual(self.client.post(f"{self.base}/plans/{first['id']}/approve", headers=self.csrf).status_code, 200)
        self.confirm_profile(offer="new catering")
        next_response = self.generate()
        self.assertEqual(next_response.status_code, 201, next_response.text)
        next_plan = next_response.json()
        self.assertTrue(all("profile_changed" in item["conflicts"] for item in next_plan["items"]))
        refused = self.client.post(f"{self.base}/plans/{next_plan['id']}/approve", headers=self.csrf)
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(self.client.get(f"{self.base}/plans", params={"week_start": self.week}).json()["last_approved"]["id"], first["id"])
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"})
        self.assertEqual(other.status_code, 201, other.text)
        other_base = f"/api/v1/workspaces/{other.json()['workspace_id']}"
        self.assertIsNone(self.client.get(f"{other_base}/plans", params={"week_start": self.week}).json()["plan"])
        cross = self.client.post(f"{other_base}/plans/{next_plan['id']}/approve", headers=self.csrf)
        self.assertEqual(cross.status_code, 404)


if __name__ == "__main__":
    unittest.main()
