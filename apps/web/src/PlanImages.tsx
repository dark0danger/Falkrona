import { type FormEvent, useEffect, useRef, useState } from "react";
import { attachmentBlob, helperRequest, requireCurrentHelper, type BrowserPacket, type ImageApp } from "./browserHelper";
import { csrfFetch } from "./csrfFetch";
import { cairoInput, lastDayOfWeek } from "./postingTime";

export type ProductPhoto = {id:string; name:string; mime_type:string; source?:string;purpose?:string};
export type CalendarPlan = {id:string;week_start:string;revision:number;status:string;items:Array<{id:string;title:string;concept:string;cta:string;platform:string;scheduled_at:string}>;
  strategy:{goal:string;audience:string;direction:string;platforms:string[];cadence:number;planner?:string;visual_planning_version?:number;
    removed_items?:Array<{item:{id:string;title:string}}>;generation?:{entries:Array<{item_id:string}>;config:{inputs:{photo_asset_id:string;product_description:string;language?:"auto"|"ar"|"en"};provider:ImageApp}}}};
type Entry = {item_id:string;title:string;design_id:string;run_id:string;status:string;last_error?:string;imported_design_id?:string;image_asset_id?:string;caption?:string;scheduled_at?:string;platform?:string};
type Batch = {provider:ImageApp|null;entries:Entry[];complete:boolean};
type Schedule = {enabled:boolean;posts:Array<{id:string;design_version_id:string;status:string;attempt:{status:string;remote_publish_id?:string;last_error?:string}}>};
async function request<T>(path:string, options?:RequestInit):Promise<T> {
  const headers = new Headers(options?.headers);
  if(!(options?.body instanceof FormData)) headers.set("Content-Type","application/json");
  const response = await csrfFetch(path,{credentials:"include",...options,headers});
  const data = await response.json();
  if(!response.ok) throw new Error(data?.detail?.message??data?.detail??"Request failed.");
  return data;
}
function FinishedImage({workspaceId,assetId,title}:{workspaceId:string;assetId:string;title:string}) {
  const [url,setUrl] = useState("");
  useEffect(()=>{let active=true; void request<{download_url:string}>(`/api/v1/workspaces/${workspaceId}/assets/${assetId}/download-url`)
    .then(value=>{if(active)setUrl(value.download_url);}).catch(()=>{}); return ()=>{active=false;};},[workspaceId,assetId]);
  return url?<img src={url} alt={title} style={{width:"100%",maxWidth:360,borderRadius:8}}/>:null;
}
export function PlanImages({workspaceId,csrf,plan,assets,consent,onBusy,openPost,canApprove=false,canEdit=false,autoGenerate=false,options,onScheduleChange,onPlanChange}:{workspaceId:string;csrf:string;plan:CalendarPlan;assets:ProductPhoto[];consent:boolean;onBusy:(busy:boolean)=>void;openPost:(itemId:string)=>void;canApprove?:boolean;canEdit?:boolean;autoGenerate?:boolean;options?:{photo:string;language:"ar"|"en";provider:ImageApp};onScheduleChange?:(scheduled:boolean)=>void;onPlanChange?:()=>Promise<void>}) {
  const base = `/api/v1/workspaces/${workspaceId}`;
  const path = `${base}/plans/${plan.id}`;
  const [batch,setBatch] = useState<Batch>({provider:null,entries:[],complete:false});
  const [photos,setPhotos] = useState<ProductPhoto[]>([]);
  const [photo,setPhoto] = useState(plan.strategy.generation?.config.inputs.photo_asset_id??options?.photo??"");
  const [description,setDescription] = useState(plan.strategy.generation?.config.inputs.product_description??"");
  const [provider,setProvider] = useState<ImageApp>(plan.strategy.generation?.config.provider??options?.provider??"chatgpt");
  const [language,setLanguage] = useState<"auto"|"ar"|"en">(plan.strategy.generation?.config.inputs.language??options?.language??"en");
  const [allowed,setAllowed] = useState(Boolean(plan.strategy.generation)||autoGenerate&&consent);
  const [busy,setBusy] = useState(false);
  const [progress,setProgress] = useState("");
  const [error,setError] = useState("");
  const [packet,setPacket] = useState<BrowserPacket|null>(null);
  const [removed,setRemoved] = useState<Array<{id:string;title:string}>>(()=>plan.strategy.removed_items?.map(value=>({id:value.item.id,title:value.item.title}))??[]);
  const [timeEditor,setTimeEditor] = useState<{itemId:string;value:string;original:string}|null>(null);
  const [timeError,setTimeError] = useState("");
  const active = useRef(true);
  const automaticStarted=useRef(false);
  const [schedule,setSchedule]=useState<Schedule>({enabled:false,posts:[]});
  const [connections,setConnections]=useState<Array<{id:string;account_name:string;provider:string;status:string;granted_scopes:string[]}>>([]);
  const [connectionId,setConnectionId]=useState("");
  async function loadSchedule() {const value=await request<Schedule>(`${path}/publishing`);if(active.current){setSchedule(value);onScheduleChange?.(value.posts.some(post=>post.status==="approved"&&post.attempt.status!=="cancelled"));}}
  const needsNewPlan=plan.strategy.visual_planning_version!==2;
  useEffect(()=>{
    active.current=true;
    void request<Batch>(`${path}/images`).then(setBatch).catch(reason=>setError(reason.message));
    void loadSchedule().catch(reason=>setError(reason.message));
    void request<{connections:Array<{id:string;account_name:string;provider:string;status:string;granted_scopes:string[]}>}>(`${base}/social/connections`).then(value=>{
      if(!active.current)return;
      const pages=value.connections.filter(item=>item.provider==="meta"&&["connected","connected_partial"].includes(item.status)&&item.granted_scopes.includes("pages_manage_posts"));
      setConnections(pages);setConnectionId(pages[0]?.id??"");
    }).catch(()=>{});
    void request<{logo_asset_id:string;reference_asset_id:string|null}>(`${base}/branding`).then(brand=>{
      const choices=assets.filter(asset=>asset.purpose==="product" && asset.source==="upload" && /^image\/(png|jpeg|webp)$/.test(asset.mime_type) && ![brand.logo_asset_id,brand.reference_asset_id].includes(asset.id));
      setPhotos(choices); if(!photo&&choices.length===1)setPhoto(choices[0].id);
    }).catch(reason=>setError(reason.message));
    void helperRequest("status").then(status=>{if(status.provider&&!options&&!plan.strategy.generation)setProvider(status.provider);}).catch(()=>{});
    return ()=>{active.current=false;};
  },[workspaceId,plan.id,assets]);
  useEffect(()=>{if(autoGenerate&&consent&&allowed&&photo&&photos.length&&!automaticStarted.current){automaticStarted.current=true;void generate();}},[autoGenerate,consent,allowed,photo,photos.length]);
  useEffect(()=>{if(options&&consent)setAllowed(true);},[Boolean(options),consent]);
  useEffect(()=>{if(!schedule.posts.length)return;const timer=window.setInterval(()=>void loadSchedule().catch(()=>{}),15000);return()=>window.clearInterval(timer);},[schedule.posts.length,path]);
  async function approve() {
    setBusy(true);onBusy(true);setError("");
    try{await request(`${path}/approve-and-schedule`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({connection_id:connectionId,design_ids:batch.entries.map(entry=>entry.imported_design_id),facts_reviewed:true})});await loadSchedule();setProgress("Plan approved. Falkrona will publish each post at its scheduled time.");}
    catch(reason){setError(reason instanceof Error?reason.message:String(reason));await refresh().catch(()=>{});}
    finally{setBusy(false);onBusy(false);}
  }
  async function cancelSchedule(){setBusy(true);try{await request(`${path}/cancel-schedule`,{method:"POST",headers:{"X-CSRF-Token":csrf}});await loadSchedule();setProgress("Unpublished posts are cancelled.");}catch(reason){setError(String(reason));}finally{setBusy(false);}}
  async function refresh() {const value=await request<Batch>(`${path}/images`);if(active.current)setBatch(value);return value;}
  async function importImage(current:BrowserPacket,file:Blob) {
    const form=new FormData();form.set("provider",current.provider);form.set("nonce",current.nonce);form.set("file",file,"Generated ad.png");
    await request(`${base}/agent-runs/${current.run_id}/browser-image`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:form});
    setPacket(null);await refresh();
  }
  async function removePost(entry:Entry,restore=false) {
    setBusy(true);onBusy(true);setError("");
    try {
      await request(`${path}/posts/${entry.item_id}${restore?"/restore":""}`,{method:restore?"POST":"DELETE",headers:{"X-CSRF-Token":csrf}});
      setRemoved(old=>restore?old.filter(item=>item.id!==entry.item_id):[...old,{id:entry.item_id,title:entry.title}]);
      await onPlanChange?.();await refresh();
    }catch(reason){setError(reason instanceof Error?reason.message:String(reason));}
    finally{setBusy(false);onBusy(false);}
  }
  async function savePostingTime(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();if(!timeEditor)return;
    const selectedTime=String(new FormData(event.currentTarget).get("posting_time")??"");
    setBusy(true);onBusy(true);setTimeError("");
    try {
      const value=await request<Batch>(`${path}/posts/${timeEditor.itemId}/schedule`,{method:"PATCH",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({scheduled_at:selectedTime,previous_scheduled_at:timeEditor.original})});
      setBatch(value);await onPlanChange?.();setTimeEditor(null);setProgress("Posting date saved. Approve the plan when you’re ready.");
    }catch(reason){setTimeError(reason instanceof Error?reason.message:String(reason));}
    finally{setBusy(false);onBusy(false);}
  }
  async function generate(replace?:Entry) {
    setBusy(true);onBusy(true);setError("");
    try {
      const status=await helperRequest("status");
      requireCurrentHelper(status.helper_version);
      if(status.provider!==provider) throw new Error(`Choose ${provider==="chatgpt"?"ChatGPT":"Gemini"} in the helper's Allow and connect menu.`);
      setProgress("Gemini is preparing the prompts for your week…");
      const state=replace?await request<Batch>(`${path}/posts/${replace.item_id}/regenerate`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({design_id:replace.imported_design_id})}):await request<Batch>(`${path}/generate-images`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({photo_asset_id:photo,product_description:description,language,provider,consent:(consent||Boolean(plan.strategy.generation))&&allowed})});
      setBatch(state);
      if(replace)await onPlanChange?.();
      for(let index=0;index<state.entries.length;index++) {
        const entry=state.entries[index];if(entry.status==="ready")continue;
        if(!active.current)return;
        setProgress(`Post ${index+1} of ${state.entries.length}: Gemini is writing the image prompt…`);
        const planningDeadline=Date.now()+330000;
        while(true) {
          if(!active.current)return;
          const run=await request<{status:string;last_error?:string}>(`${base}/agent-runs/${entry.run_id}`);
          if(run.status==="completed")break;
          if(["failed","cancelled"].includes(run.status))throw new Error(`Gemini could not finish the brief for ${entry.title}. Continue generation to try again. Your completed posts are saved.`);
          if(Date.now()>planningDeadline)throw new Error("Prompt planning is still running. Continue generation later; your request is saved.");
          await new Promise(resolve=>window.setTimeout(resolve,1500));
        }
        await refresh();
        const current=await request<BrowserPacket>(`${base}/agent-runs/${entry.run_id}/browser-packet`,{method:"POST",headers:{"X-CSRF-Token":csrf},body:JSON.stringify({provider,consent:true})});
        setPacket(current);
        const started=await helperRequest("start",current);
        if(started.stage==="paused")throw new Error(started.error??"The image app needs attention.");
        const deadline=Math.min(Date.parse(current.expires_at),Date.now()+19*60000);
        let imported=false;
        while(Date.now()<deadline) {
          if(!active.current)return;
          const result=await helperRequest("poll",undefined,current.run_id);
          if(result.stage==="complete"&&result.image) {const [prefix,data]=result.image.split(",");await importImage(current,attachmentBlob(data,prefix.slice(5).split(";")[0]));imported=true;break;}
          if(["paused","unavailable"].includes(result.stage??""))throw new Error(result.error??"Open the image app to continue. Your other posts are saved.");
          setProgress(`Post ${index+1} of ${state.entries.length}: ${result.stage==="attaching"?"adding your brand images":result.stage==="submitted"?"creating your image":"preparing your image app"}…`);
          await new Promise(resolve=>window.setTimeout(resolve,2000));
        }
        if(!imported)throw new Error("The image request is saved. Continue when the app is ready; it will not be sent twice.");
      }
      await refresh();setProgress("Your week's posts are ready.");
    } catch(reason) {setError(reason instanceof Error?reason.message:String(reason));setProgress("");await refresh().catch(()=>{});}
    finally {if(active.current){setBusy(false);onBusy(false);}}
  }
  return <div className="studio-fields weekly-generation">
    {needsNewPlan&&<p>Draft a new week to create distinct designs using the updated brand direction.</p>}
    {!batch.complete&&!needsNewPlan&&!autoGenerate&&!options&&<label>Design language<select value={language} disabled={busy||Boolean(plan.strategy.generation)||Boolean(batch.entries.length)} onChange={event=>setLanguage(event.target.value as "en"|"ar")}>{language==="auto"&&<option value="auto" disabled>Original language</option>}<option value="en">English</option><option value="ar">Arabic — العربية</option></select></label>}
    {!batch.complete&&plan.items.length>0&&!needsNewPlan&&(!autoGenerate||error)&&<>
      {!options&&photos.length>1&&<label>Product photo<select value={photo} disabled={busy||Boolean(batch.entries.length)} onChange={e=>setPhoto(e.target.value)}><option value="">Choose a photo</option>{photos.map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>}
      {!photos.length&&<p>Add a product photo in Products to create this week's images.</p>}
      {!options&&<><label className="week-consent"><input type="checkbox" checked={allowed} disabled={busy} onChange={e=>setAllowed(e.target.checked)}/> Allow {provider==="chatgpt"?"ChatGPT":"Gemini"} to use my logo, product photo and optional reference for every post this week.</label><details><summary>Image preferences and connection</summary><div className="studio-fields"><label>Create images with<select value={provider} disabled={busy||Boolean(batch.entries.length)} onChange={e=>{setProvider(e.target.value as ImageApp);setAllowed(false);}}><option value="chatgpt">ChatGPT</option><option value="gemini">Gemini</option></select></label><label>Anything else about this product?<textarea value={description} disabled={busy||Boolean(batch.entries.length)} onChange={e=>setDescription(e.target.value)} maxLength={2000}/></label><a href="/api/v1/browser-helper" download>Download browser helper</a></div></details></>}
      <button className="primary" disabled={busy||!photo||(!consent&&!plan.strategy.generation)||!allowed} onClick={()=>void generate()}>{busy?"Generating…":"Continue creating designs"}</button>
    </>}
    {progress&&<p role="status">{progress}</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    {removed.map(item=><p className="deletion-notice" role="status" key={item.id}>Design deleted. <button className="text-action" disabled={busy} onClick={()=>void removePost({item_id:item.id,title:item.title} as Entry,true)}>Undo</button></p>)}
    <div className="calendar-items">{batch.entries.map(entry=>{const delivery=schedule.posts.find(post=>post.design_version_id===entry.imported_design_id);return <article className="calendar-item" key={entry.item_id}><div className="calendar-brief"><strong>{entry.title}</strong><p>{delivery?delivery.attempt.status==="queued"?"Scheduled":delivery.attempt.status==="published"?"Published":delivery.attempt.status==="cancelled"?"Cancelled":["upload_unknown","publish_unknown","needs_attention"].includes(delivery.attempt.status)?"Needs attention — your post won’t be resent automatically":"Publishing…":entry.status==="ready"?"Ready to review":entry.status==="completed"?"Prompt ready":entry.status==="running"?"Preparing prompt":entry.status==="queued"?"Waiting for Gemini":entry.last_error??entry.status}</p>{entry.image_asset_id&&<><FinishedImage workspaceId={workspaceId} assetId={entry.image_asset_id} title={entry.title}/><p className="post-review-caption">{entry.caption}</p>{entry.scheduled_at&&<p>{new Intl.DateTimeFormat("en-GB",{timeZone:"Africa/Cairo",dateStyle:"medium",timeStyle:"short"}).format(new Date(entry.scheduled_at))} · Cairo · Facebook</p>}{canEdit&&plan.status==="draft"&&!schedule.posts.length&&<button className="text-action posting-date-action" disabled={busy||!batch.complete} onClick={()=>{setTimeError("");setTimeEditor({itemId:entry.item_id,value:cairoInput(entry.scheduled_at!),original:entry.scheduled_at!});}}>Change posting date</button>}
      {timeEditor?.itemId===entry.item_id&&<form className="posting-date-editor" onSubmit={event=>void savePostingTime(event)}><label>Posting date &amp; time (Cairo)<input type="datetime-local" name="posting_time" required value={timeEditor.value} min={`${plan.week_start}T00:00`} max={`${lastDayOfWeek(plan.week_start)}T23:59`} disabled={busy} onChange={event=>setTimeEditor({...timeEditor,value:event.target.value})}/></label><small>Choose a time within this plan’s week.</small>{timeError&&<p className="form-error" role="alert">{timeError}</p>}<div className="posting-date-buttons"><button className="primary" disabled={busy||!timeEditor.value} type="submit">{busy?"Saving…":"Save date"}</button><button className="icon-button" disabled={busy} type="button" onClick={()=>setTimeEditor(null)}>Cancel</button></div></form>}
      <div className="design-card-actions"><button className="icon-button" disabled={busy} onClick={()=>openPost(entry.item_id)}>View saved post</button>{canEdit&&plan.status==="draft"&&!schedule.posts.length&&<><button className="icon-button" disabled={busy||!batch.complete} onClick={()=>void generate(entry)}>Regenerate</button><button className="text-action danger-action" disabled={busy||!batch.complete} onClick={()=>void removePost(entry)}>Delete</button></>}</div>{delivery?.attempt.remote_publish_id&&<a href={`https://www.facebook.com/${delivery.attempt.remote_publish_id}`} target="_blank" rel="noreferrer">View published post</a>}</>}</div></article>;})}</div>
    {batch.complete&&!schedule.posts.length&&canApprove&&<div className="plan-approval"><h3>Ready to publish your week?</h3>{connections.length>1&&<label>Facebook Page<select value={connectionId} onChange={e=>setConnectionId(e.target.value)}>{connections.map(connection=><option key={connection.id} value={connection.id}>{connection.account_name}</option>)}</select></label>}<p>Approve these designs, captions and Cairo posting times for {connections.find(connection=>connection.id===connectionId)?.account_name??"your Facebook Page"}.</p>{!connectionId&&<p>Connect Facebook and allow publishing access in Social accounts first.</p>}<button className="primary" disabled={busy||Boolean(timeEditor)||!connectionId||!schedule.enabled} onClick={()=>void approve()}>Approve plan & schedule</button></div>}
    {schedule.posts.some(post=>post.status==="approved"&&!["published","cancelled"].includes(post.attempt.status))&&canApprove&&<button className="icon-button" disabled={busy} onClick={()=>void cancelSchedule()}>Cancel unpublished posts</button>}
    {batch.complete&&<details><summary>Download a copy</summary><a className="icon-button" href={`${path}/images/package`} download>Download all posts</a></details>}
    {packet&&error&&<details><summary>Recovery options</summary><a href={packet.url} target="_blank" rel="noreferrer">Open image app</a><button className="icon-button" onClick={()=>void navigator.clipboard.writeText(packet.prompt)}>Copy prompt</button><label>Import finished image<input type="file" accept=".png,.jpg,.jpeg,.webp" onChange={event=>{const file=event.target.files?.[0];if(file)void importImage(packet,file).catch(reason=>setError(reason.message));event.target.value="";}}/></label></details>}
  </div>;
}
