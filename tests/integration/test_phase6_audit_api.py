from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine, build_session_factory
from brandpilot.models import SocialPost
from brandpilot.settings import AppSettings


class Phase6AuditApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'audit.db'}")
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
        self.path = f"/api/v1/workspaces/{self.workspace}/analytics"

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_cold_start_record_evidence_invalidate(self):
        cold = self.client.get(f"{self.path}/audit")
        self.assertEqual(cold.status_code, 200, cold.text)
        self.assertEqual(cold.json()["posts"]["status"], "no_posts")
        with build_session_factory(self.engine)() as session, session.begin():
            row = SocialPost(workspace_id=self.workspace, provider="facebook_pages", account_id="123",
                             source_id="123_1", text="Hello", provenance="owner_import")
            session.add(row)
            session.flush()
            post_id = row.id
        now = datetime.now(timezone.utc)
        body = {"post_id": post_id, "metric": "reactions", "traffic": "organic", "status": "observed",
                "value": 0, "window_start": (now - timedelta(days=2)).isoformat(),
                "window_end": (now - timedelta(days=1)).isoformat(), "source_ref": "export:row:1"}
        no_csrf = self.client.post(f"{self.path}/metrics", json=body)
        self.assertNotEqual(no_csrf.status_code, 201)
        metric = self.client.post(f"{self.path}/metrics", headers=self.csrf, json=body)
        self.assertEqual(metric.status_code, 201, metric.text)
        metric_id = metric.json()["id"]
        comment = self.client.post(f"{self.path}/comments", headers=self.csrf, json={
            "post_id": post_id, "source_ref": "comment:1", "text": "Price? email me at alice@example.test"})
        self.assertEqual(comment.status_code, 201, comment.text)
        comment_id = comment.json()["id"]
        duplicate = self.client.post(f"{self.path}/comments", headers=self.csrf, json={
            "post_id": post_id, "source_ref": "comment:1", "text": "Changed"})
        self.assertEqual(duplicate.json()["id"], comment_id)
        audit = self.client.get(f"{self.path}/audit").json()
        self.assertEqual(audit["posts"]["value"], 1)
        self.assertEqual(audit["metrics"][0]["value"], 0)
        self.assertEqual(audit["metrics"][0]["evidence_ids"], [metric_id])
        self.assertEqual(audit["themes"][0]["evidence_ids"], [comment_id])
        evidence = self.client.get(f"{self.path}/evidence/{comment_id}")
        self.assertNotIn("alice@example.test", evidence.text)
        self.assertIn("[email]", evidence.text)
        invalidated = self.client.post(f"{self.path}/metric/{metric_id}/invalidate", headers=self.csrf)
        self.assertEqual(invalidated.status_code, 200, invalidated.text)
        self.assertEqual(self.client.get(f"{self.path}/audit").json()["metrics"], [])
        self.assertEqual(self.client.get(f"{self.path}/evidence/{metric_id}").json()["invalidated"], True)

    def test_cross_workspace_post_and_evidence_are_not_available(self):
        setup = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"})
        self.assertEqual(setup.status_code, 201, setup.text)
        other = setup.json()["workspace_id"]
        with build_session_factory(self.engine)() as session, session.begin():
            row = SocialPost(workspace_id=other, provider="instagram", account_id="ig",
                             source_id="ig_1", text="Other", provenance="owner_import")
            session.add(row)
            session.flush()
            other_post = row.id
        now = datetime.now(timezone.utc)
        attempt = self.client.post(f"{self.path}/metrics", headers=self.csrf, json={
            "post_id": other_post, "metric": "reach", "traffic": "organic", "status": "observed",
            "value": 7, "window_start": (now - timedelta(days=2)).isoformat(),
            "window_end": (now - timedelta(days=1)).isoformat(), "source_ref": "other"})
        self.assertEqual(attempt.status_code, 422, attempt.text)
        self.assertEqual(self.client.get(f"{self.path}/evidence/{other_post}").status_code, 404)
        self.assertEqual(self.client.get(f"{self.path}/audit").json()["posts"]["value"], 0)


if __name__ == "__main__":
    unittest.main()
