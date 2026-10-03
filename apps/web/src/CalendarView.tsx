import { CalendarDays, RefreshCw, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useRef, useState } from "react";
import { PlanImages, type CalendarPlan, type ProductPhoto } from "./PlanImages";
import { helperRequest, type ImageApp } from "./browserHelper";
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
export function CalendarView({workspaceId,csrf,canEdit,canApprove,openBrand,openStudio,assets}: {
  workspaceId:string; csrf:string; canEdit:boolean; canApprove:boolean; openBrand:()=>void;
  openStudio:(planId:string,itemId:string,platform:string,schedule:string)=>void; assets:ProductPhoto[];
}) {
  const [week,setWeek] = useState(()=>mondayOf(cairoInput(new Date().toISOString()).slice(0,10)));
  const [plan,setPlan] = useState<CalendarPlan|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [consent,setConsent] = useState(false);
  const [notice,setNotice] = useState("");
  const [photos,setPhotos] = useState<ProductPhoto[]>([]);
  const [photo,setPhoto] = useState(()=>savedImageOptions(workspaceId,week)?.photo??"");
  const [language,setLanguage] = useState<"ar"|"en">(()=>savedImageOptions(workspaceId,week)?.language??"en");
  const [provider,setProvider] = useState<ImageApp>(()=>savedImageOptions(workspaceId,week)?.provider??"chatgpt");
  const [autoGenerate,setAutoGenerate] = useState(false);
  const [scheduled,setScheduled] = useState(false);
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
    const result = await request<{plan:CalendarPlan|null;deleted_plan_id?:string|null}>(`${base}/plans?week_start=${week}`);
    if(current.current===identity){setPlan(result.plan);setDeletedPlan(result.deleted_plan_id??null);}
  }
  async function finishRun(runId:string) {
    const identity = current.current;
    const deadline = Date.now()+180000;
    while(Date.now()<deadline && current.current===identity) {
      const run = await request<{status:string;last_error?:string;output?:{failure_message?:string}}>(`${base}/agent-runs/${runId}`);
      if(run.status==="completed") {sessionStorage.removeItem(pendingKey); await load(); return;}
      if(["failed","cancelled"].includes(run.status)) {sessionStorage.removeItem(pendingKey); throw new Error(run.output?.failure_message??"Gemini couldn’t finish this draft. Your saved designs are safe. Try drafting again.");}
      await new Promise(resolve=>window.setTimeout(resolve,1500));
    }
    if(current.current===identity) throw new Error("Gemini is still planning. Refresh the calendar to check your saved request.");
  }
  useEffect(()=>{
    current.current = `${workspaceId}:${week}`;
    setPlan(null); setError("");setAutoGenerate(false);setScheduled(false);
    void load().catch(reason=>setError(String(reason)));
    const pending = sessionStorage.getItem(pendingKey);
    if(pending) {setBusy(true); setNotice("Gemini is drafting your week…"); void finishRun(pending).catch(reason=>setError(reason.message)).finally(()=>{setBusy(false);setNotice("");});}
    return ()=>{current.current="";};
  },[workspaceId,week]);
  async function draft(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    sessionStorage.setItem(`falkrona-image-options:${workspaceId}:${week}`,JSON.stringify({photo,language,provider}));
    setBusy(true); setError(""); setNotice("Gemini is drafting your week…");
    try {
      const result = await request<{id:string;status:string}>(`${base}/plans`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({
        week_start:week,goal:data.get("goal"),platforms:["facebook_pages","instagram"].filter(p=>data.get(p)==="on"),
        cadence:data.get("cadence")?Number(data.get("cadence")):null,language,public_context_confirmed:consent})});
      if(["queued","running"].includes(result.status)) {sessionStorage.setItem(pendingKey,result.id); await finishRun(result.id);}
      else await load();
      setDeletedPlan(null);setAutoGenerate(true);
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
  return <section className="queue calendar-view" aria-labelledby="calendar-title">
    <div className="section-heading"><div><p className="eyebrow">YOUR WEEK OF POSTS</p><h2 id="calendar-title">Calendar</h2></div>
      <div className="calendar-week-actions"><label>Week of<input type="date" value={week} disabled={busy} onInput={e=>e.currentTarget.value&&setWeek(mondayOf(e.currentTarget.value))} onChange={e=>e.target.value&&setWeek(mondayOf(e.target.value))}/></label>
        <button className="icon-button" aria-label="Refresh calendar" disabled={busy} onClick={()=>void load().catch(reason=>setError(reason.message))}><RefreshCw size={17}/></button></div></div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    {notice&&<p role="status">{notice}</p>}
    {deletedPlan&&!plan&&<p role="status" className="deletion-notice">Plan deleted. Your brand details are saved. <button className="text-action" disabled={busy} onClick={()=>void deletePlan(true)}>Undo</button></p>}
    {canEdit&&!scheduled&&<form className="calendar-controls" onSubmit={draft} key={`${week}:${plan?.id??"none"}`}>
      <div className="plan-start"><div><h3>{plan ? "Ready for a fresh plan?" : "Let’s plan your week"}</h3><p>Draft, review your designs, then approve once to schedule.</p></div><button className="primary" disabled={busy||!consent||!photo}><Sparkles size={16}/>{busy?"Working…":plan?"Draft a new week":"Draft a plan"}</button></div>
      <div className="plan-preferences-grid"><label>Design language<select value={language} disabled={busy} onChange={e=>setLanguage(e.target.value as "ar"|"en")}><option value="en">English</option><option value="ar">Arabic — العربية</option></select></label>{photos.length>1&&<label>Product photo<select value={photo} disabled={busy} onChange={e=>setPhoto(e.target.value)}>{photos.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>}</div>
      <details className="plan-preferences"><summary>Plan preferences</summary><div className="plan-preferences-grid"><label>Goal<select name="goal" defaultValue={plan?.strategy.goal??"engagement"} disabled={busy}><option value="awareness">Awareness</option><option value="engagement">Engagement</option><option value="leads">Leads</option><option value="sales">Sales</option></select></label>
      <fieldset disabled={busy}><legend>Platforms</legend><label><input type="checkbox" name="facebook_pages" defaultChecked={plan?.strategy.platforms.includes("facebook_pages")??true}/> Facebook</label><label><input type="checkbox" name="instagram" disabled/> Instagram · coming later</label></fieldset>
      <label>Posts per week<select name="cadence" defaultValue={plan?.strategy.cadence??""} disabled={busy}><option value="">Auto</option>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
      <label>Create images with<select value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value as ImageApp);setConsent(false);}}><option value="chatgpt">ChatGPT</option><option value="gemini">Gemini</option></select></label>
      </div></details>
      <label className="week-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} disabled={busy}/> Allow Gemini to plan my posts and {provider==="chatgpt"?"ChatGPT":"Gemini"} to create the designs using my brand details, logo, product photo and optional reference.</label>
    </form>}
    {!plan&&!busy&&<div className="calendar-empty"><CalendarDays size={25}/><p>Gemini will turn your brand details into a week of post ideas.</p><button className="icon-button" onClick={openBrand}>Branding</button></div>}
    {plan&&<>
      <div className="calendar-strategy"><div className="plan-heading"><h3>{plan.strategy.direction}</h3>{canEdit&&plan.status==="draft"&&<button className="text-action danger-action" disabled={busy||scheduled} onClick={()=>void deletePlan()}>Delete plan</button>}</div><p>{plan.items.length} posts · {plan.strategy.audience}{plan.strategy.planner==="gemini"?" · Planned by Gemini":" · Previous plan"}</p></div>
      {plan.strategy.planner==="gemini"&&<PlanImages key={plan.id} workspaceId={workspaceId} csrf={csrf} plan={plan} assets={assets} consent={consent} canApprove={canApprove} canEdit={canEdit} onPlanChange={load} autoGenerate={autoGenerate} options={{photo,language,provider}} onBusy={setBusy} onScheduleChange={setScheduled} openPost={itemId=>{const item=plan.items.find(value=>value.id===itemId);if(item)openStudio(plan.id,item.id,item.platform,cairoInput(item.scheduled_at));}}/>}
      {plan.strategy.planner!=="gemini"&&<p className="muted">Draft a new week to let Gemini plan your posts.</p>}
      <details><summary>Weekly ideas</summary><div className="calendar-items">{plan.items.map(item=><article className="calendar-item" key={item.id}>
        <div className="calendar-date"><strong>{new Intl.DateTimeFormat("en-GB",{timeZone:"Africa/Cairo",weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}).format(new Date(item.scheduled_at))}</strong><span>Cairo time</span></div>
        <div className="calendar-brief"><strong>{item.title}</strong><p>{item.concept}</p><span>{item.platform==="facebook_pages"?"Facebook":"Instagram"} · {item.cta}</span>
        </div></article>)}</div></details>
    </>}
  </section>;
}
