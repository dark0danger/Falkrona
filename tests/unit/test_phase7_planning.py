from datetime import date, datetime, timezone
import unittest
from zoneinfo import ZoneInfo

from brandpilot.models import BrandProfileVersion, Product
from brandpilot.planning import draft_plan, suggested_cadence


CAIRO = ZoneInfo("Africa/Cairo")
WEEK = date(2026, 12, 28)


def profile(id: str, brand: str, category: str, audience: str, offer: str, **more) -> BrandProfileVersion:
    return BrandProfileVersion(id=id, workspace_id="workspace", version=1, status="confirmed",
                               fields={"brand_name": brand, "category": category,
                                       "audience": audience, "offer": offer, **more},
                               provenance={"source": "fixture"}, created_by_user_id="owner")


class Phase7PlanningTests(unittest.TestCase):
    def test_adaptive_cadence_is_bounded(self):
        self.assertEqual([suggested_cadence(count) for count in (0, 3, 4, 7, 8, 100)],
                         [2, 2, 3, 3, 4, 4])

    def test_three_businesses_get_distinct_sourced_briefs(self):
        fixtures = [
            profile("cafe", "Nile Coffee", "coffee catering", "office teams", "coffee catering"),
            profile("ceramics", "Clay House", "handmade ceramics", "home decorators", "custom mugs"),
            profile("tutoring", "Bright Lessons", "math tutoring", "parents of teens", "one-to-one tutoring"),
        ]
        results = [draft_plan(row, {}, None, [], WEEK, CAIRO, "leads",
                              ["facebook_pages", "instagram"], 3, []) for row in fixtures]
        self.assertEqual(len({strategy["direction"] for strategy, _ in results}), 3)
        for row, (strategy, items) in zip(fixtures, results):
            self.assertEqual(strategy["publication_mode"], "manual_only")
            self.assertEqual(len(items), 3)
            self.assertEqual(strategy["content_mix"]["offer"], 1)
            self.assertTrue(any(row.fields["offer"] in item["concept"] for item in items))
            for item in items:
                self.assertTrue(item["title"] and item["concept"] and item["cta"] and item["rationale"])
                self.assertIn(item["platform"], {"facebook_pages", "instagram"})
                self.assertTrue(item["factual_refs"])
                self.assertEqual(item["factual_refs"][0]["id"], row.id)

    def test_expired_promotion_and_unavailable_product_are_excluded(self):
        row = profile("cafe", "Nile Coffee", "coffee", "office teams", "20% off",
                      offer_expires_at="2026-09-01")
        product = Product(id="product", workspace_id="workspace", sku="1", name="Sold-out mug",
                          availability="out_of_stock", currency="EGP")
        strategy, items = draft_plan(row, {}, None, [product], WEEK, CAIRO, "sales",
                                     ["facebook_pages"], 4, [])
        self.assertEqual(strategy["content_mix"]["offer"], 0)
        self.assertEqual(strategy["content_mix"]["product"], 0)
        self.assertNotIn("20% off", repr(items))
        self.assertNotIn("Sold-out mug", repr(items))
        no_expiry = profile("unknown", "Nile Coffee", "coffee", "office teams", "50% discount")
        _, other = draft_plan(no_expiry, {}, None, [], WEEK, CAIRO, "sales", ["instagram"], 3, [])
        self.assertNotIn("50% discount", repr(other))

    def test_cairo_week_spans_year_and_slots_have_distinct_utc_instants(self):
        row = profile("cafe", "Nile Coffee", "coffee", "office teams", "coffee catering")
        _, items = draft_plan(row, {}, None, [], WEEK, CAIRO, "awareness", ["instagram"], 5, [])
        moments = [datetime.fromisoformat(item["scheduled_at"]) for item in items]
        self.assertEqual(len(set(moments)), 5)
        self.assertTrue(all(WEEK <= moment.astimezone(CAIRO).date() < date(2027, 1, 4) for moment in moments))
        self.assertTrue(all(moment.utcoffset() == timezone.utc.utcoffset(moment) for moment in moments))
        self.assertTrue(any(moment.astimezone(CAIRO).year == 2027 for moment in moments))

    def test_replan_carries_only_locked_or_approved_and_flags_changed_facts(self):
        original = profile("v1", "Nile Coffee", "coffee", "office teams", "coffee catering")
        _, items = draft_plan(original, {}, None, [], WEEK, CAIRO, "sales",
                              ["facebook_pages"], 3, [])
        items[0]["locked"] = True
        items[1]["status"] = "approved"
        old_ids = {item["id"] for item in items[:2]}
        revised = profile("v2", "Nile Coffee", "coffee", "office teams", "new catering")
        _, changed = draft_plan(revised, {}, None, [], WEEK, CAIRO, "sales",
                                ["facebook_pages"], 3, [], items)
        carried = [item for item in changed if item["id"] in old_ids]
        self.assertEqual(len(carried), 2)
        self.assertTrue(all("profile_changed" in item["conflicts"] for item in carried))
        self.assertNotIn(items[2]["id"], {item["id"] for item in changed})


if __name__ == "__main__":
    unittest.main()
