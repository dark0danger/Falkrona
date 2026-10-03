import { useEffect, useState } from "react";

type WeeklyReport = { id: string; week_start: string; revision: number; next_plan_id: string; report: {
  generated_at: string;
  engagement?: Array<{ post_id: string; text: string; provider: string; status: string; counts: Record<string, number | null>; sources: Record<string, { source: string; observed_at: string } | null> }>;
  audit: { posts: { value: number; items: Array<{ id: string; provider: string; published_at: string; provenance: string }> }; metrics: Array<{ metric: string; value: number | null; status: string }> };
  uncertainties: string[]; learning: Array<{ id: string; instruction: string }>;
  reminders: Array<{ approval_id: string; message: string }>; experiment: { hypothesis: string; measure: string };
} };

function completedWeek() {
  const local = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const date = new Date(`${local}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7 - 7);
  return date.toISOString().slice(0, 10);
}

export function ResultsView({ workspaceId, csrf, canEdit, openCalendar }: { workspaceId: string; csrf: string; canEdit: boolean; openCalendar: () => void }) {
  const [week, setWeek] = useState(completedWeek);
  const [reports, setReports] = useState<WeeklyReport[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/api/v1/workspaces/${workspaceId}/results`;
  async function request(path: string, options?: RequestInit) {
    const response = await fetch(path, { credentials: "include", ...options });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail?.message ?? "Weekly results are unavailable.");
    return data;
  }
  useEffect(() => {
    let active = true;
    const load = () => void request(base).then((data) => { if (active) setReports(data.reports); }).catch((reason) => { if (active) setError(String(reason)); });
    load(); const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [workspaceId]);
  async function cycle(refresh: boolean) {
    setBusy(true); setError("");
    try {
      await request(`${base}/cycle`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ week_start: week, refresh }) });
      setReports((await request(base)).reports);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  return <section className="queue" aria-labelledby="results-title">
    <div className="section-heading"><div><p className="eyebrow">CONTINUING YOUR BUSINESS</p><h2 id="results-title">Weekly results</h2></div><button className="icon-button" onClick={openCalendar}>Open Calendar</button></div>
    <p className="muted">Your report appears here every Monday. Falkrona checks connected posts daily. Weeks follow Cairo time.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {canEdit && <details><summary>View an earlier week or update a report</summary><div className="studio-fields"><label>Week starting Monday<input type="date" value={week} disabled={busy} onChange={(event) => setWeek(event.target.value)} /></label></div><div className="studio-actions"><button className="primary" disabled={busy} onClick={() => void cycle(false)}>{busy ? "Preparing..." : "Prepare earlier report"}</button><button className="icon-button" disabled={busy} onClick={() => void cycle(true)}>Update with latest measurements</button></div></details>}
    {reports.length === 0 && <p>Your first report will appear after your first week. Add your brand details and connect an account to get started.</p>}
    {reports.map((entry) => <article className="studio-facts" key={entry.id}>
      <h3>Week of {new Intl.DateTimeFormat("en-GB", {day:"numeric",month:"long",timeZone:"UTC"}).format(new Date(`${entry.week_start}T12:00:00Z`))}</h3>
      <p className="muted">{entry.report.audit.posts.value} tracked posts · Updated {new Date(entry.report.generated_at).toLocaleDateString("en-GB", { timeZone: "Africa/Cairo" })}</p>
      {(entry.report.uncertainties.length > 0 || entry.report.audit.metrics.length > 0) && <details><summary>Available measurements</summary>{entry.report.uncertainties.map((note) => <p className="muted" key={note}>{note}</p>)}{entry.report.audit.metrics.map((metric, index) => <p key={index}>{metric.metric}: {metric.value ?? "Unavailable"} · {metric.status}</p>)}</details>}
      {Boolean(entry.report.engagement?.length) && <><h4>How each post is doing</h4><p className="muted">Counts are totals since publication, measured on the dates shown. They are not totals earned only during this week. A dash means unavailable.</p><div className="audit-table-wrap"><table className="engagement-table"><thead><tr><th>Post</th><th>Likes / reactions</th><th>Comments</th><th>Shares</th><th>Saves</th></tr></thead><tbody>{entry.report.engagement?.map((post) => <tr key={post.post_id}><td>{post.text || "Photo post"}<br /><small>{post.provider === "instagram" ? "Instagram" : "Facebook"}{!["observed", "owner_supplied", "partial"].includes(post.status) ? " · Measurement unavailable" : ""}</small></td>{["reactions", "comments", "shares", "saves"].map((key) => <td key={key}>{post.counts[key] ?? "—"}{post.sources[key] && <><br /><small>{new Date(post.sources[key]!.observed_at).toLocaleDateString("en-GB", { timeZone: "Africa/Cairo" })} · {post.sources[key]!.source === "meta_api" ? "Platform" : "Your export"}</small></>}</td>)}</tr>)}</tbody></table></div></>}
      <details><summary>Post evidence</summary>{entry.report.audit.posts.items.map((post) => <p key={post.id}>{post.provider} · {post.published_at} · {post.provenance}</p>)}</details>
      {entry.report.learning.length > 0 && <><strong>Your brand preferences</strong>{entry.report.learning.map((rule) => <p key={rule.id}>{rule.instruction}</p>)}</>}
      {entry.report.reminders.map((reminder) => <p className="warning-note" key={reminder.approval_id}>{reminder.message}</p>)}
      <div className="report-next"><strong>Try next week</strong><p>{entry.report.experiment.hypothesis} {entry.report.experiment.measure}</p></div>
      <button className="text-button" onClick={openCalendar}>See your next content plan →</button>
    </article>)}
  </section>;
}
