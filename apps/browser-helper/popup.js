const sites = {gemini: "https://gemini.google.com/*", chatgpt: "https://chatgpt.com/*"};
document.querySelector("#connect").addEventListener("click", async () => {
  const status = document.querySelector("#status");
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const url = new URL(tab.url);
    if (!(url.protocol === "https:" || (url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) || Object.values(sites).some(s => s.startsWith(url.origin)))
      throw new Error("Open your Falkrona page first.");
    const provider = document.querySelector("#provider").value;
    const pattern = `${url.origin}/*`;
    if (!await chrome.permissions.request({origins: [pattern, sites[provider]]})) throw new Error("Access was not granted.");
    const check = await chrome.scripting.executeScript({target: {tabId: tab.id}, func: async () => {
      const response = await fetch("/api/status", {credentials: "include"});
      return response.ok && (await response.json()).browser_helper_protocol === 1;
    }});
    if (!check[0]?.result) throw new Error("Open a current Falkrona site before connecting.");
    const {job} = await chrome.storage.session.get("job");
    if (job && !["complete", "paused"].includes(job.stage) && Date.parse(job.expiresAt) > Date.now()) throw new Error("Finish the current generation or disconnect it before reconnecting.");
    const scripts = await chrome.scripting.getRegisteredContentScripts();
    await chrome.scripting.unregisterContentScripts({ids: scripts.map(s => s.id)});
    await chrome.scripting.registerContentScripts([{id: "falkrona-owner", matches: [pattern], js: ["bridge.js"], runAt: "document_idle"}]);
    await chrome.storage.local.set({connection: {origin: url.origin, provider}});
    await chrome.scripting.executeScript({target: {tabId: tab.id}, files: ["bridge.js"]});
    await chrome.tabs.create({url: provider === "gemini" ? "https://gemini.google.com/app" : "https://chatgpt.com/"});
    status.textContent = "Connected to this Falkrona site. Sign in to the image app once, then return to Studio.";
  } catch (error) { status.textContent = error.message; }
});
document.querySelector("#disconnect").addEventListener("click", async () => {
  const {connection} = await chrome.storage.local.get("connection");
  const {job} = await chrome.storage.session.get("job");
  if (job) await chrome.tabs.sendMessage(job.providerTab, {action: "cancel"}).catch(() => {});
  await chrome.storage.session.remove("job");
  await chrome.storage.local.remove("connection");
  await chrome.storage.local.remove("jobs");
  await chrome.scripting.unregisterContentScripts();
  if (connection) await chrome.permissions.remove({origins: [`${connection.origin}/*`, sites[connection.provider]]});
  document.querySelector("#status").textContent = "Disconnected. Existing image-app chats remain in your account.";
});
