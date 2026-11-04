import { CampaignArt } from "./CampaignArt";
import { ArrowRight, Check, ChevronRight, Facebook, Instagram, RefreshCw } from "lucide-react";
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
    {snapshot && <div className="overview-grid">
      <div className="campaign-hero">
        <div className="campaign-copy">
          <span className="campaign-kicker"><i/>{!branding?.ready || !hasProduct ? "SETUP" : `WEEK OF ${dateLabel.toUpperCase()}`}</span>
          <h2>{!branding?.ready ? "Give your brand a starting point." : !hasProduct ? "Put your product in the picture." : snapshot.plan ? (ready === snapshot.plan.items.length && ready > 0 ? "Your designs are ready." : "Your week is taking shape.") : "A week of content, ready to plan."}</h2>
          <p>{!branding?.ready ? "Add your logo and tell us who you sell to." : !hasProduct ? "Add a clear photo of the product you want to feature." : snapshot.plan ? `${ready} of ${snapshot.plan.items.length} designs ready to review.` : "Create posts for your brand, then review the week in one place."}</p>
          <button className="primary" onClick={() => navigate(!branding?.ready ? "brand" : !hasProduct ? "materials" : "calendar")}>
            {!branding?.ready ? "Set up my brand" : !hasProduct ? "Add a product photo" : snapshot.plan ? "Open my plan" : "Create my week"}<ArrowRight size={17}/>
          </button>
        </div>
        <CampaignArt/>
      </div>
      <section className="setup-card" aria-labelledby="setup-title">
        <div className="setup-heading"><h2 id="setup-title">Brand setup</h2><span>{steps.filter(step=>step.done).length} / 3</span></div>
        <div className="setup-meter" aria-hidden="true">{steps.map(step=><span key={step.title} data-done={step.done}/>)}</div>
        {steps.map((step,index)=><button className="setup-item" key={step.title} onClick={()=>navigate(step.destination)}><span className="setup-step" data-done={step.done}>{step.done ? <Check size={16} aria-label="Complete"/> : index+1}</span><span><strong>{step.title}</strong><small>{step.detail}</small></span><ChevronRight size={16} aria-hidden="true"/></button>)}
      </section>
    </div>}
    {snapshot?.plan && <div className="section-heading content-heading"><h2>This week’s posts</h2><span className="quiet-label">{snapshot.plan.items.length} posts</span></div>}
    {!snapshot && !error ? <div className="dashboard-loading" role="status"><RefreshCw size={18} /> Loading your brand overview…</div> : !snapshot?.plan?.items.length ? null : <div className="dashboard-posts">
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
    {performance.posts.length > 0 && <article className="dashboard-card performance-card">
      <div className="card-heading"><h2>Latest results</h2><button className="text-button" onClick={()=>navigate("results")}>Weekly report <ArrowRight size={15}/></button></div>
      <div className="performance-bars">{performance.posts.slice(0,3).map(post=><div className="performance-row" key={post.post_id}><div><span>{post.text}</span><strong>{post.counts.reactions?.toLocaleString()} reactions</strong></div><div className="performance-track"><span style={{width:`${(post.counts.reactions??0)/maximum*100}%`}}/></div></div>)}</div>
    </article>}
  </section>;
}
