export type ImageApp = "gemini" | "chatgpt";
export type BrowserPacket = {run_id: string; workspace_id: string; design_id: string; provider: ImageApp;
  url: string; nonce: string; expires_at: string; prompt: string;
  attachments: Array<{role: string; name: string; mime_type: string; data: string}>};
export type HelperResult = {connected?: boolean; provider?: ImageApp; helper_version?: string; stage?: string; image?: string; error?: string};

export function requireCurrentHelper(version?: string, provider?: ImageApp) {
  const patch = /^0\.1\.(\d+)$/.exec(version ?? "");
  const minimum = provider === "gemini" ? 9 : 7;
  if (!patch || Number(patch[1]) < minimum)
    throw new Error(`Update Falkrona Browser Helper to 0.1.${minimum} or later from Accounts, click Reload in Extensions, then refresh Falkrona.`);
}

export async function checkImageConnection(provider?: ImageApp): Promise<HelperResult> {
  const status = await helperRequest("status");
  if (!status.connected) throw new Error("Connect your image app in Accounts before creating posts.");
  if (provider && status.provider !== provider)
    throw new Error(`Your helper is connected to ${status.provider === "gemini" ? "Gemini" : "ChatGPT"}. Choose that image app in Plan preferences, or reconnect in Accounts.`);
  requireCurrentHelper(status.helper_version, status.provider);
  return status;
}

export function helperRequest(action: "status" | "start" | "poll" | "open", packet?: BrowserPacket, runId?: string, resumeOnly = false): Promise<HelperResult> {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", listener);
      reject(new Error("Your image connection isn’t ready. Open Accounts to connect the browser helper, then try again. Use the same Chrome or Edge browser."));
    }, 8000);
    function listener(event: MessageEvent) {
      if (event.source !== window || event.origin !== location.origin || event.data?.channel !== "falkrona-helper-response" || event.data.id !== id) return;
      window.clearTimeout(timer); window.removeEventListener("message", listener);
      if (event.data.result?.error && !event.data.result?.stage) reject(new Error(event.data.result.error));
      else resolve(event.data.result);
    }
    window.addEventListener("message", listener);
    window.postMessage({channel: "falkrona-helper-request", id, action, packet, runId, resumeOnly}, location.origin);
  });
}

export function attachmentBlob(data: string, type: string): Blob {
  const bytes = Uint8Array.from(atob(data), character => character.charCodeAt(0));
  return new Blob([bytes], {type});
}

export function downloadAttachment(name: string, data: string, type: string) {
  const url = URL.createObjectURL(attachmentBlob(data, type));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}
