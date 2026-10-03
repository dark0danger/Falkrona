import { useEffect, useState } from "react";
import "./branding.css";

export type Branding = {
  ready: boolean; answers: Record<string, string>; logo_asset_id: string | null; reference_asset_id: string | null;
  public_context_confirmed: boolean; survey_source: string; survey_status: string | null;
  survey: { questions: Array<{ key: string; question: string; examples: string[] }> } | null;
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "include", ...options });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail?.message ?? "We couldn't save this. Please try again.");
  return result;
}

function AssetPreview({ workspaceId, id, logo }: { workspaceId: string; id: string | null; logo: boolean }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    setUrl(""); if (!id) return;
    let active = true;
    void request<{ download_url: string }>(`/api/v1/workspaces/${workspaceId}/assets/${id}/download-url`)
      .then((r) => { if (active) setUrl(r.download_url); }).catch(() => {});
    return () => { active = false; };
  }, [workspaceId, id]);
  return url ? <img className={logo ? "brand-logo-preview" : "brand-reference-preview"} src={url} alt={logo ? "Your uploaded brand logo" : "Your uploaded design reference"} /> : null;
}

export function BrandingView({ workspaceId, csrf, canEdit, onSaved, openPlan }: {
  workspaceId: string; csrf: string; canEdit: boolean; onSaved: (branding: Branding) => void; openPlan: () => void;
}) {
  const [data, setData] = useState<Branding | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [logo, setLogo] = useState<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [publicContext, setPublicContext] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState(false);
  const base = `/api/v1/workspaces/${workspaceId}/branding`;
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        let value = await request<Branding>(base);
        if (!active) return;
        setAnswers(value.answers); setLogo(value.logo_asset_id); setReference(value.reference_asset_id);
        setPublicContext(value.public_context_confirmed); setSaved(value.ready); setData(value); onSaved(value);
        if (!value.survey && canEdit && !value.survey_status) {
          value = await request<Branding>(`${base}/survey`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: "{}" });
          if (active) setData(value);
        }
      } catch (reason) { if (active) setError(String(reason).replace(/^Error: /, "")); }
    }
    void load();
    const timer = window.setInterval(() => {
      void request<Branding>(base).then((value) => { if (active) { setData(value); if (value.survey || ["failed", "cancelled"].includes(value.survey_status ?? "")) window.clearInterval(timer); } }).catch(() => {});
    }, 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, [workspaceId, canEdit, csrf]);

  async function upload(role: "logo" | "reference", file?: File) {
    if (!file) return; setBusy(role); setError(""); setSaved(false);
    try {
      const form = new FormData(); form.set("file", file);
      const asset = await request<{ id: string }>(`${base}/assets/${role}`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: form });
      if (role === "logo") setLogo(asset.id); else setReference(asset.id);
    } catch (reason) { setError(String(reason).replace(/^Error: /, "")); }
    finally { setBusy(""); }
  }
  async function save() {
    setBusy("save"); setError("");
    try {
      const value = await request<Branding>(base, { method: "PUT", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ answers, logo_asset_id: logo, reference_asset_id: reference, public_context_confirmed: publicContext }) });
      setData(value); setSaved(value.ready); onSaved(value);
    } catch (reason) { setError(String(reason).replace(/^Error: /, "")); }
    finally { setBusy(""); }
  }
  const complete = Boolean(logo && ["brand_name", "category", "audience", "style"].every((key) => answers[key]?.trim()));
  return <section className="queue branding-view" aria-labelledby="branding-title">
    <div className="section-heading"><div><p className="eyebrow">START WITH YOUR BRAND</p><h2 id="branding-title">Let's get to know your brand</h2></div><span>{saved ? "Ready to create" : "A few simple steps"}</span></div>
    <p className="muted">Answer four short questions and add your logo. Falkrona will use these details every time it creates a Facebook or Instagram post.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
    {!data?.survey && <p role="status">{data?.survey_status === "failed" ? "Your brand questions couldn't be prepared." : "Preparing your brand questions with Gemini…"}</p>}
    {data?.survey_status === "failed" && canEdit && <button className="icon-button" type="button" onClick={() => {
      void request<Branding>(`${base}/survey`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: JSON.stringify({ retry_failed: true }) }).then(setData).catch((reason) => setError(String(reason)));
    }}>Try preparing questions again</button>}
    {data?.survey && <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="branding-questions">{data.survey.questions.map((question, index) => <div className="branding-question" key={question.key}>
        <label htmlFor={`brand-${question.key}`}><span className="step-number">{index + 1}</span>{question.question}</label>
        {question.key === "brand_name" ? <input id={`brand-${question.key}`} required maxLength={200} disabled={!canEdit || Boolean(busy)} value={answers[question.key] ?? ""} onChange={(event) => { setSaved(false); setAnswers({ ...answers, [question.key]: event.target.value }); }} />
          : <textarea id={`brand-${question.key}`} required maxLength={1000} rows={2} disabled={!canEdit || Boolean(busy)} value={answers[question.key] ?? ""} onChange={(event) => { setSaved(false); setAnswers({ ...answers, [question.key]: event.target.value }); }} />}
        {question.key === "style" ? <div className="style-examples">{question.examples.map((example, i) => <button type="button" className={`style-example style-example-${i}`} key={example} disabled={!canEdit || Boolean(busy)} onClick={() => { setSaved(false); setAnswers({ ...answers, style: example }); }}><span className="style-miniature" aria-hidden="true"><i /><b /><em /></span><span>{example}</span></button>)}</div>
          : <p className="muted brand-example">For example: {question.examples.join(" · ")}</p>}
      </div>)}</div>
      <div className="branding-uploads">
        <div className="brand-upload"><h3>Your logo <span>Required</span></h3><p className="muted">PNG or WebP with a transparent background. The checkerboard shows transparent space.</p><AssetPreview workspaceId={workspaceId} id={logo} logo /><label>{logo ? "Replace logo" : "Upload your logo"}<input aria-label="Upload transparent brand logo" type="file" accept=".png,.webp" disabled={!canEdit || Boolean(busy)} onChange={(event) => { void upload("logo", event.target.files?.[0]); event.target.value = ""; }} /></label></div>
        <div className="brand-upload"><h3>A design you like <span>Optional</span></h3><p className="muted">Upload one example for inspiration. Your own logo and product will stay in the final post.</p><AssetPreview workspaceId={workspaceId} id={reference} logo={false} /><label>{reference ? "Replace example" : "Add an example"}<input aria-label="Upload optional design reference" type="file" accept=".png,.jpg,.jpeg,.webp" disabled={!canEdit || Boolean(busy)} onChange={(event) => { void upload("reference", event.target.files?.[0]); event.target.value = ""; }} /></label>{reference && canEdit && <button type="button" className="icon-button" disabled={Boolean(busy)} onClick={() => { setReference(null); setSaved(false); }}>Remove example</button>}</div>
      </div>
      <label className="branding-public"><input type="checkbox" checked={publicContext} disabled={!canEdit || Boolean(busy)} onChange={(event) => { setPublicContext(event.target.checked); setSaved(false); }} /> These brand details can be shared publicly. Don't include private customer information.</label>
      <div className="studio-actions">{canEdit && <button className="primary" type="submit" disabled={!complete || Boolean(busy)}>{busy ? "Saving…" : "Save my brand"}</button>}{saved && <button className="icon-button" type="button" onClick={openPlan}>Plan my posts →</button>}</div>
      {!saved && <p className="muted">Save your answers and transparent logo to start creating.</p>}
      {data.survey_source === "offline_starter" && <p className="muted">Offline preview: these are starter questions. Connected mode prepares the questions with Gemini.</p>}
    </form>}
  </section>;
}
