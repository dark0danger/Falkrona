from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import json
import unittest

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from apps.api.app import create_app
from brandpilot.branding import BrandingSurvey, STARTER
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.creative_worker import CreativeDirectionHandler
from brandpilot.database import build_session_factory
from brandpilot.engagement import EngagementHandler, save_snapshot
from brandpilot.jobs import JobStore
from brandpilot.models import (AgentRun, BrandingSetup, CredentialRecord, EngagementSnapshot, Job,
    SocialConnection, SocialPost, WeeklyReport, WorkspaceMembership, utc_now)
from brandpilot.security import CredentialCipher
from brandpilot.weekly import WeeklyReportHandler, WeeklyScheduler
from brandpilot.worker import Worker
from tests.integration.branding_fixture import complete_branding, transparent_logo
from tests.integration import test_phase8_studio_api as studio_fixture


class BrandingWeeklyTests(unittest.TestCase):
    setUp = studio_fixture.StudioApiTests.setUp
    tearDown = studio_fixture.StudioApiTests.tearDown

    def test_required_details_transparency_idempotence_and_cross_workspace_assets(self):
        sessions = build_session_factory(self.engine)
        with sessions() as session, session.begin():
            session.delete(session.get(BrandingSetup, self.workspace))
        blocked = self.client.post(self.design_path, headers=self.csrf)
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.json()["detail"]["code"], "branding_required")
        opaque = BytesIO(); Image.new("RGBA", (30, 30), "white").save(opaque, "PNG")
        invisible = BytesIO(); Image.new("RGBA", (30, 30), (0, 0, 0, 0)).save(invisible, "PNG")
        for content in (opaque.getvalue(), invisible.getvalue()):
            rejected = self.client.post(f"{self.base}/branding/assets/logo", headers=self.csrf,
                files={"file": ("bad-logo.png", content, "image/png")})
            self.assertEqual(rejected.status_code, 422, rejected.text)
        data = complete_branding(self.client, self.base, self.csrf)
        before = self.client.get(f"{self.base}/brand").json()["profile"]["version"]
        body = {k: data[k] for k in ("answers", "logo_asset_id", "reference_asset_id", "public_context_confirmed")}
        self.assertEqual(self.client.put(f"{self.base}/branding", headers=self.csrf, json=body).status_code, 200)
        self.assertEqual(self.client.get(f"{self.base}/brand").json()["profile"]["version"], before)
        incomplete = self.client.put(f"{self.base}/branding", headers=self.csrf,
            json={**body, "answers": {**data["answers"], "audience": " "}})
        self.assertEqual(incomplete.status_code, 422)
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "Other"}).json()["workspace_id"]
        response = self.client.put(f"/api/v1/workspaces/{other}/branding", headers=self.csrf, json=body)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.client.get(f"/api/v1/workspaces/{other}/branding").json()["ready"])
        self.assertEqual(self.client.post(self.design_path, headers=self.csrf).status_code, 201)

    def test_gemini_survey_is_one_deduplicated_validated_hermes_job(self):
        settings = replace(self.client.app.state.settings, runtime=RuntimeConfig(
            execution_mode=ExecutionMode.PAID_OPT_IN, model_provider=ModelProvider.GEMINI), gemini_model="fixture")
        self.client.close(); self.client = TestClient(create_app(settings, engine=self.engine), base_url="https://testserver")
        self.csrf = {"X-CSRF-Token": self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"}).json()["csrf_token"]}
        path = f"{self.base}/branding/survey"
        self.assertEqual(self.client.post(path, json={}).status_code, 403)
        first = self.client.post(path, headers=self.csrf, json={}).json()
        repeated = self.client.post(path, headers=self.csrf, json={}).json()
        self.assertEqual(first["survey_run_id"], repeated["survey_run_id"])
        sessions = build_session_factory(self.engine); store = JobStore(sessions, workspace_id=self.workspace)
        calls = []
        def executor(prompt, model, progress):
            progress(); calls.append(prompt)
            return {"text": json.dumps(STARTER), "model_calls": 1}
        handler = CreativeDirectionHandler(sessions, store, self.client.app.state.phase4, settings.runtime, executor)
        self.assertTrue(Worker("survey", store, self.client.app.state.storage, creative_handler=handler).process_one())
        finished = self.client.get(f"{self.base}/branding").json()
        self.assertEqual(finished["survey_source"], "gemini")
        BrandingSurvey.model_validate(finished["survey"])
        self.assertEqual(len(calls), 1)
        invalid = {"questions": [STARTER["questions"][0]] * 4}
        with self.assertRaises(ValueError):
            BrandingSurvey.model_validate(invalid)

    def test_daily_counts_and_restart_safe_weekly_report_delivery(self):
        sessions = build_session_factory(self.engine); store = JobStore(sessions, workspace_id=self.workspace)
        cipher = CredentialCipher({1: b"b" * 32}, current_version=1)
        encrypted, version = cipher.encrypt(self.workspace, "meta_page", "fixture-token")
        with sessions() as session, session.begin():
            session.get(BrandingSetup, self.workspace).completed_at = datetime(2026, 9, 14, tzinfo=timezone.utc)
            owner = session.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == self.workspace)).user_id
            credential = CredentialRecord(workspace_id=self.workspace, provider="meta_page", ciphertext=encrypted, key_version=version)
            session.add(credential); session.flush()
            session.add(SocialConnection(workspace_id=self.workspace, provider="meta", account_id="1234", account_name="Page",
                status="connected_partial", capabilities={"posts": True}, granted_scopes=["pages_read_engagement"],
                authorized_by_user_id=owner, account_credential_id=credential.id, token_expires_at=utc_now() + timedelta(days=1)))
            post = SocialPost(workspace_id=self.workspace, provider="facebook_pages", account_id="1234", source_id="1234_1",
                text="Our coffee", provenance="meta_api", published_at=datetime(2026, 9, 15, tzinfo=timezone.utc))
            session.add(post); session.flush(); post_id = post.id
        class Transport:
            calls = 0
            def post_engagement(self, provider, source_id, token):
                self.calls += 1
                assert (provider, source_id, token) == ("facebook_pages", "1234_1", "fixture-token")
                return {"reactions": 0, "comments": 3}  # Missing shares are unknown, never zero.
        transport = Transport()
        engagement = EngagementHandler(sessions, store, cipher, transport, injected=True)
        weekly = WeeklyReportHandler(sessions, store, self.client.app.state.results)
        scheduler = WeeklyScheduler(sessions, store, self.workspace)
        when = datetime(2026, 9, 28, 10, tzinfo=timezone.utc)
        scheduler.tick(when); scheduler.tick(when)
        with sessions() as session:
            jobs = session.scalars(select(Job)).all()
            self.assertEqual(len([j for j in jobs if j.kind == "results.weekly"]), 2)
            # Complete the separate read sync fixture; engagement must wait for it.
            sync = next(j for j in jobs if j.kind == "social.meta.sync")
            sync.status = "completed"; session.commit()
        worker = Worker("weekly", store, self.client.app.state.storage, engagement_handler=engagement, weekly_handler=weekly)
        while worker.process_one():
            pass
        reports = self.client.get(f"{self.base}/results").json()["reports"]
        self.assertEqual(len(reports), 2)
        post_result = next(r for r in reports if r["week_start"] == "2026-09-14")["report"]["engagement"][0]
        self.assertEqual(post_result["counts"]["reactions"], 0)
        self.assertEqual(post_result["counts"]["comments"], 3)
        self.assertIsNone(post_result["counts"]["shares"])
        self.assertEqual(post_result["sources"]["reactions"]["source"], "meta_api")
        scheduler.tick(when)
        self.assertFalse(worker.process_one())
        self.assertEqual(transport.calls, 1)

    def test_csv_engagement_and_unavailable_snapshot_preserve_evidence(self):
        content = b"post_id,caption,published_at,likes,comments,shares\n123,Post,2026-09-15T10:00:00Z,0,4,\n"
        preview = self.client.post(f"{self.base}/social/imports", headers=self.csrf,
            data={"provider": "instagram", "account_id": "Instagram", "dedupe_key": "counts"},
            files={"file": ("posts.csv", content, "text/csv")})
        self.assertEqual(preview.status_code, 201, preview.text)
        self.client.post(f"{self.base}/social/imports/{preview.json()['id']}/confirm", headers=self.csrf)
        sessions = build_session_factory(self.engine)
        with sessions() as session, session.begin():
            post = session.scalar(select(SocialPost).where(SocialPost.workspace_id == self.workspace))
            save_snapshot(session, self.workspace, post.id, {}, "collection_status", "permission_missing")
        report = self.client.post(f"{self.base}/results/cycle", headers=self.csrf, json={"week_start": "2026-09-14"}).json()["report"]
        post = report["engagement"][0]
        self.assertEqual(post["counts"]["reactions"], 0)
        self.assertEqual(post["counts"]["comments"], 4)
        self.assertIsNone(post["counts"]["shares"])
        self.assertEqual(post["status"], "permission_missing")
