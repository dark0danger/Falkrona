from datetime import date, datetime, timedelta, timezone
import unittest
from sqlalchemy import func, select

from brandpilot.database import build_session_factory
from brandpilot.models import SocialPost, MetricObservation, WeeklyPlan, WeeklyReport
from tests.integration import test_phase8_studio_api as studio_fixture


class WeeklyResultsTests(unittest.TestCase):
    setUp = studio_fixture.StudioApiTests.setUp
    tearDown = studio_fixture.StudioApiTests.tearDown
    def test_two_cycles_deduplicate_and_exclude_unpublished_designs(self):
        self.client.post(self.design_path, headers=self.csrf)
        week = date(2026, 9, 14)
        for offset in (0, 7):
            response = self.client.post(f"{self.base}/results/cycle", headers=self.csrf,
                json={"week_start": (week + timedelta(days=offset)).isoformat()})
            self.assertEqual(response.status_code, 201, response.text)
            first = response.json()
            duplicate = self.client.post(f"{self.base}/results/cycle", headers=self.csrf,
                json={"week_start": (week + timedelta(days=offset)).isoformat()}).json()
            self.assertEqual(first["id"], duplicate["id"])
            self.assertEqual(first["next_plan_id"], duplicate["next_plan_id"])
            self.assertEqual(first["report"]["audit"]["posts"]["value"], 0)
            self.assertEqual(first["revision"], 1)
        sessions = build_session_factory(self.engine)
        with sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(WeeklyReport)), 2)
            self.assertEqual(session.get(WeeklyPlan, first["next_plan_id"]).status, "draft")

    def test_refresh_preserves_window_and_late_evidence_provenance(self):
        week = "2026-09-14"
        path = f"{self.base}/results/cycle"
        before = self.client.post(path, headers=self.csrf, json={"week_start": week}).json()
        sessions = build_session_factory(self.engine)
        with sessions() as session, session.begin():
            post = SocialPost(workspace_id=self.workspace, provider="instagram", account_id="account",
                source_id="published-1", text="Owner imported post", provenance="owner_imported",
                published_at=datetime(2026, 9, 15, tzinfo=timezone.utc), observed_at=datetime(2026, 9, 22, tzinfo=timezone.utc))
            session.add(post); session.flush()
            session.add(MetricObservation(workspace_id=self.workspace, post_id=post.id, metric="reactions",
                traffic="organic", status="observed", value=0,
                window_start=datetime.fromisoformat(before["report"]["window_start"]),
                window_end=datetime.fromisoformat(before["report"]["window_end"]), source_ref="owner-export",
                observed_at=datetime(2026, 9, 23, tzinfo=timezone.utc)))
        after = self.client.post(path, headers=self.csrf, json={"week_start": week, "refresh": True}).json()
        self.assertEqual(after["revision"], 2)
        self.assertEqual(after["next_plan_id"], before["next_plan_id"])
        self.assertEqual(after["report"]["audit"]["posts"]["value"], 1)
        self.assertEqual(after["report"]["audit"]["posts"]["items"][0]["provenance"], "owner_imported")
        self.assertEqual(after["report"]["audit"]["metrics"][0]["value"], 0)
        self.assertTrue(any("after" in text for text in after["report"]["uncertainties"]))

    def test_future_week_csrf_and_workspace_isolation(self):
        path = f"{self.base}/results/cycle"
        self.assertEqual(self.client.post(path, json={"week_start": "2026-09-14"}).status_code, 403)
        self.assertEqual(self.client.post(path, headers=self.csrf, json={"week_start": "2099-01-05"}).status_code, 422)
        self.client.post(path, headers=self.csrf, json={"week_start": "2026-09-14"})
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"}).json()["workspace_id"]
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{other}/results").json()["reports"], [])
