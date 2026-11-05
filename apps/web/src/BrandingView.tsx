import { useEffect, useState } from "react";
import { csrfFetch } from "./csrfFetch";
import "./branding.css";

type Survey = { questions: Array<{ key: string; question: string; examples: string[] }> };

export type Branding = {
  ready: boolean; answers: Record<string, string>; logo_asset_id: string | null; reference_asset_id: string | null;
  public_context_confirmed: boolean; survey_source: string; survey_status: string | null;
  survey: Survey | null; starter_survey?: Survey;
};

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await csrfFetch(url, { credentials: "include", ...options });
  const result = await response.json().catch(() => null);
  if (!response.ok || result === null) throw new Error(result?.detail?.message ?? "Falkrona couldn't complete the request. Please try again.");
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

export function BrandingView({ workspaceId, csrf, canEdit, onSaved, openPlan, nextLabel }: {
  workspaceId: string; csrf: string; canEdit: boolean; onSaved: (branding: Branding) => void; openPlan: () => void; nextLabel: string;
}) {
  const [data, setData] = useState<Branding | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [logo, setLogo] = useState<string | null>(null);
  const [reference, setReference] = useState<string | null>(null);
  const [publicContext, setPublicContext] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [saved, setSaved] = useState(false);
  const [questions, setQuestions] = useState<Survey | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const base = `/api/v1/workspaces/${workspaceId}/branding`;
  useEffect(() => {
    const controller = new AbortController();
    let poll: number | undefined;
    let deadline: number | undefined;
    let finished = false;
    const signal = controller.signal;

    function showQuestions(survey?: Survey) {
      if (finished || signal.aborted) return;
      finished = true;
      window.clearTimeout(poll);
      window.clearTimeout(deadline);
      if (survey) setQuestions(survey);
      else setError("Your brand questions are temporarily unavailable. Please try again.");
    }

    function checkSurvey(value: Branding) {
      if (finished || signal.aborted) return;
      if (value.survey) return showQuestions(value.survey);
      if (["failed", "cancelled"].includes(value.survey_status ?? "")) return showQuestions(value.starter_survey);
      poll = window.setTimeout(async () => {
        try {
          checkSurvey(await request<Branding>(base, { signal }));
        } catch {
          showQuestions(value.starter_survey);
        }
      }, 2000);
    }

    async function load() {
      setError("");
      let value: Branding;
      try {
        value = await request<Branding>(base, { signal: AbortSignal.any([signal, AbortSignal.timeout(10000)]) });
      } catch (reason) {
        if (!signal.aborted) setError(reason instanceof Error && reason.name !== "TimeoutError" ? reason.message : "Loading your brand took too long.");
        return;
      }
      if (signal.aborted) return;
      setAnswers(value.answers); setLogo(value.logo_asset_id); setReference(value.reference_asset_id);
      setPublicContext(value.public_context_confirmed); setSaved(value.ready); setData(value); onSaved(value);
      if (value.survey || !canEdit || value.ready) return showQuestions(value.survey ?? value.starter_survey);

      // Keep the same questions for this visit once the owner can start typing.
      deadline = window.setTimeout(() => showQuestions(value.starter_survey), 8000);
      try {
        if (!value.survey_status) {
          const queued = await request<Branding>(`${base}/survey`, { method: "POST", signal,
            headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: "{}" });
          checkSurvey(queued);
        } else {
          checkSurvey(value);
        }
      } catch {
        showQuestions(value.starter_survey);
      }
    }
    void load();
    return () => { controller.abort(); window.clearTimeout(poll); window.clearTimeout(deadline); };
  }, [workspaceId, canEdit, csrf, loadAttempt]);

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
    <div className="section-heading"><div><h2 id="branding-title">Brand essentials</h2></div><span>{saved ? "Ready to create" : "A few simple steps"}</span></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {!questions && (error ? <button className="icon-button" type="button" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Try again</button>
      : <p role="status">Preparing your brand questions…</p>)}
    {questions && <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <div className="branding-questions">{questions.questions.map((question, index) => <div className="branding-question" key={question.key}>
        <label htmlFor={`brand-${question.key}`}><span className="step-number">{index + 1}</span>{question.question}</label>
        {question.key === "brand_name" ? <input id={`brand-${question.key}`} required maxLength={200} disabled={!canEdit || Boolean(busy)} value={answers[question.key] ?? ""} onChange={(event) => { setSaved(false); setAnswers({ ...answers, [question.key]: event.target.value }); }} />
          : <textarea id={`brand-${question.key}`} required maxLength={1000} rows={2} disabled={!canEdit || Boolean(busy)} value={answers[question.key] ?? ""} onChange={(event) => { setSaved(false); setAnswers({ ...answers, [question.key]: event.target.value }); }} />}
        {question.key === "style" ? <div className="style-examples">{question.examples.map((example, i) => <button type="button" className={`style-example style-example-${i}`} key={example} aria-pressed={answers.style === example} disabled={!canEdit || Boolean(busy)} onClick={() => { setSaved(false); setAnswers({ ...answers, style: example }); }}><span className="style-miniature" aria-hidden="true"><i /><b /><em /></span><span>{example}</span></button>)}</div>
          : <p className="muted brand-example">For example: {question.examples.join(" · ")}</p>}
      </div>)}</div>
      <div className="branding-uploads">
        <div className="brand-upload"><h3>Your logo <span>Required</span></h3><p className="muted">Transparent PNG or WebP.</p><AssetPreview workspaceId={workspaceId} id={logo} logo /><label>{logo ? "Replace logo" : "Upload your logo"}<input aria-label="Upload transparent brand logo" type="file" accept=".png,.webp" disabled={!canEdit || Boolean(busy)} onChange={(event) => { void upload("logo", event.target.files?.[0]); event.target.value = ""; }} /></label></div>
        <div className="brand-upload"><h3>A design you like <span>Optional</span></h3><p className="muted">An example of the style you like.</p><AssetPreview workspaceId={workspaceId} id={reference} logo={false} /><label>{reference ? "Replace example" : "Add an example"}<input aria-label="Upload optional design reference" type="file" accept=".png,.jpg,.jpeg,.webp" disabled={!canEdit || Boolean(busy)} onChange={(event) => { void upload("reference", event.target.files?.[0]); event.target.value = ""; }} /></label>{reference && canEdit && <button type="button" className="icon-button" disabled={Boolean(busy)} onClick={() => { setReference(null); setSaved(false); }}>Remove example</button>}</div>
      </div>
      <label className="branding-public"><input type="checkbox" checked={publicContext} disabled={!canEdit || Boolean(busy)} onChange={(event) => { setPublicContext(event.target.checked); setSaved(false); }} /> These brand details can be shared publicly. Don't include private customer information.</label>
      <div className="brand-save studio-actions">{saved ? <button className="primary" type="button" onClick={openPlan}>{nextLabel} →</button> : canEdit && <button className="primary" type="submit" disabled={!complete || Boolean(busy)}>{busy ? "Saving…" : "Save my brand"}</button>}</div>

      {data?.survey_source === "offline_starter" && <p className="muted">Offline preview: these are starter questions. Connected mode prepares the questions with Gemini.</p>}
    </form>}
  </section>;
}
