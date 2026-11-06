import { RefreshCw, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { PlanImages, type CalendarPlan, type ProductPhoto } from "./PlanImages";
import { checkImageConnection, helperRequest, type ImageApp } from "./browserHelper";
import { csrfFetch } from "./csrfFetch";

import { cairoInput } from "./postingTime";
export { cairoInput };

function mondayOf(value: string) {
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate()-((day.getUTCDay()+6)%7));
  return day.toISOString().slice(0,10);
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await csrfFetch(path,{credentials:"include",...options,headers:{"Content-Type":"application/json",...options?.headers}});
  const data = await response.json();
  if(!response.ok) throw new Error(data?.detail?.message ?? data?.detail ?? "Request failed.");
  return data;
}
function savedImageOptions(workspace:string,week:string):{photo:string;language:"ar"|"en";provider:ImageApp}|null {
  try{const value=JSON.parse(sessionStorage.getItem(`falkrona-image-options:${workspace}:${week}`)??"null");
    return value&&typeof value.photo==="string"&&["ar","en"].includes(value.language)&&["chatgpt","gemini"].includes(value.provider)?value:null;
  }catch{return null;}
}
type DraftFailure = { last_error?: string | null; failure_message?: string | null };

function draftFailureMessage(failure: DraftFailure): string {
  if (failure.failure_message) return failure.failure_message;
  if (failure.last_error === "lease_expired_review_required") return "The planning worker was interrupted before it saved your draft. You can start a new draft.";
  if (failure.last_error === "invalid_direction") return "Gemini returned an incomplete plan. Try drafting again.";
  if (failure.last_error === "cancelled") return "Drafting was cancelled.";
  return "Falkrona couldn’t finish this draft. Your saved designs are safe.";
}

export function CalendarView({workspaceId,csrf,canEdit,canApprove,brandReady,openBrand,openProducts,openAccounts,openStudio,assets,week,setWeek}: {
  week:string; setWeek:(week:string)=>void; workspaceId:string; csrf:string; canEdit:boolean; canApprove:boolean; brandReady:boolean; openBrand:()=>void; openProducts:()=>void; openAccounts:()=>void;
  openStudio:(planId:string,itemId:string,platform:string,schedule:string)=>void; assets:ProductPhoto[];
}) {
  const [plan,setPlan] = useState<CalendarPlan|null>(null);
  const [loaded,setLoaded] = useState(false);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [lastDraftFailure,setLastDraftFailure] = useState<DraftFailure|null>(null);
  const [consent,setConsent] = useState(false);
  const [notice,setNotice] = useState("");
  const [photos,setPhotos] = useState<ProductPhoto[]>([]);
  const [photo,setPhoto] = useState(()=>savedImageOptions(workspaceId,week)?.photo??"");
  const [language,setLanguage] = useState<"ar"|"en">(()=>savedImageOptions(workspaceId,week)?.language??"en");
  const [provider,setProvider] = useState<ImageApp>(()=>savedImageOptions(workspaceId,week)?.provider??"chatgpt");
  const [autoGenerate,setAutoGenerate] = useState(false);
  const [scheduled,setScheduled] = useState(false);
  const [showNewPlan,setShowNewPlan] = useState(false);
  const [deletedPlan,setDeletedPlan] = useState<string|null>(null);
  const current = useRef(""); current.current = `${workspaceId}:${week}`;
  const base = `/api/v1/workspaces/${workspaceId}`;
  const pendingKey = `falkrona-week-plan:${workspaceId}:${week}`;
  useEffect(()=>{
    let active=true;
    void request<{logo_asset_id:string;reference_asset_id:string|null}>(`${base}/branding`).then(brand=>{
      if(!active)return;
      const choices=assets.filter(asset=>asset.purpose==="product"&&asset.source==="upload"&&/^image\/(png|jpeg|webp)$/.test(asset.mime_type)&&![brand.logo_asset_id,brand.reference_asset_id].includes(asset.id));
      setPhotos(choices);setPhoto(old=>choices.some(asset=>asset.id===old)?old:choices[0]?.id??"");
    }).catch(()=>{});
    void helperRequest("status").then(status=>{if(active&&status.provider&&!savedImageOptions(workspaceId,week))setProvider(status.provider);}).catch(()=>{});
    return ()=>{active=false;};
  },[workspaceId,assets]);
  async function load() {
    const identity = current.current;
    const result = await request<{plan:CalendarPlan|null;deleted_plan_id?:string|null;draft_failure?:DraftFailure|null}>(`${base}/plans?week_start=${week}`);
    if(current.current===identity){setPlan(result.plan);setDeletedPlan(result.deleted_plan_id??null);setLastDraftFailure(result.draft_failure??null);setLoaded(true);}
  }
  async function finishRun(runId:string) {
    const identity = current.current;
    const deadline = Date.now()+420000;
    while(Date.now()<deadline && current.current===identity) {
      const run = await request<{status:string;last_error?:string;output?:{failure_message?:string}}>(`${base}/agent-runs/${runId}`);
      if(run.status==="completed") {sessionStorage.removeItem(pendingKey); await load(); return;}
      if(["failed","cancelled"].includes(run.status)) {sessionStorage.removeItem(pendingKey); throw new Error(draftFailureMessage({last_error:run.last_error??run.status,failure_message:run.output?.failure_message}));}
      await new Promise(resolve=>window.setTimeout(resolve,1500));
    }
    if(current.current===identity) throw new Error("Your plan is still being prepared. Refresh the calendar to check your saved request.");
  }
  useEffect(()=>{
    current.current = `${workspaceId}:${week}`;
    setPlan(null); setLoaded(false); setError("");setLastDraftFailure(null);setAutoGenerate(false);setScheduled(false);setShowNewPlan(false);
    void load().catch(reason=>setError(String(reason)));
    const pending = sessionStorage.getItem(pendingKey);
    if(pending) {setBusy(true); setNotice("Planning and polishing your posts…"); void finishRun(pending).catch(reason=>setError(reason.message)).finally(()=>{setBusy(false);setNotice("");});}
    return ()=>{current.current="";};
  },[workspaceId,week]);
  async function draft(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    sessionStorage.setItem(`falkrona-image-options:${workspaceId}:${week}`,JSON.stringify({photo,language,provider}));
    setBusy(true); setError(""); setLastDraftFailure(null); setNotice("Checking your image connection…");
    try {
      await checkImageConnection(provider);
      setNotice("Planning and polishing your posts…");
      const result = await request<{id:string;status:string}>(`${base}/plans`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({
        week_start:week,goal:data.get("goal"),platforms:["facebook_pages"],
        cadence:data.get("cadence")?Number(data.get("cadence")):null,language,public_context_confirmed:consent})});
      if(["queued","running"].includes(result.status)) {sessionStorage.setItem(pendingKey,result.id); await finishRun(result.id);}
      else await load();
      setDeletedPlan(null);setShowNewPlan(false);setAutoGenerate(true);
    } catch(reason) {setError(reason instanceof Error?reason.message:String(reason));}
    finally {setBusy(false);setNotice("");}
  }
  async function deletePlan(restore=false) {
    const id=restore?deletedPlan:plan?.id;if(!id)return;
    setBusy(true);setError("");setAutoGenerate(false);
    try{await request(`${base}/plans/${id}${restore?"/restore":""}`,{method:restore?"POST":"DELETE",headers:{"X-CSRF-Token":csrf}});setDeletedPlan(restore?null:id);await load();}
    catch(reason){setError(reason instanceof Error?reason.message:String(reason));}
    finally{setBusy(false);}
  }
  const visibleError = error || (!busy && lastDraftFailure ? draftFailureMessage(lastDraftFailure) : "");
  return <section className="queue calendar-view" aria-labelledby="calendar-title">
    <div className="section-heading"><div><h2 id="calendar-title" className="sr-only">Content plan</h2></div>
      <div className="calendar-week-actions"><label>Week of<input type="date" value={week} disabled={busy} onChange={e=>e.target.value&&setWeek(mondayOf(e.target.value))}/></label>
        <button className="icon-button" aria-label="Refresh calendar" disabled={busy} onClick={()=>void load().catch(reason=>setError(reason.message))}><RefreshCw size={17}/></button></div></div>
    {visibleError&&<p className="form-error" role="alert">{visibleError} {/helper|connection|image app/i.test(visibleError)&&<button type="button" className="text-button" onClick={openAccounts}>Open accounts</button>}</p>}
    {notice&&<p role="status">{notice}</p>}
    {deletedPlan&&!plan&&<p role="status" className="deletion-notice">Plan deleted. Your brand details are saved. <button className="text-action" disabled={busy} onClick={()=>void deletePlan(true)}>Undo</button></p>}
    {!loaded&&!error&&<p className="loading-line" role="status">Loading your plan…</p>}
    {loaded&&!plan&&!busy&&(!brandReady||!photo)&&<div className="workflow-empty"><div><h3>{brandReady ? "Add a product photo first" : "Set up your brand first"}</h3><p>{brandReady ? "Choose the product you want to feature in your posts." : "Tell us about your business and upload your logo."}</p></div><button className="primary" onClick={brandReady ? openProducts : openBrand}>{brandReady ? "Add a product photo" : "Set up my brand"}</button></div>}
    {loaded&&brandReady&&photo&&canEdit&&!scheduled&&(!plan||showNewPlan)&&<form className="calendar-controls" onSubmit={draft} key={`${week}:${plan?.id??"none"}`}>
      <div className="plan-start"><div><h3>{plan ? "Start a new plan" : "Let’s create your week"}</h3><p>Your brand. A week of posts. One approval.</p></div><button className="primary" disabled={busy||!consent||!photo}><Sparkles size={16}/>{busy?"Working…":plan?"Create new plan":"Create my week"}</button></div>
      <div className="plan-preferences-grid"><label>Design language<select value={language} disabled={busy} onChange={e=>setLanguage(e.target.value as "ar"|"en")}><option value="en">English</option><option value="ar">Arabic — العربية</option></select></label>{photos.length>1&&<label>Product photo<select value={photo} disabled={busy} onChange={e=>setPhoto(e.target.value)}>{photos.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>}</div>
      <details className="plan-preferences"><summary>Plan preferences</summary><div className="plan-preferences-grid"><label>Goal<select name="goal" defaultValue={plan?.strategy.goal??"engagement"} disabled={busy}><option value="awareness">Awareness</option><option value="engagement">Engagement</option><option value="leads">Leads</option><option value="sales">Sales</option></select></label>
      <label>Posts per week<select name="cadence" defaultValue={plan?.strategy.cadence??""} disabled={busy}><option value="">Auto</option>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
      <label>Create images with<select value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value as ImageApp);setConsent(false);}}><option value="chatgpt">ChatGPT</option><option value="gemini">Gemini</option></select></label>
      </div></details>
      <label className="week-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/> Allow Gemini to plan my posts and {provider==="chatgpt"?"ChatGPT":"Gemini"} to create designs using my brand details and images.</label>
    </form>}

    {plan&&<>
      <div className="calendar-strategy"><div className="plan-heading"><div><h3>Your week</h3><span className="quiet-label">{plan.items.length} posts · Facebook</span></div>{canEdit&&!busy&&!scheduled&&<details className="plan-menu"><summary>Plan options</summary><button className="text-action" onClick={()=>setShowNewPlan(value=>!value)}>{showNewPlan?"Keep this plan":"Create another plan"}</button>{plan.status==="draft"&&<button className="text-action danger-action" onClick={()=>void deletePlan()}>Delete plan</button>}</details>}</div></div>
      {plan.strategy.planner==="gemini"&&<PlanImages key={plan.id} workspaceId={workspaceId} csrf={csrf} plan={plan} assets={assets} consent={consent} canApprove={canApprove} canEdit={canEdit} onPlanChange={load} openAccounts={openAccounts} autoGenerate={autoGenerate} options={{photo,language,provider}} onBusy={setBusy} onScheduleChange={setScheduled} openPost={itemId=>{const item=plan.items.find(value=>value.id===itemId);if(item)openStudio(plan.id,item.id,item.platform,item.scheduled_at);}}/>}
      {plan.strategy.planner!=="gemini"&&<p className="muted">Create a new week to start your designs.</p>}
      <details><summary>Plan details</summary><p>{plan.strategy.direction}</p><div className="calendar-items">{plan.items.map(item=><article className="calendar-item" key={item.id}>
        <div className="calendar-date"><strong>{new Intl.DateTimeFormat("en-GB",{timeZone:"Africa/Cairo",weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}).format(new Date(item.scheduled_at))}</strong><span>Cairo time</span></div>
        <div className="calendar-brief"><strong>{item.title}</strong><p>{item.concept}</p><span>{item.platform==="facebook_pages"?"Facebook":"Instagram"} · {item.cta}</span>
        </div></article>)}</div></details>
    </>}
  </section>;
}
