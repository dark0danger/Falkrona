const sites = {gemini: "https://gemini.google.com", chatgpt: "https://chatgpt.com"};
const uuid = /^[0-9a-f-]{36}$/i;
let starting = false;
// Chrome clears dynamically registered scripts when an unpacked extension reloads.
// Restore only the already-authorized owner origin, without requesting new access.
async function restoreOwnerBridge() {
  const {connection} = await chrome.storage.local.get("connection");
  if (!connection || !["gemini", "chatgpt"].includes(connection.provider)) return;
  const origin = new URL(connection.origin);
  if (origin.origin !== connection.origin || !(origin.protocol === "https:" ||
      origin.protocol === "http:" && ["localhost", "127.0.0.1"].includes(origin.hostname))) return;
  const pattern = `${connection.origin}/*`;
  if (!await chrome.permissions.contains({origins: [pattern]})) return;
  const scripts = await chrome.scripting.getRegisteredContentScripts();
  if (!scripts.some(script => script.id === "falkrona-owner"))
    await chrome.scripting.registerContentScripts([{id:"falkrona-owner",matches:[pattern],js:["bridge.js"],runAt:"document_idle"}]);
}
void restoreOwnerBridge().catch(() => {});
async function readJob(runId) {
  const {job} = await chrome.storage.session.get("job");
  if (job && (!runId || job.runId === runId)) return job;
  const {jobs = {}} = await chrome.storage.local.get("jobs");
  const saved = jobs[runId];
  if (!saved) return null;
  // Images stay in session memory. Reload can safely observe the original chat again.
  return {...saved, stage: "paused"};
}
async function saveJob(job) {
  await chrome.storage.session.set({job});
  const {jobs = {}} = await chrome.storage.local.get("jobs");
  const {image, error, ...metadata} = job;
  const retained = Object.fromEntries(Object.entries(jobs).filter(([, value]) => Date.parse(value.expiresAt) > Date.now()));
  retained[job.runId] = metadata;
  await chrome.storage.local.set({jobs: Object.fromEntries(Object.entries(retained).slice(-25))});
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  route(message, sender).then(respond, error => respond({error: error.message}));
  return true;
});
async function route(message, sender) {
  const {connection} = await chrome.storage.local.get("connection");
  if (["provider-progress", "provider-result", "provider-refresh"].includes(message.action)) {
    const job = await readJob();
    if (!job || sender.tab?.id !== job.providerTab || sender.frameId !== 0 || new URL(sender.url).origin !== sites[job.provider]) throw new Error("Wrong provider tab.");
    if (message.action === "provider-refresh") {
      const packet = message.packet;
      const url = new URL(sender.url);
      if (!job.submitted || job.observedFresh || job.provider !== "chatgpt" || !/^\/c\/[a-z0-9-]+$/i.test(url.pathname)
          || packet?.run_id !== job.runId || packet.provider !== job.provider || Date.parse(packet.expires_at) <= Date.now()) return {ok:false};
      // Observe a fresh view of the SAME request; keep the original server run intact.
      const fresh = await chrome.tabs.create({url:sender.url,active:false});
      await saveJob({...job,providerTab:fresh.id,providerUrl:sender.url,stage:"checking",observedFresh:true});
      void launch(fresh.id,packet,true,true).catch(async () => {
        const current = await readJob();
        if (current?.runId === job.runId) await saveJob({...current,stage:"paused",error:"The saved image conversation needs attention. Nothing was resent."});
      });
      return {ok:true};
    }
    if (message.action === "provider-progress") {
      await saveJob({...job, stage: message.stage, providerUrl: sender.url, submitted: job.submitted || message.stage === "submitted"});
      return {ok: true};
    }
    if (message.image && (!job.submitted || !/^data:image\/(png|jpeg|webp);base64,/.test(message.image) || message.image.length > 20_000_100)) throw new Error("Invalid result.");
    await saveJob({...job, stage: message.image ? "complete" : "paused", image: message.image, error: message.error});
    return {ok: true};
  }
  if (!connection || sender.frameId !== 0 || !sender.tab || new URL(sender.url).origin !== connection.origin) throw new Error("Connect this Falkrona page using the helper button first.");
  if (message.action === "status") return {connected: true, provider: connection.provider, helper_version: "0.1.5", account_verified: false};
  const job = await readJob(message.runId || message.packet?.run_id);
  if (message.action === "poll") {
    if (!job || job.runId !== message.runId || job.ownerTab !== sender.tab.id || job.origin !== connection.origin) return {stage: "unavailable"};
    if (Date.now() > Date.parse(job.expiresAt)) return {stage: "paused", error: "The request expired. Your direction is saved; import the downloaded image manually."};
    return {stage: job.stage, image: job.image, error: job.error};
  }
  if (message.action !== "start") throw new Error("Unknown request.");
  const packet = message.packet;
  if (!packet || !uuid.test(packet.run_id) || !uuid.test(packet.workspace_id) || packet.provider !== connection.provider || packet.url !== (packet.provider === "gemini" ? sites.gemini + "/app" : sites.chatgpt + "/") || !packet.nonce || Date.parse(packet.expires_at) <= Date.now() || !Array.isArray(packet.attachments) || packet.attachments.length < 2 || packet.attachments.length > 3 || typeof packet.prompt !== "string" || packet.prompt.length > 12000) throw new Error("Invalid generation packet.");
  if (packet.attachments.map(a => a.role).join(",") !== (packet.attachments.length === 3 ? "logo,product,reference" : "logo,product")) throw new Error("Image roles changed.");
  const {job: activeJob} = await chrome.storage.session.get("job");
  if (activeJob?.runId !== packet.run_id && activeJob && !["complete", "paused"].includes(activeJob.stage) && Date.parse(activeJob.expiresAt) > Date.now()) throw new Error("Finish the current image first.");
  if (message.resumeOnly && job?.runId !== packet.run_id)
    return {stage: "paused", error: "The helper lost this request after reloading. Import the existing image using Recovery options; nothing was resent."};
  if (job?.runId === packet.run_id) {
    if (job.ownerTab !== sender.tab.id || job.origin !== connection.origin) throw new Error("This generation belongs to another Falkrona tab.");
    if (job.stage !== "paused") {
      // A new owner-issued packet renews observation/import, never the submitted request.
      await saveJob({...job,expiresAt:packet.expires_at});
      return {stage: job.stage};
    }
    // Resume the SAME tab: recognize a manual submission instead of creating a duplicate.
    try { await chrome.tabs.get(job.providerTab); }
    catch {
      const existing = job.providerUrl && new URL(job.providerUrl);
      const knownChat = existing && existing.origin === sites[job.provider] && (job.provider === "chatgpt" ? /^\/c\/[a-z0-9-]+$/i.test(existing.pathname) : /^\/app\/[a-z0-9_-]+$/i.test(existing.pathname));
      if (job.submitted && !knownChat) return {stage: "paused", error: "The image tab was closed. Import its finished image from Recovery options; nothing was resent."};
      const reopened = await chrome.tabs.create({url: job.submitted ? job.providerUrl : packet.url, active: false});
      job.providerTab = reopened.id;
    }
    await saveJob({...job, stage: "checking", expiresAt: packet.expires_at});
    void launch(job.providerTab, packet, true, job.submitted).catch(async () => {
      const {job: current} = await chrome.storage.session.get("job");
      if (current?.runId === packet.run_id) await saveJob({...current, stage: "paused", error: "The existing image tab needs attention. Nothing was resent."});
    });
    return {stage: "checking"};
  }
  if (starting || (activeJob && !["complete", "paused"].includes(activeJob.stage) && Date.parse(activeJob.expiresAt) > Date.now())) throw new Error("Finish the current image first.");
  starting = true;
  try {
    const tab = await chrome.tabs.create({url: packet.url, active: false});
    const next = {runId: packet.run_id, provider: packet.provider, origin: connection.origin,
      ownerTab: sender.tab.id, providerTab: tab.id, expiresAt: packet.expires_at, stage: "opening", submitted: false};
    await saveJob(next);
    void launch(tab.id, packet).catch(async () => {
      const {job: current} = await chrome.storage.session.get("job");
      if (current?.runId === packet.run_id) await saveJob({...current, stage: "paused", error: "The image app needs attention. Open its tab; your prompt is saved in Studio. Nothing was resubmitted."});
    });
    return {stage: "opening"};
  } finally { starting = false; }
}
async function launch(tabId, packet, resume = false, observeOnly = false) {
  // Short bounded load checks, then a content script owns the long generation wait.
  for (let attempt = 0; attempt < 30; attempt++) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  await chrome.scripting.executeScript({target: {tabId}, files: ["provider-dom.js", "provider.js"]});
  await chrome.tabs.sendMessage(tabId, {action: resume ? "resume" : "generate", packet, observeOnly});
}
