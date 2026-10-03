import { describe, expect, it } from "vitest";
import { currentCairoWeek, latestPerformance, type DashboardReport } from "./dashboard";

describe("dashboard evidence", () => {
  it("uses Cairo's week boundary rather than the UTC date", () => {
    expect(currentCairoWeek(new Date("2026-09-27T22:30:00Z"))).toBe("2026-09-28");
  });
  it("does not add repeated lifetime snapshots across reports", () => {
    const reports: DashboardReport[] = [
      { id: "older", week_start: "2026-09-21", report: { engagement: [{ post_id: "p", text: "Post", provider: "facebook_pages", counts: { reactions: 10 } }] } },
      { id: "latest", week_start: "2026-09-28", report: { engagement: [{ post_id: "p", text: "Post", provider: "facebook_pages", counts: { reactions: 15 } }] } },
    ];
    expect(latestPerformance(reports).posts[0].counts.reactions).toBe(15);
    expect(reports[0].id).toBe("older");
  });
  it("retains measured zero while excluding missing reactions", () => {
    const result = latestPerformance([{ id: "r", week_start: "2026-09-28", report: { engagement: [
      { post_id: "missing", text: "Missing", provider: "facebook_pages", counts: { reactions: null } },
      { post_id: "zero", text: "Zero", provider: "facebook_pages", counts: { reactions: 0 } },
    ] } }]);
    expect(result.posts.map(post => post.post_id)).toEqual(["zero"]);
  });
});
