export type EngagementPost = { post_id: string; text: string; provider: string; counts: Record<string, number | null> };
export type DashboardReport = { id: string; week_start: string; report: {
  engagement?: EngagementPost[]; experiment?: { hypothesis: string; measure: string };
} };

export function currentCairoWeek(now = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(now).map(part => [part.type, part.value]));
  const monday = new Date(`${parts.year}-${parts.month}-${parts.day}T12:00:00Z`);
  monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7);
  return monday.toISOString().slice(0, 10);
}

// Each report contains lifetime snapshots. Use only the latest report, never add snapshots across weeks.
export function latestPerformance(reports: DashboardReport[]) {
  const latest = [...reports].sort((a, b) => b.week_start.localeCompare(a.week_start))[0];
  return { report: latest, posts: (latest?.report.engagement ?? []).filter(post => post.counts.reactions != null) };
}
