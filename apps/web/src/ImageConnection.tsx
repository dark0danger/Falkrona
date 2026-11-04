import { useEffect, useState } from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { checkImageConnection, type HelperResult } from "./browserHelper";

export function ImageConnection() {
  const [connection, setConnection] = useState<HelperResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    async function check() {
      if (!active) return;
      setChecking(true);
      try {
        const value = await checkImageConnection();
        if (active) { setConnection(value); setError(""); }
      } catch (reason) {
        if (active) { setConnection(null); setError(reason instanceof Error ? reason.message : "Check your image connection."); }
      } finally { if (active) setChecking(false); }
    }
    void check();
    window.addEventListener("focus", check);
    window.addEventListener("falkrona-check-image-connection", check);
    return () => { active = false; window.removeEventListener("focus", check); window.removeEventListener("falkrona-check-image-connection", check); };
  }, []);
  return <section className="image-connection tool-panel" aria-labelledby="image-connection-title">
    <div className="image-connection-heading"><div><h3 id="image-connection-title">Image creation</h3>
      <p className="muted">{connection ? `${connection.provider === "gemini" ? "Gemini" : "ChatGPT"} is connected to this browser.` : "Connect once. Create and receive your designs from Falkrona."}</p></div>
      <button type="button" className="icon-button" disabled={checking} onClick={() => window.dispatchEvent(new Event("falkrona-check-image-connection"))}><RefreshCw size={16}/>{checking ? "Checking…" : "Check connection"}</button></div>
    {connection ? <p className="image-connection-ready"><CheckCircle2 size={18}/> Browser connection ready <span className="muted">Keep your image app signed in.</span></p> : !checking && <p className="muted" role="status">{error}</p>}
    <details><summary>{connection ? "Connection settings" : "Set up image creation"}</summary>
      <ol className="connection-steps">
        <li><a href="/api/v1/browser-helper" download>Download Falkrona Browser Helper</a> and extract the ZIP.</li>
        <li>In Chrome’s Extensions page, turn on Developer mode, choose Load unpacked and select the extracted folder.</li>
        <li>With this Falkrona page open, click the helper once, choose your image app and select Allow and connect.</li>
        <li>Sign in to the image app, then return here. Future posts start from Content plan.</li>
      </ol>
      <p className="muted">The connection belongs to this browser and this Falkrona address. It does not verify your ChatGPT or Gemini login or remaining image allowance.</p>
      {connection && <small>Helper {connection.helper_version}. Disconnect or change the image app from the helper menu.</small>}
    </details>
  </section>;
}
