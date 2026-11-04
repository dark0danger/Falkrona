import { FormEvent, useEffect, useState } from "react";
import { csrfFetch } from "./csrfFetch";

type Feedback = { id: string; design_version_id: string; original_text: string; interpretation: string;
  category: string; kind: string; scope: string; scope_key: string; status: string };
type Preference = { id: string; feedback_id: string; scope: string; scope_key: string;
  category: string; instruction: string; version: number; status: string };

async function request<T>(path: string, csrf: string, options?: RequestInit): Promise<T> {
  const response = await csrfFetch(path, { credentials: "include", ...options, headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf, ...options?.headers,
  } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body?.detail?.message ?? "Request failed."));
  return body as T;
}

export function LearningPanel({ workspaceId, designId, csrf, canEdit, canApprove }: {
  workspaceId: string; designId: string; csrf: string; canEdit: boolean; canApprove: boolean;
}) {
  const base = `/api/v1/workspaces/${workspaceId}`;
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [scope, setScope] = useState("future");
  const [category, setCategory] = useState("copy");
  const [original, setOriginal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const [notes, rules] = await Promise.all([
      request<Feedback[]>(`${base}/designs/${designId}/feedback`, csrf),
      request<Preference[]>(`${base}/learning`, csrf),
    ]);
    setFeedback(notes); setPreferences(rules);
  }

  useEffect(() => { let live = true;
    void Promise.all([request<Feedback[]>(`${base}/designs/${designId}/feedback`, csrf),
      request<Preference[]>(`${base}/learning`, csrf)])
      .then(([notes, rules]) => { if (live) { setFeedback(notes); setPreferences(rules); } })
      .catch((reason) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [workspaceId, designId, csrf]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const note = await request<Feedback>(`${base}/designs/${designId}/feedback`, csrf, { method: "POST",
        body: JSON.stringify({ original_text: original, interpretation: original, category, kind: "preference", scope }) });
      if (scope === "future" && canApprove) {
        const active = preferences.find(rule => rule.status === "active" && rule.scope === "future" && rule.category === category);
        await request(`${base}/feedback/${note.id}/approve`, csrf, {method:"POST",body:JSON.stringify({supersedes_id:active?.id??null})});
      }
      setOriginal(""); await refresh();
    } catch (reason) { setError(String(reason)); await refresh().catch(()=>{}); } finally { setBusy(false); }
  }

  async function decide(id: string, approve: boolean, supersedesId?: string) {
    setBusy(true); setError("");
    try {
      await request(`${base}/feedback/${id}/${approve ? "approve" : "reject"}`, csrf,
        { method: "POST", body: approve ? JSON.stringify({ supersedes_id: supersedesId || null }) : "{}" });
      await refresh();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }

  async function revert(id: string) {
    setBusy(true); setError("");
    try { await request(`${base}/learning/${id}/revert`, csrf, { method: "POST", body: "{}" }); await refresh(); }
    catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }

  const activeRules = preferences.filter(rule=>rule.status==="active");
  const existing = activeRules.find(rule=>rule.scope==="future"&&rule.category===category);
  return <div className="studio-learning">
    {error && <p className="form-error" role="alert">{error}</p>}
    {canEdit && <form className="studio-fields" onSubmit={event=>void submit(event)}>
      <label>What would you change?<textarea required maxLength={1000} value={original} onChange={event=>setOriginal(event.target.value)} placeholder="For example: use simple Arabic, short headlines and no exaggerated claims."/></label>
      <label>About<select value={category} onChange={event=>setCategory(event.target.value)}><option value="copy">Writing</option><option value="layout">Design</option></select></label>
      <label className="week-consent"><input type="checkbox" checked={scope==="future"} onChange={event=>setScope(event.target.checked?"future":"post")}/> Use this for future posts too</label>
      {scope==="future"&&existing&&<p className="muted">Replaces your saved {category==="copy"?"writing":"design"} preference: “{existing.instruction}”</p>}
      <button className="primary" disabled={busy||!original.trim()} type="submit">{busy?"Saving…":scope==="future"?"Save preference":"Save for this post"}</button>
      <small className="muted">Applied next time you create or regenerate a design.</small>
    </form>}
    {feedback.filter(note=>note.status==="pending").map(note=><div className="studio-learning-entry" key={note.id}><p>{note.original_text}</p><small>Awaiting owner approval</small>{canApprove&&<div className="studio-actions"><button className="icon-button" disabled={busy} onClick={()=>void decide(note.id,true,activeRules.find(rule=>rule.scope===note.scope&&rule.scope_key===note.scope_key&&rule.category===note.category)?.id)}>Use this preference</button><button className="text-button" disabled={busy} onClick={()=>void decide(note.id,false)}>Dismiss</button></div>}</div>)}
    {activeRules.length>0&&<div className="saved-preferences"><h3>Saved for your brand</h3>{activeRules.map(rule=><div className="studio-learning-entry" key={rule.id}><p>{rule.instruction}</p>{canApprove&&<button className="text-button" disabled={busy} onClick={()=>void revert(rule.id)}>Forget</button>}</div>)}</div>}
    {feedback.some(note=>note.status==="local_only")&&<details><summary>Notes for this post</summary>{feedback.filter(note=>note.status==="local_only").map(note=><p key={note.id}>{note.original_text}</p>)}</details>}
  </div>;
}
