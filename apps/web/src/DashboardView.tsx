import { ArrowRight, BarChart3, CalendarDays, Check, ChevronRight, Facebook, Instagram, Plus, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { Branding } from "./BrandingView";
import type { CalendarPlan } from "./PlanImages";
import { AssetImage } from "./AssetImage";
import { currentCairoWeek, latestPerformance, type DashboardReport } from "./dashboard";

type ImageEntry = { item_id: string; status: string; image_asset_id?: string; last_error?: string };
type Connection = { id: string; provider: string; account_name: string | null; account_id: string | null; status: string };
type Snapshot = { plan: CalendarPlan | null; entries: ImageEntry[]; connections: Connection[]; reports: DashboardReport[] };
type Destination = "brand" | "materials" | "social" | "calendar" | "results";

export function DashboardView({ workspaceId, branding, hasProduct, navigate, openPost }: {
  workspaceId: string; branding: Branding | null; hasProduct: boolean;
  navigate: (destination: Destination) => void;
  openPost: (planId: string, itemId: string, platform: string, schedule: string) => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const week = currentCairoWeek();
  useEffect(() => {
    const controller = new AbortController();
    setSnapshot(null); setError("");
    const base = `/api/v1/workspaces/${workspaceId}`;
    async function get<T>(path: string): Promise<T> {
      const response = await fetch(path, { credentials: "include", signal: controller.signal });
      if (!response.ok) throw new Error("We couldn't load your overview. Please try again.");
      return response.json();
    }
    void (async () => {
      const [plans, accounts, results] = await Promise.all([
        get<{ plan: CalendarPlan | null }>(`${base}/plans?week_start=${week}`),
        get<{ connections: Connection[] }>(`${base}/social/connections`),
        get<{ reports: DashboardReport[] }>(`${base}/results`),
      ]);
      const images = plans.plan ? await get<{ entries: ImageEntry[] }>(`${base}/plans/${plans.plan.id}/images`) : { entries: [] };
      if (!controller.signal.aborted) setSnapshot({ plan: plans.plan, entries: images.entries, connections: accounts.connections, reports: results.reports });
    })().catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [workspaceId, week, refresh]);

  const accounts = snapshot?.connections.filter(connection => connection.account_id && ["connected", "connected_partial"].includes(connection.status)) ?? [];
  const ready = snapshot?.entries.filter(entry => entry.status === "ready").length ?? 0;
  const performance = latestPerformance(snapshot?.reports ?? []);
  const maximum = Math.max(1, ...performance.posts.map(post => post.counts.reactions ?? 0));
  const steps: Array<{ title: string; detail: string; done: boolean; destination: Destination }> = [
    { title: "Brand essentials", detail: "Your identity, style and logo", done: Boolean(branding?.ready), destination: "brand" },
    { title: "Product photos", detail: "The products you want to share", done: hasProduct, destination: "materials" },
    { title: "Social accounts", detail: "Connect an account to track results", done: accounts.length > 0, destination: "social" },
  ];
  const dateLabel = new Intl.DateTimeFormat("en-GB", { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(`${week}T12:00:00Z`));
  return <section className="dashboard-view" aria-label="Brand dashboard" aria-busy={!snapshot && !error}>
    {error && <p className="form-error" role="alert">{error} <button className="text-button" onClick={() => setRefresh(value => value + 1)}>Try again</button></p>}
    <div className="dashboard-stats">
      {[{ label: "Posts planned", value: snapshot?.plan?.items.length ?? 0, note: `Week of ${dateLabel}`, accent: "coral", icon: CalendarDays },
        { label: "Designs ready", value: ready, note: ready ? "Ready to download and share" : "Your next idea starts here", accent: "green", icon: Sparkles },
        { label: "Social accounts", value: accounts.length, note: accounts.length ? "Connected to your brand" : "Connect to track your posts", accent: "gold", icon: Facebook }].map(stat => <article className={`dashboard-stat accent-${stat.accent}`} key={stat.label}>
        <div><span>{stat.label}</span><strong>{snapshot ? stat.value : "—"}</strong><small>{stat.note}</small></div><stat.icon size={22} aria-hidden="true" />
      </article>)}
    </div>
    <div className="dashboard-middle">
      <article className="dashboard-card performance-card">
        <div className="card-heading"><h2>Post performance</h2><button className="text-button" onClick={() => navigate("results")}>View reports <ArrowRight size={15} /></button></div>
        {performance.posts.length ? <><p className="muted">Likes / reactions · latest report, week of {performance.report?.week_start}</p><div className="performance-bars">{performance.posts.slice(0, 4).map((post, index) => <div className="performance-row" key={post.post_id}>
          <div><span title={post.text}>{post.text || `Post ${index + 1}`}</span><strong>{post.counts.reactions?.toLocaleString()}</strong></div>
          <div className="performance-track"><span style={{ width: `${(post.counts.reactions ?? 0) / maximum * 100}%` }} /></div>
        </div>)}</div><p className="chart-footnote">Totals since publication, measured in your latest report.</p></> : <div className="performance-empty">
          <span className="empty-icon"><BarChart3 size={25} /></span><h3>Your results will grow here</h3><p>Once your posts have measurements, you’ll see how they’re doing in your weekly report.</p>
          <button className="icon-button" onClick={() => navigate(accounts.length ? "results" : "social")}>{accounts.length ? "Open weekly reports" : "Connect an account"}<ArrowRight size={15} /></button>
        </div>}
      </article>
      <article className="dashboard-card brand-checklist">
        <div className="card-heading"><h2>Your brand at a glance</h2><span className="quiet-label">{steps.filter(step => step.done).length} / 3 ready</span></div>
        {steps.map(step => <button className="checklist-row" key={step.title} onClick={() => navigate(step.destination)}>
          <span className={`checklist-icon ${step.done ? "complete" : ""}`}>{step.done ? <Check size={17} /> : <Plus size={17} />}</span>
          <span><strong>{step.title}</strong><small>{step.detail}</small></span><ChevronRight size={17} />
        </button>)}
        <div className="brand-next"><Sparkles size={17} /><p>{snapshot?.plan ? "Your week is taking shape. Keep creating, and Falkrona will track the results." : "A few brand details. A whole week of ideas."}</p></div>
      </article>
    </div>
    <div className="section-heading content-heading"><div><h2>This week’s content</h2><p className="muted">Your ideas, all in one place.</p></div><button className="primary" onClick={() => navigate(branding?.ready ? "calendar" : "brand")}><Plus size={18} />{snapshot?.plan ? "Open content plan" : "Plan your week"}</button></div>
    {!snapshot && !error ? <div className="dashboard-loading" role="status"><RefreshCw size={18} /> Loading your brand overview…</div> : !snapshot?.plan?.items.length ? <div className="dashboard-card content-empty"><CalendarDays size={28} /><h3>A fresh week starts with a good plan</h3><p>Let Gemini turn your brand and products into a week of post ideas.</p><button className="text-button" onClick={() => navigate(branding?.ready ? "calendar" : "brand")}>Get started <ArrowRight size={16} /></button></div> : <div className="dashboard-posts">
      {snapshot.plan.items.map(item => {
        const entry = snapshot.entries.find(image => image.item_id === item.id);
        const isReady = entry?.status === "ready";
        return <button className="content-card" key={item.id} onClick={() => isReady ? openPost(snapshot.plan!.id, item.id, item.platform, item.scheduled_at) : navigate("calendar")}>
          <AssetImage workspaceId={workspaceId} assetId={entry?.image_asset_id} alt={item.title} />
          <div className="content-card-copy"><span className={`platform-label ${item.platform === "instagram" ? "instagram" : "facebook"}`}>{item.platform === "instagram" ? <Instagram size={18} /> : <Facebook size={18} />}{item.platform === "instagram" ? "Instagram" : "Facebook"}</span>
            <time dateTime={item.scheduled_at}>{new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(item.scheduled_at))} <small>Cairo</small></time>
            <h3>{item.title}</h3><span className={`content-status ${isReady ? "ready" : "draft"}`}>{isReady ? "Ready" : entry?.last_error || ["failed", "cancelled"].includes(entry?.status ?? "") ? "Needs attention" : entry ? "In progress" : "Draft"}</span>
          </div>
        </button>;
      })}
    </div>}
  </section>;
}
