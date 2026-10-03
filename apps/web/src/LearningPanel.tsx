import { Check, RotateCcw, X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

type Feedback = { id: string; design_version_id: string; original_text: string; interpretation: string;
  category: string; kind: string; scope: string; scope_key: string; status: string };
type Preference = { id: string; feedback_id: string; scope: string; scope_key: string;
  category: string; instruction: string; version: number; status: string };

async function request<T>(path: string, csrf: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...options, headers: {
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
  const [scope, setScope] = useState("post");
  const [category, setCategory] = useState("layout");
  const [kind, setKind] = useState("preference");
  const [original, setOriginal] = useState("");
  const [interpretation, setInterpretation] = useState("");
  const [replacement, setReplacement] = useState<Record<string, string>>({});
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
      await request(`${base}/designs/${designId}/feedback`, csrf, { method: "POST",
        body: JSON.stringify({ original_text: original, interpretation: original.slice(0, 1000), category: "other", kind: "preference", scope }) });
      setOriginal(""); setInterpretation(""); await refresh();
    } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
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

  return <div className="studio-learning">
    <h3>Feedback for this revision</h3>
    {error && <p className="form-error" role="alert">{error}</p>}
    {canEdit && <form className="studio-fields" onSubmit={(event) => void submit(event)}>
      <label>Your feedback<textarea required maxLength={4000} value={original} onChange={(event) => setOriginal(event.target.value)} /></label>
      <label><input type="checkbox" checked={scope === "future"} onChange={(event) => setScope(event.target.checked ? "future" : "post")} /> Remember this for future posts</label>
      <button className="primary" type="submit" disabled={busy}>Save feedback</button>
    </form>}
    <div className="studio-learning-list">{feedback.map((note) => {
      const active = preferences.find((rule) => rule.status === "active" && rule.scope === note.scope
        && rule.scope_key === note.scope_key && rule.category === note.category);
      return <div className="studio-learning-entry" key={note.id}>
        <strong>{note.category} · {note.scope} · {note.status}</strong>
        <p>{note.original_text}</p><p>Interpretation: {note.interpretation}</p>
        {canApprove && note.status === "pending" && <div className="studio-actions">
          {note.kind === "preference" && <><button className="icon-button" type="button" disabled={busy || Boolean(active && replacement[note.id] !== active.id)}
            onClick={() => void decide(note.id, true, replacement[note.id])}><Check size={16} /> Approve</button>
            {active && <label>Replace current rule<select value={replacement[note.id] ?? ""}
              onChange={(event) => setReplacement({ ...replacement, [note.id]: event.target.value })}>
              <option value="">Select explicitly</option><option value={active.id}>{active.instruction}</option>
            </select></label>}</>}
          <button className="icon-button" type="button" disabled={busy} onClick={() => void decide(note.id, false)}><X size={16} /> Reject</button>
        </div>}
        {note.kind !== "preference" && note.status === "pending" && <p>Review facts in Brand; hypotheses need sourced performance evidence.</p>}
      </div>;
    })}</div>
    <h3>What I learned</h3>
    <div className="studio-learning-list">{preferences.map((rule) => <div className="studio-learning-entry" key={rule.id}>
      <strong>{rule.category} · {rule.scope} · v{rule.version} · {rule.status}</strong>
      <p>{rule.instruction}</p>
      {canApprove && rule.status === "active" && <button className="icon-button" type="button" disabled={busy}
        onClick={() => void revert(rule.id)}><RotateCcw size={16} /> Revert</button>}
    </div>)}</div>
  </div>;
}
