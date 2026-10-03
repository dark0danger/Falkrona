export type ImageApp = "gemini" | "chatgpt";
export type BrowserPacket = {run_id: string; workspace_id: string; design_id: string; provider: ImageApp;
  url: string; nonce: string; expires_at: string; prompt: string;
  attachments: Array<{role: string; name: string; mime_type: string; data: string}>};
type HelperResult = {connected?: boolean; provider?: ImageApp; helper_version?: string; stage?: string; image?: string; error?: string};

export function requireCurrentHelper(version?: string) {
  const patch = /^0\.1\.(\d+)$/.exec(version ?? "");
  if (!patch || Number(patch[1]) < 3)
    throw new Error("Update Falkrona Browser Helper to 0.1.3 or later, click Reload in Extensions, then refresh Falkrona.");
}

export function helperRequest(action: "status" | "start" | "poll", packet?: BrowserPacket, runId?: string, resumeOnly = false): Promise<HelperResult> {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", listener);
      reject(new Error("No browser helper responded. Open Falkrona in Chrome or Edge, then click the Falkrona extension and choose Allow and connect."));
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
