// Isolated-world bridge. No cookies or credentials are copied to the extension.
if (!globalThis.falkronaBridgeInstalled) {
  globalThis.falkronaBridgeInstalled = true;
  window.addEventListener("message", async event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.channel !== "falkrona-helper-request") return;
    const {id, action, packet} = event.data;
    if (!/^[a-z0-9-]{1,80}$/i.test(id ?? "") || !["status", "start", "poll"].includes(action)) return;
    try {
      const result = await chrome.runtime.sendMessage({action, packet, runId: event.data.runId, resumeOnly: event.data.resumeOnly === true});
      window.postMessage({channel: "falkrona-helper-response", id, result}, location.origin);
    } catch { window.postMessage({channel: "falkrona-helper-response", id, result: {error: "Reconnect the Falkrona helper."}}, location.origin); }
  });
}
