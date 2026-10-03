import { Check, Download, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

type Approval = { id: string; design_version_id: string; destination_platform: string;
  destination_account_id: string; scheduled_at_utc: string; schedule_local: string;
  delivery_mode: string; status: string; attempt: { status: string; exported_at: string | null } | null };
type Connection = { id: string; provider: string; account_id: string | null; account_name: string | null;
  status: string; capabilities: Record<string, boolean> };

async function request<T>(path: string, csrf: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...options, headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf, ...options?.headers,
  } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body?.detail?.message ?? "Request failed."));
  return body as T;
}

export function PublicationPanel({ workspaceId, designId, platform, initialSchedule, csrf,
  canApprove, saved }: { workspaceId: string; designId: string; platform: string;
    initialSchedule: string; csrf: string; canApprove: boolean; saved: boolean }) {
  const base = `/api/v1/workspaces/${workspaceId}`;
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [schedule, setSchedule] = useState(initialSchedule);
  const [fold, setFold] = useState("");
  const [factsReviewed, setFactsReviewed] = useState(false);
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setApprovals(await request<Approval[]>(`${base}/designs/${designId}/publication-approvals`, csrf));
  }

  useEffect(() => {
    let live = true;
    void Promise.all([request<Approval[]>(`${base}/designs/${designId}/publication-approvals`, csrf),
      request<{ connections: Connection[] }>(`${base}/social/connections`, csrf)])
      .then(([items, result]) => { if (live) { setApprovals(items); setConnections(result.connections); } })
      .catch((reason) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [workspaceId, designId, csrf]);

  async function approve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await request(`${base}/designs/${designId}/publication-approvals`, csrf, {
        method: "POST", body: JSON.stringify({ platform, account_id: accountId,
          connection_id: connectionId || null, schedule_local: schedule,
          fold: fold === "" ? null : Number(fold), idempotency_key: requestKey,
          facts_reviewed: factsReviewed }),
      });
      setRequestKey(crypto.randomUUID()); setFactsReviewed(false); await refresh();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }

  async function cancel(id: string) {
    setBusy(true); setError("");
    try { await request(`${base}/publication-approvals/${id}/cancel`, csrf,
      { method: "POST", body: "{}" }); await refresh(); }
    catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }

  async function download(id: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${base}/publication-approvals/${id}/manual-package`,
        { method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrf } });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(String(body?.detail?.message ?? "Package is unavailable."));
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url;
      link.download = `falkrona-approved-${id}.zip`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      await refresh();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }

  const pageConnections = connections.filter((connection) => connection.provider === "meta"
    && connection.account_id && ["connected", "connected_partial"].includes(connection.status));
  return <div className="publication-panel">
    <h3>Publication approval</h3>
    {error && <p className="form-error" role="alert">{error}</p>}
    {canApprove && <form className="publication-form" onSubmit={(event) => void approve(event)}>
      <label>Destination<select value={connectionId} onChange={(event) => {
        const id = event.target.value; setConnectionId(id);
        if (id) setAccountId(pageConnections.find((entry) => entry.id === id)?.account_id ?? "");
      }}><option value="">Manual account</option>
        {platform === "facebook_pages" && pageConnections.map((entry) =>
          <option value={entry.id} key={entry.id}>{entry.account_name ?? entry.account_id}</option>)}
      </select></label>
      <label>Account or Page<input value={accountId} maxLength={160} required
        readOnly={Boolean(connectionId)} onChange={(event) => setAccountId(event.target.value)} /></label>
      <label>Cairo date & time<input type="datetime-local" value={schedule} required
        onChange={(event) => setSchedule(event.target.value)} /></label>
      <label>Repeated hour<select value={fold} onChange={(event) => setFold(event.target.value)}>
        <option value="">Automatic</option><option value="0">First occurrence</option>
        <option value="1">Second occurrence</option></select></label>
      <label className="publication-confirm"><input type="checkbox" checked={factsReviewed}
        onChange={(event) => setFactsReviewed(event.target.checked)} /> I reviewed this exact artwork, copy, facts, destination and time</label>
      <button className="primary" type="submit" disabled={!saved || !factsReviewed || busy || !accountId.trim()}>
        <Check size={16} /> Approve manual package</button>
    </form>}
    <div className="publication-list">{approvals.map((approval) => <div className="publication-row" key={approval.id}>
      <div><strong>{approval.destination_account_id}</strong><span>{approval.destination_platform.replaceAll("_", " ")} · {approval.schedule_local} Cairo · {approval.status}</span>
        <small>{approval.attempt?.status ?? "No attempt"} · Export only</small></div>
      {canApprove && approval.status === "approved" && <div className="studio-actions">
        <button className="icon-button" type="button" disabled={busy} onClick={() => void download(approval.id)}
          title="Download exact approved revision"><Download size={16} /> Package</button>
        <button className="icon-button" type="button" disabled={busy} onClick={() => void cancel(approval.id)}
          title="Cancel approval"><X size={16} /> Cancel</button>
      </div>}
    </div>)}</div>
  </div>;
}
