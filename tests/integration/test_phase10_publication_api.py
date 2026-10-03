from copy import deepcopy
from datetime import datetime, timedelta
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine, build_session_factory
from brandpilot.models import PublicationApproval, PublicationAttempt, SocialConnection, User, WorkspaceMembership
from brandpilot.publication import PublicationError, cairo_instant
from brandpilot.settings import AppSettings
from tests.integration.branding_fixture import complete_branding


class PublicationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'publication.db'}")
        Base.metadata.create_all(self.engine)
        settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:", storage_root=root / "storage",
            runtime=RuntimeConfig(execution_mode=ExecutionMode.OFFLINE_TEST, model_provider=ModelProvider.NONE),
            app_secret_key=b"a" * 32, credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
        )
        self.app = create_app(settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        setup = self.client.post("/api/v1/setup/owner", headers={"X-Setup-Token": settings.owner_setup_token},
                                 json={"email": "owner@example.test", "password": "owner-password-long",
                                       "workspace_name": "TepeS"})
        self.assertEqual(setup.status_code, 201, setup.text)
        self.workspace = setup.json()["workspace_id"]
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test",
                                                           "password": "owner-password-long"})
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.base = f"/api/v1/workspaces/{self.workspace}"
        self.profile = self.client.post(f"{self.base}/brand/proposals", headers=self.csrf,
                                        json={"fields": {"brand_name": "TepeS", "category": "juice"}}).json()
        self.client.post(f"{self.base}/brand/versions/{self.profile['version']}/confirm", headers=self.csrf)
        complete_branding(self.client, self.base, self.csrf)
        self.profile = self.client.get(f"{self.base}/brand").json()["profile"]
        # Keep the fixture week in the future regardless of the day tests are run.
        local = datetime.now(ZoneInfo("Africa/Cairo")) + timedelta(days=35)
        self.week = (local.date() - timedelta(days=local.weekday())).isoformat()
        plan_response = self.client.post(f"{self.base}/plans", headers=self.csrf,
                                         json={"week_start": self.week, "goal": "awareness",
                                               "platforms": ["facebook_pages"], "cadence": 1})
        self.assertEqual(plan_response.status_code, 201, plan_response.text)
        self.plan = plan_response.json()
        self.item = self.plan["items"][0]
        design_response = self.client.post(
            f"{self.base}/plans/{self.plan['id']}/items/{self.item['id']}/design", headers=self.csrf)
        self.assertEqual(design_response.status_code, 201, design_response.text)
        self.design = design_response.json()
        self.path = f"{self.base}/designs/{self.design['id']}/publication-approvals"
        self.schedule = datetime.fromisoformat(self.item["scheduled_at"]).astimezone(
            ZoneInfo("Africa/Cairo")).strftime("%Y-%m-%dT%H:%M")

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def approval_body(self, **changes):
        return {"platform": "facebook_pages", "account_id": "TepeS",
                "connection_id": None, "schedule_local": self.schedule,
                "fold": None, "idempotency_key": "review-12345678",
                "facts_reviewed": True, **changes}

    def render_and_approve_plan(self):
        data = BytesIO()
        Image.new("RGB", (1080, 1350), "#c5223b").save(data, "PNG")
        for slide in self.design["scene"]["slides"]:
            response = self.client.post(
                f"{self.base}/designs/{self.design['id']}/slides/{slide['id']}/renders",
                headers=self.csrf, data={"preset": "portrait"},
                files={"file": ("slide.png", data.getvalue(), "image/png")})
            self.assertEqual(response.status_code, 200, response.text)
        approved = self.client.post(f"{self.base}/plans/{self.plan['id']}/approve", headers=self.csrf)
        self.assertEqual(approved.status_code, 200, approved.text)

    def test_exact_version_manual_package_dedupe_and_cancel(self):
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body()).status_code, 409)
        self.render_and_approve_plan()
        self.assertEqual(self.client.post(self.path, json=self.approval_body()).status_code, 403)
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body(facts_reviewed=False)).status_code, 422)
        created = self.client.post(self.path, headers=self.csrf, json=self.approval_body())
        self.assertEqual(created.status_code, 201, created.text)
        approval = created.json()
        self.assertEqual(approval["delivery_mode"], "manual")
        self.assertEqual(approval["attempt"]["status"], "manual_ready")
        self.assertIsNone(approval["attempt"]["remote_publish_id"])
        duplicate = self.client.post(self.path, headers=self.csrf, json=self.approval_body())
        self.assertEqual(duplicate.json()["id"], approval["id"])
        another_key = self.client.post(self.path, headers=self.csrf,
                                       json=self.approval_body(idempotency_key="review-87654321"))
        self.assertEqual(another_key.json()["id"], approval["id"])
        sessions = build_session_factory(self.engine)
        with sessions() as session:
            self.assertEqual(len(session.scalars(select(PublicationApproval)).all()), 1)
            self.assertEqual(len(session.scalars(select(PublicationAttempt)).all()), 1)
        package_path = f"{self.base}/publication-approvals/{approval['id']}/manual-package"
        self.assertEqual(self.client.post(package_path).status_code, 403)
        download = self.client.post(package_path, headers=self.csrf)
        self.assertEqual(download.status_code, 200, download.text)
        with ZipFile(BytesIO(download.content)) as archive:
            self.assertEqual(len([name for name in archive.namelist() if name.endswith(".png")]),
                             len(self.design["scene"]["slides"]))
            self.assertEqual(archive.read("caption.txt").decode(), self.design["caption"])
            receipt = json.loads(archive.read("publication-approval.json"))
            self.assertEqual(receipt["approval_id"], approval["id"])
            self.assertEqual(receipt["content_hash"], approval["content_hash"])
            self.assertEqual(receipt["destination_account_id"], "TepeS")
            self.assertFalse(receipt["published"])
        self.assertEqual(self.client.get(self.path).json()[0]["attempt"]["status"], "manual_exported")
        cancel = self.client.post(f"{self.base}/publication-approvals/{approval['id']}/cancel",
                                  headers=self.csrf)
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(cancel.json()["status"], "cancelled")
        self.assertEqual(self.client.post(package_path, headers=self.csrf).status_code, 409)

    def test_new_revision_profile_edit_and_scope_block_old_approval(self):
        self.render_and_approve_plan()
        approved = self.client.post(self.path, headers=self.csrf,
                                    json=self.approval_body()).json()
        other = self.client.post("/api/v1/workspaces", headers=self.csrf,
                                 json={"name": "Other"}).json()["workspace_id"]
        self.assertEqual(self.client.post(
            f"/api/v1/workspaces/{other}/publication-approvals/{approved['id']}/manual-package", headers=self.csrf
        ).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{other}/designs/{self.design['id']}/publication-approvals").json(), [])
        scene = deepcopy(self.design["scene"])
        headline = next(layer for layer in scene["slides"][0]["layers"] if layer["role"] == "headline")
        headline["text"] = "Fresh juice"
        revised = self.client.post(f"{self.base}/designs/{self.design['id']}/revisions",
                                   headers=self.csrf, json={"scene": scene, "caption": self.design["caption"]})
        self.assertEqual(revised.status_code, 201, revised.text)
        self.assertEqual(self.client.post(
            f"{self.base}/publication-approvals/{approved['id']}/manual-package", headers=self.csrf
        ).status_code, 409)
        proposal = self.client.post(f"{self.base}/brand/proposals", headers=self.csrf,
                                    json={"fields": {"brand_name": "TepeS", "category": "new juice"}}).json()
        self.client.post(f"{self.base}/brand/versions/{proposal['version']}/confirm", headers=self.csrf)
        self.assertEqual(self.client.post(f"{self.base}/designs/{revised.json()['id']}/publication-approvals",
                                          headers=self.csrf, json=self.approval_body()).status_code, 409)

    def test_destination_schedule_and_request_conflicts(self):
        self.render_and_approve_plan()
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body(platform="instagram")).status_code, 422)
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body(account_id=" ")).status_code, 422)
        approval = self.client.post(self.path, headers=self.csrf, json=self.approval_body()).json()
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body(account_id="Other" )).status_code, 409)
        self.assertEqual(self.client.post(self.path, headers=self.csrf,
                                          json=self.approval_body(connection_id="not-a-connection",
                                                                  idempotency_key="review-22222222")).status_code, 409)
        self.assertEqual(self.client.get(self.path).json()[0]["id"], approval["id"])

    def test_disconnect_and_role_revocation_block_a_prepared_package(self):
        self.render_and_approve_plan()
        sessions = build_session_factory(self.engine)
        with sessions() as session, session.begin():
            user = session.scalar(select(User).where(User.email == "owner@example.test"))
            connection = SocialConnection(workspace_id=self.workspace, provider="meta",
                                          authorized_by_user_id=user.id, account_id="12345",
                                          account_name="TepeS", status="connected_partial",
                                          granted_scopes=["pages_show_list"],
                                          capabilities={"posts": True, "publish": False})
            session.add(connection)
            session.flush()
            connection_id = connection.id
        approved = self.client.post(self.path, headers=self.csrf,
                                    json=self.approval_body(account_id="12345",
                                                            connection_id=connection_id)).json()
        package = f"{self.base}/publication-approvals/{approved['id']}/manual-package"
        self.assertEqual(self.client.post(package, headers=self.csrf).status_code, 200)
        with sessions() as session, session.begin():
            connection = session.get(SocialConnection, connection_id)
            connection.status = "disconnected"
        self.assertEqual(self.client.post(package, headers=self.csrf).status_code, 409)
        with sessions() as session, session.begin():
            membership = session.scalar(select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == self.workspace))
            membership.role = "analyst"
        self.assertEqual(self.client.post(package, headers=self.csrf).status_code, 403)


class CairoScheduleTests(unittest.TestCase):
    def test_gap_overlap_and_future_policy(self):
        with self.assertRaises(PublicationError) as gap:
            cairo_instant("2026-04-24T00:30", None, now=datetime(2026, 1, 1, tzinfo=ZoneInfo("Africa/Cairo")))
        self.assertEqual(gap.exception.code, "nonexistent_schedule")
        now = datetime(2026, 1, 1, tzinfo=ZoneInfo("Africa/Cairo"))
        with self.assertRaises(PublicationError) as overlap:
            cairo_instant("2026-10-29T23:30", None, now=now)
        self.assertEqual(overlap.exception.code, "ambiguous_schedule")
        first, fold0 = cairo_instant("2026-10-29T23:30", 0, now=now)
        second, fold1 = cairo_instant("2026-10-29T23:30", 1, now=now)
        self.assertEqual((fold0, fold1), (0, 1))
        self.assertEqual(abs((second - first).total_seconds()), 3600)
        with self.assertRaises(PublicationError) as missed:
            cairo_instant("2026-01-01T12:00", None, now=datetime(2026, 9, 30, tzinfo=ZoneInfo("Africa/Cairo")))
        self.assertEqual(missed.exception.code, "missed_schedule")
