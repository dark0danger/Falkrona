import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Building2,
  CalendarDays,
  CheckCircle2,
  Database,
  Download,
  FileSpreadsheet,
  Facebook,
  Globe2,
  HardDrive,
  Image,
  Instagram,
  Languages,
  LockKeyhole,
  LogIn,
  LogOut,
  LayoutDashboard,
  PanelRightClose,
  PanelRightOpen,
  RadioTower,
  RefreshCw,
  Send,
  Share2,
  Upload,
  UserPlus,
} from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { componentStatus, type Health } from "./health";
import { CalendarView } from "./CalendarView";
import { StudioView } from "./StudioView";
import { ResultsView } from "./ResultsView";
import { BrandingView, type Branding } from "./BrandingView";
import { DashboardView } from "./DashboardView";
import { AssetImage } from "./AssetImage";
import { cairoInput } from "./CalendarView";
import { currentCairoWeek } from "./dashboard";

type Workspace = { workspace_id: string; name: string; role: string };
type CurrentUser = { id: string; email: string; workspaces: Workspace[] };
type AuthMode = "login" | "setup";
type Asset = { id: string; name: string; mime_type: string; sha256: string; size: number; asset_type: string; metadata: Record<string, unknown>; source?: string; purpose?: string };
type Interview = { status: string; confirmed_answers: Record<string, string>; contradictions: Array<Record<string, string>>; next_question: string | null };
type Profile = { version: number; status: string; fields: Record<string, string> } | null;
type SocialConnection = {
  id: string; provider: string; account_id: string | null; account_name: string | null;
  status: string; granted_scopes: string[]; capabilities: Record<string, boolean>;
  last_synced_at: string | null;
};
type ManagedAccount = { id: string; name: string };
type SocialPost = { id: string; provider: string; account_id: string; source_id: string; text: string; provenance: string };
type SocialImport = { id: string; post_count: number; provider: string; account_id: string; rows: Array<{ source_id: string; text: string }> };
type Audit = {
  generated_at: string; timezone: string;
  source_freshness: { last_observed_at: string | null; status: string };
  posts: { value: number; status: string; evidence_ids: string[]; by_provider: Array<{ provider: string; value: number; evidence_ids: string[] }>; items: Array<{ id: string; provider: string; account_id: string; age_days: number | null; provenance: string }> };
  metrics: Array<{ provider: string; account_id: string; metric: string; traffic: string; window_start: string; window_end: string; value: number | null; status: string; observed_posts: number; suppressed_posts: number; missing_posts: number; evidence_ids: string[]; per_post: Array<{ post_id: string; value: number | null; status: string; evidence_id: string }> }>;
  comments: { value: number; status: string; evidence_ids: string[] };
  themes: Array<{ theme: string; value: number; evidence_ids: string[] }>;
  limitations: string[];
};
type AuditEvidence = { id: string; kind: string; post_id: string; observed_at: string; source_ref?: string; source_id?: string; metric?: string; value?: number | null; status?: string; invalidated?: boolean; redacted_text?: string };
type WorkspaceTab = "dashboard" | "operations" | "brand" | "materials" | "social" | "insights" | "calendar" | "studio" | "results";

const socialPlatforms = [
  { id: "facebook_pages", name: "Facebook Pages", capabilities: "Managed Pages, permitted post metrics and comments, supported publishing", fallback: "Import Page exports; prepare a manual publishing package" },
  { id: "instagram", name: "Instagram", capabilities: "Professional identity, media, permitted comments and insights, eligible publishing", fallback: "Upload exports or screenshots; prepare posts, carousels, and stories" },
];

async function jsonRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (!(options?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.detail?.message ?? body?.detail ?? "Request failed.";
    throw new Error(String(message));
  }
  return body as T;
}

export function App() {
  const [health, setHealth] = useState<Health>({ status: "loading" });
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [mode, setMode] = useState<AuthMode>("login");
  const [error, setError] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const currentWorkspace = useRef(workspaceId);
  currentWorkspace.current = workspaceId;
  const [assets, setAssets] = useState<Asset[]>([]);
  const [branding, setBranding] = useState<Branding | null>(null);
  const [profile, setProfile] = useState<Profile>(null);
  const [interview, setInterview] = useState<Interview | null>(null);
  const [phaseError, setPhaseError] = useState("");
  const [busy, setBusy] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("dashboard");
  const [dashboardRefresh, setDashboardRefresh] = useState(0);
  const [newReports, setNewReports] = useState(0);
  const [executionMode, setExecutionMode] = useState("offline_test");
  const [studioSelection, setStudioSelection] = useState<{ planId: string; itemId: string; platform: string; schedule: string } | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [metaReadAvailable, setMetaReadAvailable] = useState(false);
  const [socialConnections, setSocialConnections] = useState<SocialConnection[]>([]);
  const [managedAccounts, setManagedAccounts] = useState<Record<string, ManagedAccount[]>>({});
  const [socialError, setSocialError] = useState("");
  const [socialPosts, setSocialPosts] = useState<SocialPost[]>([]);
  const [socialImport, setSocialImport] = useState<SocialImport | null>(null);
  const [socialImportWorkspace, setSocialImportWorkspace] = useState("");
  const [socialLoadedWorkspace, setSocialLoadedWorkspace] = useState("");
  const [syncJobs, setSyncJobs] = useState<Record<string, { job_id: string; status: string }>>({});
  const [audit, setAudit] = useState<Audit | null>(null);
  const [auditWorkspace, setAuditWorkspace] = useState("");
  const [auditEvidence, setAuditEvidence] = useState<AuditEvidence | null>(null);
  const [auditError, setAuditError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/status", { signal: controller.signal }).then((response) => response.json())
      .then((status: { execution_mode: string }) => setExecutionMode(status.execution_mode)).catch(() => {});
    const timer = window.setTimeout(() => setHealth({ status: "degraded" }), 3000);
    fetch("/health/ready", { signal: controller.signal })
      .then((response) => response.json())
      .then((data: Health) => {
        window.clearTimeout(timer);
        setHealth(data);
      })
      .catch(() => setHealth({ status: "degraded" }));
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, []);

  async function loadSession() {
    try {
      const current = await jsonRequest<CurrentUser>("/api/v1/me");
      const token = await jsonRequest<{ csrf_token: string }>("/api/v1/session/csrf");
      setUser(current);
      setCsrf(token.csrf_token);
      setWorkspaceId((selected) => selected || current.workspaces[0]?.workspace_id || "");
    } catch {
      setUser(null);
      setCsrf("");
    } finally {
      setAuthReady(true);
    }
  }

  useEffect(() => {
    void loadSession();
  }, []);

  async function loadPhase3() {
    if (!workspaceId) return;
    const requestedWorkspace = workspaceId;
    try {
      setPhaseError("");
      const [assetResponse, profileResponse, interviewResponse, brandResponse] = await Promise.all([
        jsonRequest<{ assets: Asset[] }>(`/api/v1/workspaces/${workspaceId}/assets`),
        jsonRequest<{ profile: Profile }>(`/api/v1/workspaces/${workspaceId}/brand`),
        jsonRequest<Interview>(`/api/v1/workspaces/${workspaceId}/onboarding/status`),
        jsonRequest<Branding>(`/api/v1/workspaces/${workspaceId}/branding`),
      ]);
      if (currentWorkspace.current !== requestedWorkspace) return;
      setAssets(assetResponse.assets);
      setProfile(profileResponse.profile);
      setInterview(interviewResponse);
      setBranding(brandResponse);
    } catch (reason) {
      if (currentWorkspace.current === requestedWorkspace) setPhaseError(reason instanceof Error ? reason.message : "Unable to load workspace data.");
    }
  }

  useEffect(() => {
    setAssets([]); setBranding(null); setProfile(null); setInterview(null); setStudioSelection(null);
    void loadPhase3();
  }, [workspaceId]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("social")) setActiveTab("social");
  }, []);

  useEffect(() => {
    if (!workspaceId || !user) return;
    let active = true;
    const load = () => void jsonRequest<{ reports: Array<{ updated_at: string }> }>(`/api/v1/workspaces/${workspaceId}/results`).then((data) => {
      if (!active) return;
      const key = `falkrona-reports-seen:${user.id}:${workspaceId}`;
      if (activeTab === "results") { localStorage.setItem(key, new Date().toISOString()); setNewReports(0); }
      else { const seen = localStorage.getItem(key) ?? ""; setNewReports(data.reports.filter((r) => r.updated_at > seen).length); }
    }).catch(() => {});
    load(); const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [workspaceId, activeTab, user?.id]);

  async function loadSocial() {
    if (!workspaceId) return;
    const requestedWorkspace = workspaceId;
    try {
      setSocialError("");
      const [connections, capabilities, posts] = await Promise.all([
        jsonRequest<{ connections: SocialConnection[] }>(`/api/v1/workspaces/${workspaceId}/social/connections`),
        jsonRequest<{ meta_read_available: boolean }>(`/api/v1/workspaces/${workspaceId}/social/capabilities`),
        jsonRequest<{ posts: SocialPost[] }>(`/api/v1/workspaces/${workspaceId}/social/posts`),
      ]);
      if (currentWorkspace.current !== requestedWorkspace) return;
      setSocialConnections(connections.connections);
      setMetaReadAvailable(capabilities.meta_read_available);
      setSocialPosts(posts.posts);
      setSocialLoadedWorkspace(requestedWorkspace);
      const accountChoices: Record<string, ManagedAccount[]> = {};
      if (user?.workspaces.find((workspace) => workspace.workspace_id === workspaceId)?.role === "owner") {
        for (const connection of connections.connections.filter((item) => item.status === "authorizing")) {
          const response = await jsonRequest<{ accounts: ManagedAccount[] }>(`/api/v1/workspaces/${workspaceId}/social/connections/${connection.id}/accounts`);
          accountChoices[connection.id] = response.accounts;
        }
      }
      if (currentWorkspace.current === requestedWorkspace) setManagedAccounts(accountChoices);
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Unable to load social connections.");
    }
  }

  useEffect(() => {
    if (activeTab === "social") void loadSocial();
  }, [activeTab, workspaceId, user]);

  async function loadAudit() {
    if (!workspaceId) return;
    const requestedWorkspace = workspaceId;
    try {
      setAuditError("");
      const result = await jsonRequest<Audit>(`/api/v1/workspaces/${workspaceId}/analytics/audit`);
      if (currentWorkspace.current !== requestedWorkspace) return;
      setAudit(result);
      setAuditWorkspace(requestedWorkspace);
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "Unable to load audit.");
    }
  }

  useEffect(() => {
    setAuditEvidence(null);
    if (activeTab === "insights") void loadAudit();
  }, [activeTab, workspaceId]);

  async function submitMetric(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy("audit-metric");
    try {
      if (data.get("status") === "observed" && String(data.get("value") ?? "").trim() === "") {
        throw new Error("Enter an observed value, including 0 when the source says zero.");
      }
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/analytics/metrics`, {
        method: "POST", headers: { "X-CSRF-Token": csrf },
        body: JSON.stringify({
          post_id: data.get("post_id"), metric: data.get("metric"), traffic: data.get("traffic"),
          status: data.get("status"), value: data.get("status") === "suppressed" ? null : Number(data.get("value")),
          window_start: new Date(String(data.get("window_start"))).toISOString(),
          window_end: new Date(String(data.get("window_end"))).toISOString(), source_ref: data.get("source_ref"),
        }),
      });
      form.reset();
      await loadAudit();
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "Unable to record metric.");
    } finally { setBusy(""); }
  }

  async function submitComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy("audit-comment");
    try {
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/analytics/comments`, {
        method: "POST", headers: { "X-CSRF-Token": csrf },
        body: JSON.stringify({ post_id: data.get("post_id"), source_ref: data.get("source_ref"), text: data.get("text") }),
      });
      form.reset();
      await loadAudit();
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "Unable to record comment.");
    } finally { setBusy(""); }
  }

  async function showEvidence(id: string) {
    try {
      setAuditError("");
      const result = await jsonRequest<AuditEvidence>(`/api/v1/workspaces/${workspaceId}/analytics/evidence/${id}`);
      setAuditEvidence(result);
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "Evidence is unavailable.");
    }
  }

  async function invalidateEvidence() {
    if (!auditEvidence || auditEvidence.kind === "post") return;
    setBusy("audit-invalidate");
    try {
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/analytics/${auditEvidence.kind}/${auditEvidence.id}/invalidate`, {
        method: "POST", headers: { "X-CSRF-Token": csrf },
      });
      setAuditEvidence(null);
      await loadAudit();
    } catch (reason) {
      setAuditError(reason instanceof Error ? reason.message : "Unable to invalidate evidence.");
    } finally { setBusy(""); }
  }

  async function beginFacebook(publishing = false) {
    setBusy("meta");
    try {
      const result = await jsonRequest<{ authorization_url: string }>(`/api/v1/workspaces/${workspaceId}/social/meta/authorize`, {
        method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ publishing }),
      });
      window.location.assign(result.authorization_url);
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Facebook authorization could not start.");
      setBusy("");
    }
  }

  async function selectMetaAccount(event: FormEvent<HTMLFormElement>, connectionId: string) {
    event.preventDefault();
    setBusy(connectionId);
    try {
      const accountId = String(new FormData(event.currentTarget).get("account_id") ?? "");
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/social/connections/${connectionId}/account`, {
        method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ account_id: accountId }),
      });
      await loadSocial();
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Page selection failed.");
    } finally {
      setBusy("");
    }
  }

  async function disconnectMeta(connectionId: string) {
    setBusy(connectionId);
    try {
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/social/connections/${connectionId}`, {
        method: "DELETE", headers: { "X-CSRF-Token": csrf },
      });
      await loadSocial();
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Disconnect failed.");
    } finally {
      setBusy("");
    }
  }

  async function submitSocialImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("social-import");
    try {
      const data = new FormData(event.currentTarget);
      const preview = await jsonRequest<SocialImport>(`/api/v1/workspaces/${workspaceId}/social/imports`, {
        method: "POST", headers: { "X-CSRF-Token": csrf }, body: data,
      });
      if (currentWorkspace.current === workspaceId) {
        setSocialImport(preview);
        setSocialImportWorkspace(workspaceId);
      }
      setSocialError("");
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Post import failed.");
    } finally {
      setBusy("");
    }
  }

  async function confirmSocialImport() {
    if (!socialImport || socialImportWorkspace !== workspaceId) return;
    setBusy("social-confirm");
    try {
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/social/imports/${socialImport.id}/confirm`, {
        method: "POST", headers: { "X-CSRF-Token": csrf },
      });
      setSocialImport(null);
      await loadSocial();
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Post confirmation failed.");
    } finally {
      setBusy("");
    }
  }

  async function queueMetaSync(connectionId: string) {
    setBusy(connectionId);
    try {
      const job = await jsonRequest<{ job_id: string; status: string }>(`/api/v1/workspaces/${workspaceId}/social/connections/${connectionId}/sync`, {
        method: "POST", headers: { "X-CSRF-Token": csrf },
        body: JSON.stringify({ dedupe_key: `sync-${Date.now()}` }),
      });
      setSyncJobs((current) => ({ ...current, [connectionId]: job }));
      setSocialError("");
    } catch (reason) {
      setSocialError(reason instanceof Error ? reason.message : "Post sync could not start.");
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    if (activeTab !== "social" || !workspaceId || !Object.values(syncJobs).some((job) => ["queued", "running"].includes(job.status))) return;
    const timer = window.setInterval(() => {
      void Promise.all(Object.entries(syncJobs).filter(([, job]) => ["queued", "running"].includes(job.status)).map(async ([connectionId, job]) => {
        try {
          const update = await jsonRequest<{ status: string }>(`/api/v1/workspaces/${workspaceId}/jobs/${job.job_id}`);
          setSyncJobs((current) => ({ ...current, [connectionId]: { ...job, status: update.status } }));
          if (update.status === "completed") void loadSocial();
        } catch {
          setSocialError("Unable to refresh sync status.");
        }
      }));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeTab, workspaceId, syncJobs]);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "");
    const password = String(data.get("password") ?? "");
    try {
      if (mode === "setup") {
        await jsonRequest("/api/v1/setup/owner", {
          method: "POST",
          headers: { "X-Setup-Token": String(data.get("setupToken") ?? "") },
          body: JSON.stringify({
            email,
            password,
            workspace_name: String(data.get("workspaceName") ?? ""),
          }),
        });
      }
      const grant = await jsonRequest<{ csrf_token: string }>("/api/v1/session", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setCsrf(grant.csrf_token);
      await loadSession();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to continue.");
    }
  }

  async function signOut() {
    try {
      await fetch("/api/v1/session", {
        method: "DELETE",
        credentials: "include",
        headers: { "X-CSRF-Token": csrf },
      });
    } finally {
      setUser(null);
      setCsrf("");
      setWorkspaceId("");
    }
  }

  async function submitAsset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy("asset");
    try {
      const data = new FormData(form);
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/assets`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: data });
      form.reset();
      setPhaseError("");
      await loadPhase3();
    } catch (reason) {
      setPhaseError(reason instanceof Error ? reason.message : "Upload failed.");
    } finally {
      setBusy("");
    }
  }

  async function submitImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy("import");
    try {
      const data = new FormData(form);
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/imports`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: data });
      form.reset();
      setPhaseError("");
    } catch (reason) {
      setPhaseError(reason instanceof Error ? reason.message : "Import failed.");
    } finally {
      setBusy("");
    }
  }

  async function submitUrlImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy("url");
    try {
      const data = new FormData(form);
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/imports/url`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ url: data.get("url"), dedupe_key: data.get("dedupe_key") }) });
      form.reset();
      setPhaseError("");
    } catch (reason) {
      setPhaseError(reason instanceof Error ? reason.message : "Website import failed.");
    } finally {
      setBusy("");
    }
  }

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("profile");
    try {
      const data = new FormData(event.currentTarget);
      const fields = Object.fromEntries([...data.entries()].filter(([, value]) => String(value).trim()));
      const proposal = await jsonRequest<{ version: number }>(`/api/v1/workspaces/${workspaceId}/brand/proposals`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ fields }) });
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/brand/versions/${proposal.version}/confirm`, { method: "POST", headers: { "X-CSRF-Token": csrf } });
      await loadPhase3();
    } catch (reason) {
      setPhaseError(reason instanceof Error ? reason.message : "Profile update failed.");
    } finally {
      setBusy("");
    }
  }

  async function submitInterview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!interview?.next_question) return;
    setBusy("interview");
    try {
      const data = new FormData(form);
      await jsonRequest(`/api/v1/workspaces/${workspaceId}/interview/turns`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ question_key: interview.next_question, answer: String(data.get("answer") ?? ""), confirmed: true }) });
      form.reset();
      await loadPhase3();
    } catch (reason) {
      setPhaseError(reason instanceof Error ? reason.message : "Interview update failed.");
    } finally {
      setBusy("");
    }
  }

  if (!authReady) {
    return <div className="loading-screen">Checking session...</div>;
  }

  if (!user) {
    return (
      <main className="auth-layout">
        <section className="auth-panel" aria-labelledby="auth-title">
          <div className="auth-brand">
            <div className="brand-lockup">
              <div className="brand-mark"><span>FK</span></div>
              <div className="brand-copy"><strong>FALKRONA</strong><span className="tagline">Your Brand's Pilot</span></div>
            </div>
          </div>
          <div className="auth-heading">
            <LockKeyhole size={22} />
            <div>
              <p className="eyebrow">{mode === "login" ? "WELCOME BACK" : "YOUR FIRST WORKSPACE"}</p>
              <h1 id="auth-title">{mode === "login" ? "Sign in" : "Set up the owner"}</h1>
            </div>
          </div>
          <form onSubmit={submitAuth}>
            {mode === "setup" && <label>Workspace name<input name="workspaceName" required maxLength={160} autoComplete="organization" /></label>}
            <label>Email<input name="email" type="email" required autoComplete="email" /></label>
            <label>Password<input name="password" type="password" required minLength={12} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
            {mode === "setup" && <label>Local setup token<input name="setupToken" type="password" required autoComplete="off" /></label>}
            {error && <p className="form-error" role="alert">{error}</p>}
            <button className="primary" type="submit">{mode === "login" ? <LogIn size={17} /> : <UserPlus size={17} />}{mode === "login" ? "Sign in" : "Create owner"}</button>
          </form>
          <details className="auth-setup"><summary>First-time workspace setup</summary><button className="text-button" onClick={() => setMode(mode === "login" ? "setup" : "login")} type="button">{mode === "login" ? "Set up the owner" : "Back to sign in"}</button></details>
        </section>
      </main>
    );
  }

  const database = componentStatus(health, "database");
  const storage = componentStatus(health, "storage");
  const workspaceOwner = user.workspaces.find((workspace) => workspace.workspace_id === workspaceId)?.role === "owner";
  const workspaceRole = user.workspaces.find((workspace) => workspace.workspace_id === workspaceId)?.role;
  const visibleSocialConnections = socialLoadedWorkspace === workspaceId ? socialConnections : [];
  const visibleSocialPosts = socialLoadedWorkspace === workspaceId ? socialPosts : [];
  const visibleSocialImport = socialImportWorkspace === workspaceId ? socialImport : null;
  const visibleAudit = auditWorkspace === workspaceId ? audit : null;
  const brandName = branding?.answers.brand_name || user.workspaces.find(workspace => workspace.workspace_id === workspaceId)?.name || "Your brand";
  const productPhotos = assets.filter(asset => asset.purpose === "product" && /^image\//.test(asset.mime_type) && ![branding?.logo_asset_id, branding?.reference_asset_id].includes(asset.id) && asset.source === "upload");
  const sections = [
    { id: "dashboard", label: "Dashboard", arabic: "لوحة التحكم", icon: LayoutDashboard },
    { id: "brand", label: "Brand", arabic: "هوية العلامة", icon: Building2 },
    { id: "social", label: "Social accounts", arabic: "الحسابات الاجتماعية", icon: Share2 },
    { id: "calendar", label: "Content plan", arabic: "خطة المحتوى", icon: CalendarDays },
    { id: "studio", label: "Creative studio", arabic: "استوديو التصميم", icon: Image },
  ] as const;
  const subtitles: Record<string, string> = { brand: "A little about your brand. A lot of possibilities.", materials: "Your products, ready for their moment.", social: "Bring your accounts together and keep track of your posts.", calendar: "From a good idea to a whole week of content.", studio: "Make something your audience will love.", results: "See what’s working, and what to try next." };
  const hour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "numeric", hourCycle: "h23" }).format(new Date()));
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const pageTitle = activeTab === "materials" ? "Products" : activeTab === "results" ? "Weekly reports" : sections.find(section => section.id === activeTab)?.[language === "ar" ? "arabic" : "label"] ?? "Your workspace";
  const chooseWorkspace = (id: string) => { setAssets([]); setBranding(null); setProfile(null); setInterview(null); setStudioSelection(null); setWorkspaceId(id); };
  const openSavedPost = (planId: string, itemId: string, platform: string, schedule: string) => { setStudioSelection({ planId, itemId, platform, schedule: cairoInput(schedule) }); setActiveTab("studio"); };

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-topline">
          <div className="brand-lockup" aria-label="Falkrona"><div className="brand-mark"><span>F</span></div><div className="brand-copy"><strong>FALKRONA</strong></div></div>
          <button className="sidebar-toggle" type="button" onClick={() => setSidebarCollapsed((collapsed) => !collapsed)} aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {sidebarCollapsed ? <PanelRightOpen size={18} /> : <PanelRightClose size={18} />}
          </button>
        </div>
        <nav className="workspace-tabs" aria-label="Workspace sections">
          {sections.map(section => <button key={section.id} className={activeTab === section.id || section.id === "brand" && activeTab === "materials" || section.id === "dashboard" && activeTab === "results" ? "active" : ""} type="button" onClick={() => setActiveTab(section.id)} title={section.label} aria-current={activeTab === section.id || section.id === "brand" && activeTab === "materials" || section.id === "dashboard" && activeTab === "results" ? "page" : undefined}><section.icon size={19} /><span className="nav-label">{language === "ar" ? section.arabic : section.label}</span></button>)}
        </nav>
        <div className="sidebar-bottom"><button className="sidebar-report" onClick={() => setActiveTab("results")}><BarChart3 size={18}/><span className="nav-label">Weekly reports<small>Every Monday</small></span>{newReports > 0 ? <span className="report-badge" aria-label={`${newReports} new weekly reports`}>{newReports}</span> : <ArrowUpRight size={15}/>}</button><div className="mode"><RadioTower size={14}/><span className="nav-label">{executionMode === "offline_test" ? "Offline preview" : "Powered by Gemini"}</span></div></div>
      </aside>
      <main id="operations" dir={language === "ar" ? "rtl" : "ltr"}>
        <header className="app-topbar">
          <label className="topbar-brand"><span className="sr-only">Choose brand workspace</span><select aria-label="Brand workspace" value={workspaceId} onChange={event => chooseWorkspace(event.target.value)}>{user.workspaces.map(workspace => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.workspace_id === workspaceId ? brandName : workspace.name}</option>)}</select></label>
          <div className="topbar-actions"><span className="date-pill"><CalendarDays size={17}/>Week of {new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${currentCairoWeek()}T12:00:00Z`))}</span><button className="icon-button language-toggle" type="button" onClick={() => setLanguage(language === "en" ? "ar" : "en")} aria-label="Switch interface language" title="Switch interface language"><Languages size={17}/>{language.toUpperCase()}</button><span className={`service-dot status-${health.status}`} title={`Service: ${health.status}`} aria-label={`Service: ${health.status}`}/><details className="profile-menu"><summary aria-label="Account menu"><span className="avatar-initials">{user.email.slice(0, 2).toUpperCase()}</span></summary><div className="profile-popover"><strong>Your account</strong><span>{user.email}</span><button className="icon-button" onClick={signOut}><LogOut size={16}/> Sign out</button></div></details></div>
        </header>
        <div className="workspace-page">
          <div className="page-intro"><div><h1>{activeTab === "dashboard" ? (language === "ar" ? "أهلاً بك في فالكرونا" : `${greeting}.`) : pageTitle}</h1><p>{activeTab === "dashboard" ? `Here’s what’s happening with ${brandName} this week.` : subtitles[activeTab]}</p></div>{activeTab === "dashboard" && <button className="icon-button refresh-overview" aria-label="Refresh dashboard" onClick={() => {setDashboardRefresh(value => value + 1); void loadPhase3();}}><RefreshCw size={17}/></button>}</div>
          {activeTab === "dashboard" && <DashboardView key={`${workspaceId}:${dashboardRefresh}`} workspaceId={workspaceId} branding={branding} hasProduct={productPhotos.length > 0} navigate={setActiveTab} openPost={openSavedPost}/>}
        {phaseError && <p className="form-error phase-error" role="alert">{phaseError}</p>}
        {["brand", "materials"].includes(activeTab) && <nav className="brand-subnav" aria-label="Brand setup"><button className={activeTab === "brand" ? "selected" : ""} onClick={() => setActiveTab("brand")}>Brand details</button><button className={activeTab === "materials" ? "selected" : ""} onClick={() => setActiveTab("materials")}>Product photos</button></nav>}
        {activeTab === "results" && <ResultsView key={workspaceId} workspaceId={workspaceId} csrf={csrf} canEdit={workspaceRole === "owner" || workspaceRole === "editor"} openCalendar={() => setActiveTab("calendar")} />}
        {activeTab === "brand" && <BrandingView key={workspaceId} workspaceId={workspaceId} csrf={csrf} canEdit={workspaceRole === "owner" || workspaceRole === "editor"} onSaved={(value) => { setBranding(value); void loadPhase3(); }} openPlan={() => setActiveTab("calendar")} />}
        {activeTab === "materials" && <section className="queue" aria-labelledby="assets-title">
          <div className="section-heading"><div><h2 id="assets-title">Add a product photo</h2></div></div>
          <div className="product-upload-area">
            <form className="tool-panel" onSubmit={submitAsset}><div className="tool-title"><Image size={18} /><div><strong>Product photos</strong><span>Add a real photo of your product</span></div></div><label>File<input name="file" type="file" required accept=".png,.jpg,.jpeg,.webp" /></label><button className="primary" disabled={busy === "asset"} type="submit"><Upload size={16} />{busy === "asset" ? "Uploading..." : "Add to gallery"}</button></form>
            <details><summary>Have a product catalog? Import a file</summary><form className="catalog-import" onSubmit={submitImport}><input name="dedupe_key" type="hidden" value={`catalog-${Date.now()}`} /><label>CSV or Excel catalog<input name="file" type="file" required accept=".csv,.xlsx" /></label><button className="icon-button" disabled={busy === "import"} type="submit"><Upload size={16} />{busy === "import" ? "Previewing..." : "Preview import"}</button></form></details>
          </div>
          <div className="product-gallery"><div className="section-heading"><h2>Product photos</h2><span>{productPhotos.length} photo{productPhotos.length === 1 ? "" : "s"}</span></div>{productPhotos.length === 0 ? <div className="empty-state">Add your first product photo above.</div> : <div className="product-grid">{productPhotos.map(asset => <figure className="product-card" key={asset.id}><AssetImage workspaceId={workspaceId} assetId={asset.id} alt={asset.name}/><figcaption>{asset.name}<small>{Math.ceil(asset.size / 1024)} KB</small></figcaption></figure>)}</div>}</div>
          <div className="asset-purpose-groups">{([['logo','Logos'],['reference','Design references'],['document','Documents']] as const).map(([purpose,label])=>{const group=assets.filter(asset=>asset.purpose===purpose&&asset.source==='upload');return group.length>0&&<details key={purpose}><summary>{label} <span>{group.length}</span></summary><div className="product-grid">{group.map(asset=><figure className="product-card" key={asset.id}>{asset.mime_type.startsWith('image/')&&<AssetImage workspaceId={workspaceId} assetId={asset.id} alt={asset.name}/>}<figcaption>{asset.name}<small>{label}</small></figcaption></figure>)}</div></details>;})}</div>
        </section>}
        {activeTab === "calendar" && <CalendarView key={workspaceId} workspaceId={workspaceId} csrf={csrf} assets={assets} canEdit={workspaceRole === "owner" || workspaceRole === "editor"} canApprove={workspaceRole === "owner"} openBrand={() => setActiveTab("brand")} openStudio={(planId, itemId, platform, schedule) => { setStudioSelection({ planId, itemId, platform, schedule }); setActiveTab("studio"); }} />}
        {activeTab === "studio" && <StudioView key={workspaceId} workspaceId={workspaceId} csrf={csrf} selection={studioSelection} assets={assets} branding={branding} openBrand={() => setActiveTab("brand")} refreshAssets={loadPhase3} canEdit={workspaceRole === "owner" || workspaceRole === "editor"} canApprove={workspaceRole === "owner"} openCalendar={() => setActiveTab("calendar")} />}
        {activeTab === "social" && <section className="queue" aria-labelledby="social-title">
          <div className="section-heading"><div><p className="eyebrow">SOCIAL CONNECTIONS</p><h2 id="social-title">Your social accounts</h2></div><span>{visibleSocialConnections.filter((item) => item.account_id && item.status !== "disconnected").length} account(s)</span></div>
          <p className="muted social-disclosure">Connect your accounts for daily post tracking and weekly results. Your logo and design example are uploaded in Branding.</p>
          {socialError && <p className="form-error social-error" role="alert">{socialError}</p>}
          {!metaReadAvailable && <p className="muted">Account connections are unavailable in this preview. You can add a post export below.</p>}
          <div className="phase-grid social-grid">{socialPlatforms.map((platform) => <article className="tool-panel social-panel" key={platform.id}>
            <div className="tool-title">{platform.id === "instagram" ? <Instagram size={18} /> : <Facebook size={18} />}<strong>{platform.name}</strong></div>
            {visibleSocialConnections.filter((c) => platform.id === "instagram" ? c.provider === "instagram" : c.provider === "meta" || c.provider === "facebook_pages").map((connection) => <div className="social-connection" key={connection.id}>
              <strong>{connection.account_name ?? "Choose your account"}</strong>
              <span>{connection.status === "connected_partial" ? "Connected for post tracking" : connection.status === "needs_reauth" ? "Please reconnect this account" : connection.status === "permission_missing" ? "Post access was not granted" : connection.status === "authorizing" ? "Choose an account below" : connection.status === "disconnected" ? "Disconnected" : "Waiting for the platform"}</span>
              {connection.last_synced_at && <span>Last checked: {new Date(connection.last_synced_at).toLocaleDateString()}</span>}
              {connection.status === "authorizing" && workspaceOwner && <form onSubmit={(event) => void selectMetaAccount(event, connection.id)}>
                <label>{platform.id === "instagram" ? "Your Instagram account" : "Your Facebook Page"}<select name="account_id" required>{(managedAccounts[connection.id] ?? []).filter((account) => platform.id === "instagram" ? account.id.startsWith("ig:") : !account.id.startsWith("ig:")).map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
                <button className="primary" type="submit" disabled={busy === connection.id || !managedAccounts[connection.id]?.some((account) => platform.id === "instagram" ? account.id.startsWith("ig:") : !account.id.startsWith("ig:"))}>Use this account</button>
              </form>}
              {workspaceOwner && connection.capabilities.posts && <button className="icon-button" type="button" disabled={busy === connection.id || ["queued", "running"].includes(syncJobs[connection.id]?.status ?? "")} onClick={() => void queueMetaSync(connection.id)}><RefreshCw size={16} /> Check posts now</button>}
              {syncJobs[connection.id] && <span>{["queued", "running"].includes(syncJobs[connection.id].status) ? "Checking your posts…" : syncJobs[connection.id].status === "completed" ? "Posts updated" : "Please try checking again"}</span>}
              {connection.capabilities.posts && <span>{connection.capabilities.publish ? "Publishing is available" : connection.granted_scopes.includes("pages_manage_posts") ? "Publishing permission granted. Automatic delivery is not enabled yet." : "Post tracking is available. Publishing permission is needed."}</span>}
              {workspaceOwner && platform.id === "facebook_pages" && connection.capabilities.posts && !connection.granted_scopes.includes("pages_manage_posts") && <button className="icon-button" type="button" disabled={busy === "meta" || !metaReadAvailable} onClick={() => void beginFacebook(true)}><LockKeyhole size={16} /> Allow publishing access</button>}
              {workspaceOwner && connection.status !== "disconnected" && <button className="icon-button" type="button" disabled={busy === connection.id} onClick={() => void disconnectMeta(connection.id)}>Disconnect</button>}
            </div>)}
            <p className="muted">{platform.id === "instagram" ? "Use a professional Instagram account linked to your Facebook Page." : "Connect a Page you manage to track its published posts."}</p>
            {workspaceOwner && (platform.id === "facebook_pages" ? <button className="primary" type="button" disabled={!metaReadAvailable || busy === "meta"} onClick={() => void beginFacebook()}><Facebook size={16} /> Connect Facebook</button> : <><p className="muted">Instagram connection setup is pending.</p><button className="primary" type="button" disabled><Instagram size={16} /> Connect Instagram</button></>)}
          </article>)}</div>
          <details className="social-history" open={visibleSocialImport ? true : undefined}><summary>Post history and optional imports</summary><div className="section-heading social-import-heading"><div><h2>Post history</h2></div><span>{visibleSocialPosts.length} imported post(s) <a className="icon-button social-export" href={`/api/v1/workspaces/${workspaceId}/social/posts/export`} download="falkrona-social-posts.csv" title="Export social posts as CSV"><Download size={16} /> Export CSV</a></span></div>
          <div className="phase-grid social-grid">
            <form className="tool-panel" onSubmit={submitSocialImport}>
              <div className="tool-title"><FileSpreadsheet size={18} /><div><strong>Add a post export</strong><span>Optional: include likes, comments, shares and saves</span></div></div>
              <label>Platform<select name="provider" required>{socialPlatforms.map((platform) => <option key={platform.id} value={platform.id}>{platform.name}</option>)}</select></label>
              <label>Account ID or label<input name="account_id" required maxLength={160} /></label>
              <input name="dedupe_key" type="hidden" value={`social-${Date.now()}`} />
              <label>CSV file<input name="file" type="file" required accept=".csv,text/csv" /></label>
              <button className="primary" type="submit" disabled={busy === "social-import"}><Upload size={16} /> Preview import</button>
            </form>
            <div className="tool-panel">
              <div className="tool-title"><FileSpreadsheet size={18} /><div><strong>Import preview</strong><span>{visibleSocialImport ? `${visibleSocialImport.post_count} posts · ${visibleSocialImport.provider}` : "No pending import"}</span></div></div>
              {visibleSocialImport && <><ul className="asset-list">{visibleSocialImport.rows.slice(0, 5).map((row) => <li key={row.source_id}><span>{row.source_id}</span><small>{row.text || "Media post"}</small></li>)}</ul><button className="primary" type="button" disabled={busy === "social-confirm"} onClick={() => void confirmSocialImport()}><CheckCircle2 size={16} /> Confirm import</button></>}
            </div>
          </div>
          {visibleSocialPosts.length > 0 && <div className="social-post-list" aria-label="Imported social posts">{visibleSocialPosts.map((post) => <div className="workspace-row" key={post.id}><Share2 size={17} /><div><strong>{post.text || post.source_id}</strong><span>{post.provider.replaceAll("_", " ")} · {post.account_id} · {post.provenance.replaceAll("_", " ")}</span></div></div>)}</div>}
          </details>
        </section>}
        </div>
      </main>
    </div>
  );
}
