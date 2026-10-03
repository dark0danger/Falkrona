from datetime import datetime, timedelta, timezone
import unittest

from brandpilot.analytics import build_audit, redact_comment
from brandpilot.models import AuditComment, MetricObservation, SocialPost


NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
START = NOW - timedelta(days=7)
END = NOW - timedelta(days=1)


def post(id, account="page-1"):
    return SocialPost(id=id, workspace_id="workspace", provider="facebook_pages", account_id=account,
                      source_id=id, text="", provenance="owner_import", published_at=START,
                      observed_at=NOW - timedelta(hours=1))


def metric(id, post_id, name, value, *, traffic="organic", status="observed", observed_at=NOW):
    return MetricObservation(id=id, workspace_id="workspace", post_id=post_id, metric=name,
                             traffic=traffic, status=status, value=value, window_start=START,
                             window_end=END, source_ref=id, observed_at=observed_at)


class Phase6Calculations(unittest.TestCase):
    def test_additive_zero_snapshot_replacement_and_reach(self):
        posts = [post("p1"), post("p2")]
        rows = [metric("r0", "p1", "reactions", 2, observed_at=NOW - timedelta(hours=2)),
                metric("r1", "p1", "reactions", 0), metric("r2", "p2", "reactions", 5),
                metric("reach1", "p1", "reach", 10), metric("reach2", "p2", "reach", 20),
                metric("paid1", "p1", "reactions", 9, traffic="paid"),
                metric("missing", "p1", "shares", 4)]
        report = build_audit(posts, rows, [], NOW)
        groups = {(row["metric"], row["traffic"]): row for row in report["metrics"]}
        self.assertEqual(groups["reactions", "organic"]["value"], 5)
        self.assertEqual(groups["reactions", "organic"]["evidence_ids"], ["r1", "r2"])
        self.assertEqual(groups["reach", "organic"]["status"], "per_post_only")
        self.assertIsNone(groups["reach", "organic"]["value"])
        self.assertEqual([item["value"] for item in groups["reach", "organic"]["per_post"]], [10, 20])
        self.assertIsNone(groups["reactions", "paid"]["value"])
        self.assertEqual(groups["reactions", "paid"]["missing_posts"], 1)
        self.assertIsNone(groups["shares", "organic"]["value"])
        self.assertEqual(report["posts"]["value"], 2)
        self.assertEqual(report["posts"]["items"][0]["age_days"], 7)

    def test_suppression_invalidation_and_account_boundaries(self):
        posts = [post("p1"), post("p2"), post("p3", "page-2")]
        suppressed = metric("s", "p2", "comments", None, status="suppressed")
        rows = [metric("c1", "p1", "comments", 0), suppressed,
                metric("c3", "p3", "comments", 3)]
        report = build_audit(posts, rows, [], NOW)
        page1 = next(row for row in report["metrics"] if row["account_id"] == "page-1")
        page2 = next(row for row in report["metrics"] if row["account_id"] == "page-2")
        self.assertEqual(page1["status"], "suppressed")
        self.assertIsNone(page1["value"])
        self.assertEqual(page1["suppressed_posts"], 1)
        self.assertEqual(page2["value"], 3)
        suppressed.invalidated_at = NOW
        recomputed = build_audit(posts, rows, [], NOW)
        page1 = next(row for row in recomputed["metrics"] if row["account_id"] == "page-1")
        self.assertEqual(page1["status"], "incomplete")
        self.assertEqual(page1["missing_posts"], 1)

    def test_post_published_after_window_is_not_missing_from_earlier_report(self):
        earlier = post("earlier")
        later = post("later")
        later.published_at = NOW
        report = build_audit([earlier, later], [metric("r", "earlier", "reactions", 4)], [], NOW)
        self.assertEqual(report["metrics"][0]["value"], 4)
        self.assertEqual(report["metrics"][0]["missing_posts"], 0)

    def test_cold_start_and_redacted_themes(self):
        empty = build_audit([], [], [], NOW)
        self.assertEqual(empty["posts"]["status"], "no_posts")
        self.assertEqual(empty["comments"]["status"], "unavailable")
        self.assertEqual(empty["metrics"], [])
        self.assertEqual(empty["source_freshness"]["status"], "no_source")
        text = redact_comment("What is the price? Contact alice@example.test @alice +201234567890 https://example.test")
        self.assertNotIn("alice", text)
        self.assertNotIn("201234", text)
        self.assertNotIn("example.test", text)
        comment = AuditComment(id="comment1", workspace_id="workspace", post_id="p1",
                               redacted_text=text, source_ref="export-row-1", observed_at=NOW)
        report = build_audit([post("p1")], [], [comment], NOW)
        self.assertEqual(report["themes"], [{"theme": "pricing", "value": 1, "evidence_ids": ["comment1"]}])
        comment.invalidated_at = NOW
        self.assertEqual(build_audit([post("p1")], [], [comment], NOW)["themes"], [])


if __name__ == "__main__":
    unittest.main()
