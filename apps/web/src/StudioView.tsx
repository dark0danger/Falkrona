import { helperRequest, requireCurrentHelper, attachmentBlob, downloadAttachment, type BrowserPacket, type ImageApp } from "./browserHelper";
import type { Branding } from "./BrandingView";
import { ChevronDown, ChevronUp, Download, Image as ImageIcon, RotateCcw, Save, Sparkles, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LearningPanel } from "./LearningPanel";

type Asset = { id: string; name: string; mime_type: string; sha256: string; source?: string; purpose?:string };
type BaseLayer = { id: string; x: number; y: number; w: number; h: number; rotation: number; opacity: number; editable: boolean; role: string };
type TextLayer = BaseLayer & { type: "text"; text: string; color: string; font: "Arial"; size: number; weight: 400 | 700; direction: "auto" | "ltr" | "rtl"; align: "start" | "center" | "end" };
type ShapeLayer = BaseLayer & { type: "rectangle"; fill: string };
type EllipseLayer = BaseLayer & { type: "ellipse"; fill: string };
type ImageLayer = BaseLayer & { type: "image"; asset_id: string; sha256: string; fit: "contain" | "cover" };
type Layer = TextLayer | ShapeLayer | EllipseLayer | ImageLayer;
export type Scene = { schema: 1; layout: "editorial" | "product" | "type"; preset: keyof typeof PRESETS; slides: Array<{ id: string; layers: Layer[] }> };
type Design = { id: string; plan_id: string; item_id: string; revision: number; scene: Scene; caption: string; needs_fact_review: boolean; factual_refs: Array<{ field: string; value: string }>; creative_direction?: { design_idea: string; image_prompt: string; missing_information: string[]; model: string; renderer?: string; product_asset_id?: string; generated_asset_id?: string; language?: "ar"|"en" } };
type HistoryEntry = { id: string; revision: number };

export const PRESETS = { portrait: [1080, 1350], square: [1080, 1080], story: [1080, 1920], landscape: [1200, 628] } as const;

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (!(options?.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { credentials: "include", ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(String(body?.detail?.message ?? body?.detail ?? "Request failed."));
  return body as T;
}

export function textLayout(layer: TextLayer, width: number, height: number, lockSize = false): { lines: string[]; size: number; lineHeight: number; fits: boolean } {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const maxWidth = layer.w * width / 1000;
  const maxHeight = layer.h * height / 1000;
  const baseSize = layer.size * Math.min(width, height) / 1000;
  const paragraphs = layer.text.split(/\s*\|\s*|\n/u).map((part) => part.trim()).filter(Boolean);
  let lastLines: string[] = [];
  for (let size = baseSize; size >= 12; size -= 2) {
    if (context) context.font = `${layer.weight} ${size}px Arial`;
    const lines: string[] = [];
    let current = "";
    for (const paragraph of paragraphs) {
      for (const word of paragraph.split(/\s+/u)) {
        const candidate = current ? `${current} ${word}` : word;
        if (context && context.measureText(candidate).width <= maxWidth) { current = candidate; continue; }
        if (current) { lines.push(current); current = ""; }
        let segment = "";
        for (const character of Array.from(word)) {
          if (context && segment && context.measureText(segment + character).width > maxWidth) { lines.push(segment); segment = ""; }
          segment += character;
        }
        current = segment;
      }
      if (current) { lines.push(current); current = ""; }
    }
    if (lines.length * size * 1.22 <= maxHeight && lines.every((line) => !context || context.measureText(line).width <= maxWidth + 1))
      return { lines, size, lineHeight: size * 1.22, fits: true };
    lastLines = lines;
    if (lockSize) break;
  }
  const fallbackSize = lockSize ? baseSize : 12;
  const visible = Math.max(1, Math.floor(maxHeight / (fallbackSize * 1.22)));
  return { lines: lastLines.slice(0, visible).map((line, index) => index === visible - 1 ? `${line.slice(0, -1)}…` : line),
           size: fallbackSize, lineHeight: fallbackSize * 1.22, fits: false };
}

export function SceneSvg({ scene, slideIndex, imageData, svgRef }: {
  scene: Scene; slideIndex: number; imageData: Record<string, string>; svgRef: React.RefObject<SVGSVGElement | null>;
}) {
  const [width, height] = PRESETS[scene.preset];
  const slide = scene.slides[slideIndex];
  return <svg ref={svgRef} className="studio-canvas" viewBox={`0 0 ${width} ${height}`} width={width} height={height}
    xmlns="http://www.w3.org/2000/svg" aria-label={`Design slide ${slideIndex + 1}`} role="img">
    {slide.layers.map((layer) => {
      const x = layer.x * width / 1000, y = layer.y * height / 1000;
      const w = layer.w * width / 1000, h = layer.h * height / 1000;
      const transform = layer.rotation ? `rotate(${layer.rotation} ${x + w / 2} ${y + h / 2})` : undefined;
      if (layer.type === "rectangle" || layer.type === "ellipse") return layer.type === "rectangle"
        ? <rect key={layer.id} x={x} y={y} width={w} height={h} fill={layer.fill} opacity={layer.opacity} transform={transform} />
        : <ellipse key={layer.id} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill={layer.fill} opacity={layer.opacity} transform={transform} />;
      if (layer.type === "image") return imageData[layer.asset_id]
        ? <image key={layer.id} x={x} y={y} width={w} height={h} opacity={layer.opacity} transform={transform}
            preserveAspectRatio={layer.fit === "cover" ? "xMidYMid slice" : "xMidYMid meet"} href={imageData[layer.asset_id]} /> : null;
      const locked = slide.layers.some((entry) => entry.role === "photo");
      const { lines, size, lineHeight } = textLayout(layer, width, height, locked);
      return <g key={layer.id} opacity={layer.opacity} transform={transform}>
        {lines.map((line, index) => {
          const rtl = layer.direction === "rtl" || (layer.direction === "auto" && /^[^A-Za-z\u0600-\u06ff]*[\u0600-\u06ff]/u.test(line));
          const textX = layer.align === "center" ? x + w / 2 : layer.align === "end" ? (rtl ? x : x + w) : (rtl ? x + w : x);
          return <text key={index} x={textX} y={y + size + index * lineHeight} fill={layer.color}
            fontFamily={layer.font} fontWeight={layer.weight} fontSize={size} direction={rtl ? "rtl" : "ltr"}
            textAnchor={layer.align === "center" ? "middle" : "start"} style={{ unicodeBidi: "isolate" }}>{line}</text>;
        })}
      </g>;
    })}
  </svg>;
}

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Image could not be loaded."));
    reader.readAsDataURL(blob);
  });
}

export function toPng(svg: SVGSVGElement, width: number, height: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const markup = new XMLSerializer().serializeToString(svg);
    const url = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml" }));
    const image = new window.Image();
    image.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) throw new Error("Canvas is unavailable.");
        context.drawImage(image, 0, 0, width, height);
        canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG export failed.")), "image/png");
      } catch (error) { reject(error); }
      finally { URL.revokeObjectURL(url); }
    };
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error("SVG render failed.")); };
    image.src = url;
  });
}

export function StudioView({ workspaceId, csrf, selection, assets, branding, openBrand, refreshAssets, canEdit, canApprove, openCalendar }: {
  workspaceId: string; csrf: string; selection: { planId: string; itemId: string; platform: string; schedule: string } | null;
  assets: Asset[]; branding: Branding | null; openBrand: () => void; refreshAssets: () => Promise<void>; canEdit: boolean; canApprove: boolean; openCalendar: () => void;
}) {
  const [design, setDesign] = useState<Design | null>(null);
  const [scene, setScene] = useState<Scene | null>(null);
  const [caption, setCaption] = useState("");
  const [slideIndex, setSlideIndex] = useState(0);
  const [selectedRole, setSelectedRole] = useState("headline");
  const [undo, setUndo] = useState<Array<{ scene: Scene; caption: string }>>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [imageData, setImageData] = useState<Record<string, string>>({});
  const [reference, setReference] = useState<{ palette: string[]; aspect_ratio: number } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [logoAssetId, setLogoAssetId] = useState("");
  const [photoAssetId, setPhotoAssetId] = useState("");
  const [productImageConfirmed, setProductImageConfirmed] = useState(false);
  const [logoIncludesName, setLogoIncludesName] = useState(false);
  const [productDescription, setProductDescription] = useState("");
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [useGemini, setUseGemini] = useState(false);
  const [generationReady, setGenerationReady] = useState(false);
  const [publicContextConfirmed, setPublicContextConfirmed] = useState(false);
  const [planningStatus, setPlanningStatus] = useState("");
  const [imageApp, setImageApp] = useState<ImageApp>("gemini");
  const [imageAppConsent, setImageAppConsent] = useState(false);
  const [helperConnected, setHelperConnected] = useState(false);
  const [packet, setPacket] = useState<BrowserPacket | null>(null);
  const activeRequest = useRef(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const base = `/api/v1/workspaces/${workspaceId}`;

  useEffect(() => {
    let active = true;
    void requestJson<{ model_provider: string; execution_mode: string; creative_generation_ready: boolean }>("/api/status")
      .then((status) => { if (active) { setUseGemini(status.model_provider === "gemini" && status.execution_mode !== "offline_test"); setGenerationReady(status.creative_generation_ready); } })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    void helperRequest("status").then(status => {if (active) {setHelperConnected(Boolean(status.connected)); if(status.provider) setImageApp(status.provider);}}).catch(() => {});
    return () => {active = false;};
  }, []);

  useEffect(() => {
    activeRequest.current++;
    setPacket(null); setDesign(null); setScene(null); setHistory([]); setUndo([]); setError(""); setSlideIndex(0);
    setLogoAssetId(branding?.logo_asset_id ?? ""); setPublicContextConfirmed(Boolean(branding?.public_context_confirmed)); setPhotoAssetId(""); setProductImageConfirmed(false); setProductDescription(""); setLogoIncludesName(false);
    if (!selection) return;
    let cancelled = false;
    void requestJson<{ current: Design | null; history: HistoryEntry[] }>(`${base}/plans/${selection.planId}/items/${selection.itemId}/design`)
      .then((result) => { if (!cancelled) {
        setHistory(result.history); setDesign(result.current); setScene(result.current?.revision === 1 ? null : result.current?.scene ?? null);
        setCaption(result.current?.caption ?? "");
        setLanguage(result.current?.creative_direction?.language??"en");
        const images = result.current?.scene.slides[0]?.layers.filter((layer): layer is ImageLayer => layer.type === "image") ?? [];
        setLogoAssetId(branding?.logo_asset_id ?? "");
        setLogoIncludesName(Boolean(images.some((layer) => layer.role === "logo") &&
          result.current?.scene.slides[0]?.layers.some((layer) => layer.type === "text" && layer.role === "brand" && !layer.text)));
        setPhotoAssetId(result.current?.creative_direction?.product_asset_id ?? images.find((layer) => layer.role === "photo")?.asset_id ?? "");
        setProductImageConfirmed(images.some((layer) => layer.role === "photo"));
      } })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { cancelled = true; activeRequest.current++; };
  }, [workspaceId, selection?.planId, selection?.itemId, branding?.logo_asset_id]);

  useEffect(() => {
    if (!scene) return;
    const ids = [...new Set(scene.slides.flatMap((slide) => slide.layers.filter((layer): layer is ImageLayer => layer.type === "image").map((layer) => layer.asset_id)))];
    let cancelled = false;
    void Promise.all(ids.map(async (id) => {
      const signed = await requestJson<{ download_url: string }>(`${base}/assets/${id}/download-url`);
      const response = await fetch(signed.download_url, { credentials: "include" });
      if (!response.ok) throw new Error("An image asset is unavailable. The draft is unchanged.");
      return [id, await dataUrl(await response.blob())] as const;
    })).then((values) => { if (!cancelled) setImageData(Object.fromEntries(values)); })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { cancelled = true; };
  }, [scene, workspaceId]);

  function update(next: Scene, nextCaption = caption) {
    if (scene) setUndo((previous) => [...previous.slice(-29), { scene, caption }]);
    setScene(next); setCaption(nextCaption); setError("");
  }

  function updateLayer(role: string, patch: Partial<Layer>) {
    if (!scene) return;
    update({ ...scene, slides: scene.slides.map((slide, index) => index === slideIndex
      ? { ...slide, layers: slide.layers.map((layer) => layer.role === role ? { ...layer, ...patch } as Layer : layer) } : slide) });
  }

  function updateImage(role: "logo" | "product", id: string) {
    if (!scene) return;
    const asset = assets.find((entry) => entry.id === id);
    if (id && (!asset || !["image/png", "image/jpeg", "image/webp"].includes(asset.mime_type))) return;
    const slides = scene.slides.map((slide) => {
      const layers = slide.layers.filter((layer) => layer.role !== role);
      if (asset) layers.push({ id: crypto.randomUUID(), type: "image", role, asset_id: asset.id,
        sha256: asset.sha256, fit: "contain", x: role === "logo" ? 730 : 510,
        y: role === "logo" ? 40 : 240, w: role === "logo" ? 200 : 430,
        h: role === "logo" ? 180 : 390, rotation: 0, opacity: 1, editable: true });
      return { ...slide, layers };
    });
    update({ ...scene, layout: role === "product" && asset ? "product" : scene.layout,
      slides: role === "product" && asset ? slides.map((slide) => ({ ...slide, layers: slide.layers.map((layer) =>
        layer.role === "headline" ? { ...layer, w: 420 } : layer) })) : slides });
  }

  function compositionInputs() {
    return { logo_asset_id: logoAssetId, photo_asset_id: photoAssetId, language,
      product_image_confirmed: productImageConfirmed, logo_includes_name: logoIncludesName,
      product_description: productDescription };
  }

  async function importGenerated(current: BrowserPacket, file: Blob) {
    const requestId = activeRequest.current;
    const form = new FormData(); form.set("provider", current.provider); form.set("nonce", current.nonce);
    form.set("file", file, "Generated ad.png");
    const next = await requestJson<Design>(`${base}/agent-runs/${current.run_id}/browser-image`, {
      method: "POST", headers: {"X-CSRF-Token": csrf}, body: form});
    if (activeRequest.current !== requestId) throw new Error("The image is saved in its original brief. Open that brief to view it.");
    setPacket(null); setDesign(next); setScene(next.scene); setCaption(next.caption); setUndo([]);
    sessionStorage.removeItem(`falkrona-pending:${workspaceId}:${selection?.itemId}`);
    setHistory(entries => entries[0]?.id === next.id ? entries : [{id: next.id, revision: next.revision}, ...entries]);
    return next;
  }

  async function runHelper(current: BrowserPacket, resumeOnly = false): Promise<Design | null> {
    const requestId = activeRequest.current;
    const status = await helperRequest("status");
    setHelperConnected(Boolean(status.connected));
    requireCurrentHelper(status.helper_version);
    if (status.provider !== current.provider) throw new Error("Choose the same image app in the helper's Connect menu.");
    const started = await helperRequest("start", current, undefined, resumeOnly);
    if (started.stage === "paused") throw new Error(started.error ?? "Use Recovery options to import the existing image.");
    const deadline = Math.min(Date.parse(current.expires_at), Date.now() + 19 * 60000);
    while (Date.now() < deadline) {
      if (activeRequest.current !== requestId) throw new Error("Your generation continues in its original brief. Open that brief to return the result.");
      const result = await helperRequest("poll", undefined, current.run_id);
      if (result.stage === "complete" && result.image) {
        const [prefix, data] = result.image.split(",");
        return importGenerated(current, attachmentBlob(data, prefix.slice(5).split(";")[0]));
      }
      if (["paused", "unavailable"].includes(result.stage ?? "")) throw new Error(result.error ?? "Open the image app to finish. Your prepared prompt is saved below.");
      setPlanningStatus(({opening: "Opening your image app…", checking: "Checking your saved request…",
        attaching: "Adding your brand images…", ready_to_send: "Sending your design request…",
        submitted: "Creating your image…"} as Record<string, string>)[result.stage ?? ""] ?? "Preparing your design…");
      await new Promise(resolve => window.setTimeout(resolve, 2000));
    }
    throw new Error("Your image request is saved. Download the result from the image app and import it below; nothing will be resent.");
  }

  async function compose(draft: Design): Promise<Design | null> {
    if (!generationReady || !useGemini) throw new Error("Gemini planning needs operator setup before creating a design.");
    if (!imageAppConsent) throw new Error("Allow your chosen image app to receive the brand details and images first.");
    const requestId = activeRequest.current;
    setPlanningStatus("Gemini is preparing your design idea and advertising copy…");
    type Run = {id: string; status: string; last_error?: string};
    let run = await requestJson<Run>(`${base}/designs/${draft.id}/direction`, {
      method: "POST", headers: {"X-CSRF-Token": csrf},
      body: JSON.stringify({...compositionInputs(), public_context_confirmed: publicContextConfirmed, retry_failed: true})});
    const deadline = Date.now() + 330000;
    while (["queued", "running", "cancelling"].includes(run.status)) {
      if (Date.now() >= deadline) throw new Error("Planning is still pending. Click Create again to check the same saved request.");
      await new Promise(resolve => window.setTimeout(resolve, 1500));
      if (activeRequest.current !== requestId) throw new Error("Your direction is saved in the original brief.");
      run = await requestJson<Run>(`${base}/agent-runs/${run.id}`);
    }
    if (run.status !== "completed") throw new Error(`Gemini planning ${run.status}: ${run.last_error ?? "check provider settings"}. Your draft is saved.`);
    if (activeRequest.current !== requestId) throw new Error("The selected brief changed.");
    const current = await requestJson<BrowserPacket>(`${base}/agent-runs/${run.id}/browser-packet`, {
      method: "POST", headers: {"X-CSRF-Token": csrf}, body: JSON.stringify({provider: imageApp, consent: imageAppConsent})});
    setPacket(current);
    sessionStorage.setItem(`falkrona-pending:${workspaceId}:${selection?.itemId}`, JSON.stringify({runId: run.id, provider: imageApp}));
    return runHelper(current);
  }

  async function resumePrepared(automatic = true) {
    if (!imageAppConsent) {setError("Allow sharing with your chosen image app first."); return;}
    setBusy("resume"); setError("");
    try {
      const saved = sessionStorage.getItem(`falkrona-pending:${workspaceId}:${selection?.itemId}`);
      const pending = saved ? JSON.parse(saved) : null;
      if (!packet && pending?.provider !== imageApp) throw new Error("Select the image app used for your saved request and allow it to receive the brand images.");
      const current = packet ?? await requestJson<BrowserPacket>(`${base}/agent-runs/${pending.runId}/browser-packet`, {
        method: "POST", headers: {"X-CSRF-Token": csrf}, body: JSON.stringify({provider: pending.provider, consent: true})});
      setPacket(current);
      if (automatic) await runHelper(current, true);
    } catch (reason) {setError(reason instanceof Error ? reason.message : String(reason));}
    finally {setBusy(""); setPlanningStatus("");}
  }

  async function create() {
    if (!selection) return;
    if (!generationReady) { setError("Configure Gemini planning before creating an ad."); return; }
    if (!logoAssetId || !photoAssetId || !productImageConfirmed) {
      setError("Select the real logo and confirm the product image before creating a design."); return;
    }
    setBusy("create"); setError("");
    try {
      const draft = await requestJson<Design>(`${base}/plans/${selection.planId}/items/${selection.itemId}/design`,
        { method: "POST", headers: { "X-CSRF-Token": csrf } });
      setDesign(draft); setScene(draft.revision === 1 ? null : draft.scene); setCaption(draft.caption);
      const next = await compose(draft);
      if (next) { setDesign(next); setScene(next.scene); setCaption(next.caption);
      setHistory([{ id: next.id, revision: next.revision }, { id: draft.id, revision: draft.revision }]); }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); setPlanningStatus(""); }
  }

  async function save() {
    if (!design || !scene) return;
    setBusy("save"); setError("");
    try {
      const next = await requestJson<Design>(`${base}/designs/${design.id}/revisions`, {
        method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify({ scene, caption }),
      });
      setDesign(next); setScene(next.scene); setCaption(next.caption); setUndo([]);
      setHistory((entries) => entries[0]?.id === next.id ? entries : [{ id: next.id, revision: next.revision }, ...entries]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); }
  }

  async function regenerate() {
    if (!design || !logoAssetId || !photoAssetId || !productImageConfirmed) return;
    setBusy("regenerate"); setError("");
    try {
      const next = await compose(design);
      if (!next) return;
      setDesign(next); setScene(next.scene); setCaption(next.caption); setSlideIndex(0); setUndo([]);
      setHistory((entries) => [{ id: next.id, revision: next.revision }, ...entries]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); setPlanningStatus(""); }
  }

  async function downloadPng() {
    if (!scene || !design || dirty || overflow) return;
    setBusy("png"); setError("");
    try {
      await document.fonts.ready;
      const current = scene.slides[slideIndex];
      if (current.layers.some((layer) => layer.type === "image" && !imageData[layer.asset_id]))
        throw new Error("Wait for the logo and photograph to load before downloading.");
      if (!svgRef.current) throw new Error("Preview renderer is unavailable.");
      const [width, height] = PRESETS[scene.preset];
      const png = await toPng(svgRef.current, width, height);
      const url = URL.createObjectURL(png);
      const link = document.createElement("a"); link.href = url;
      link.download = `falkrona-design-r${design.revision}-slide-${slideIndex + 1}.png`;
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); }
  }

  async function restore(id: string) {
    try {
      const old = await requestJson<Design>(`${base}/designs/${id}`);
      if (scene) update(old.scene, old.caption);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  async function renderAndDownload() {
    if (!design || !scene || JSON.stringify(scene) !== JSON.stringify(design.scene) || caption !== design.caption) {
      setError("Save this revision before rendering."); return;
    }
    if (scene.slides.some((slide) => slide.layers.some((layer) => layer.type === "text"
        && !textLayout(layer, PRESETS[scene.preset][0], PRESETS[scene.preset][1],
          slide.layers.some((entry) => entry.role === "photo")).fits))) {
      setError("Some text does not fit this format. Shorten it before export."); return;
    }
    setBusy("render"); setError("");
    try {
      await document.fonts.ready;
      if (!document.fonts.check("700 24px Arial")) throw new Error("Arial did not load; the draft is preserved.");
      const ids = [...new Set(scene.slides.flatMap((slide) => slide.layers.filter((layer): layer is ImageLayer => layer.type === "image").map((layer) => layer.asset_id)))];
      if (ids.some((id) => !imageData[id])) throw new Error("An image is still loading. Try again when the preview is complete.");
      const [width, height] = PRESETS[scene.preset];
      for (let index = 0; index < scene.slides.length; index++) {
        setSlideIndex(index);
        await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        if (!svgRef.current) throw new Error("Preview renderer is unavailable.");
        const png = await toPng(svgRef.current, width, height);
        const body = new FormData(); body.set("preset", scene.preset); body.set("file", png, `slide-${index + 1}.png`);
        await requestJson(`${base}/designs/${design.id}/slides/${scene.slides[index].id}/renders`,
          { method: "POST", headers: { "X-CSRF-Token": csrf }, body });
      }
      const response = await fetch(`${base}/designs/${design.id}/package`, { credentials: "include" });
      if (!response.ok) throw new Error("The export package is incomplete. Your design is preserved.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = `falkrona-design-r${design.revision}.zip`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(""); }
  }

  async function analyzeReference(id: string) {
    setReference(null);
    if (!id) return;
    try { setReference(await requestJson(`${base}/assets/${id}/reference-traits`)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  }

  const layers = scene?.slides[slideIndex]?.layers ?? [];
  const text = (role: string) => layers.find((layer): layer is TextLayer => layer.type === "text" && layer.role === role);
  const shape = (role: string) => layers.find((layer): layer is ShapeLayer => layer.type === "rectangle" && layer.role === role);
  const selectedLayer = layers.find((layer) => layer.role === selectedRole);
  const imageAssets = assets.filter((asset) => asset.purpose === "product" && !["local_composition", "gemini_image", "external_generation"].includes(asset.source ?? "") && ["image/png", "image/jpeg", "image/webp"].includes(asset.mime_type));
  const dirty = design && scene && (JSON.stringify(scene) !== JSON.stringify(design.scene) || caption !== design.caption);
  const overflow = scene?.slides.some((slide) => slide.layers.some((layer) => layer.type === "text"
    && !textLayout(layer, PRESETS[scene.preset][0], PRESETS[scene.preset][1],
      slide.layers.some((entry) => entry.role === "photo")).fits)) ?? false;
  const guided = scene?.slides.some((slide) => slide.layers.some((layer) => layer.role === "photo")) ?? false;

  const externalArtwork = design?.creative_direction?.renderer === "browser_image_app";
  const helperSetup = <details className="studio-connection">
    <summary>{helperConnected ? "Image app connected" : "Image app connection"}</summary>
    <p>Use the browser helper's Allow and connect button, then sign in to your chosen image app.</p>
    <div className="studio-actions"><a href="/api/v1/browser-helper" download>Download helper</a>
      <button className="icon-button" type="button" disabled={Boolean(busy)} onClick={() => {
        void helperRequest("status").then(status => {
          if (packet && status.provider !== packet.provider) throw new Error(`Choose ${packet.provider === "gemini" ? "Gemini" : "ChatGPT"} in the helper for this design.`);
          setHelperConnected(Boolean(status.connected)); setError("");
          if (status.provider && status.provider !== imageApp) {setImageApp(status.provider); setImageAppConsent(false);}
        }).catch(reason => {setHelperConnected(false); setError(reason instanceof Error ? reason.message : String(reason));});
      }}>Check connection</button>
    </div>
  </details>;
  const imageChoices = <>
    <label>Design language<select value={language} disabled={!canEdit || Boolean(busy) || Boolean(packet)} onChange={event=>setLanguage(event.target.value as "en"|"ar")}><option value="en">English</option><option value="ar">Arabic — العربية</option></select></label>
    <label>Create images with<select value={imageApp} disabled={Boolean(busy) || Boolean(packet)} onChange={event => {setImageApp(event.target.value as ImageApp); setImageAppConsent(false); setHelperConnected(false);}}><option value="gemini">Gemini</option><option value="chatgpt">ChatGPT</option></select></label>
    <label><input type="checkbox" checked={imageAppConsent} disabled={Boolean(busy)} onChange={event => setImageAppConsent(event.target.checked)} /> Allow {imageApp === "gemini" ? "Gemini" : "ChatGPT"} to use my brand details and images.</label>
    {helperSetup}

    {!generationReady && <p className="form-error" role="status">Gemini planning is awaiting operator setup. Your uploaded photos and saved drafts are safe.</p>}
    <label>Product photo<select value={photoAssetId} disabled={!canEdit || Boolean(busy)} onChange={(event) => { setPhotoAssetId(event.target.value); setProductImageConfirmed(Boolean(event.target.value)); }}><option value="">Choose a photo</option>{imageAssets.filter((asset) => asset.id !== logoAssetId && asset.id !== branding?.reference_asset_id).map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
    <label>Or upload a product photo<input type="file" accept=".png,.jpg,.jpeg,.webp" disabled={!canEdit || Boolean(busy)} onChange={(event) => {
      const file = event.target.files?.[0]; if (!file) return;
      setBusy("upload"); setError(""); const form = new FormData(); form.set("file", file);
      void requestJson<{ id: string }>(`${base}/assets`, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: form })
        .then(async (asset) => { await refreshAssets(); setPhotoAssetId(asset.id); setProductImageConfirmed(true); })
        .catch((reason) => setError(String(reason))).finally(() => setBusy("")); event.target.value = "";
    }} /></label>
    <label>What should this post say about your product?<textarea value={productDescription} disabled={!canEdit || Boolean(busy)} maxLength={2000} onChange={(event) => setProductDescription(event.target.value)} placeholder="For example: our fresh coffee beans, available in a 250g bag" /></label>
    {useGemini && !publicContextConfirmed && <label><input type="checkbox" checked={publicContextConfirmed} disabled={!canEdit || Boolean(busy)} onChange={(event) => setPublicContextConfirmed(event.target.checked)} /> These brand and product details can be shared publicly.</label>}
  </>;

  if (!branding?.ready) return <section className="queue calendar-empty"><ImageIcon size={24} /><h2>Let's set up your brand first</h2><p>Answer the short questions and upload your transparent logo to unlock designs.</p><button className="primary" type="button" onClick={openBrand}>Open Branding</button></section>;
  if (!selection) return <section className="queue studio-empty"><span className="empty-icon"><ImageIcon size={25}/></span><h2>Your next great post starts here</h2><p>Open a saved post from your content plan to edit or download it.</p><button className="primary" type="button" onClick={openCalendar}>Open content plan</button></section>;
  return <section className="queue studio-view" aria-labelledby="studio-title">
    <div className="section-heading"><div><p className="eyebrow">MAKE YOUR NEXT POST</p><h2 id="studio-title">Design studio</h2></div>
      <button className="icon-button" type="button" onClick={openCalendar}>Back to Calendar</button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {packet && helperSetup}
    {planningStatus && <p role="status">{planningStatus}</p>}
    {packet && <div className="studio-fields studio-pending">
      <h3>{busy ? "Creating your design" : "Your design is ready to continue"}</h3>
      {!busy && <button className="primary" type="button" onClick={() => void resumePrepared()}>Continue design</button>}
      <details><summary>Recovery options</summary>
        <div className="studio-fields"><a href={packet.url} target="_blank" rel="noreferrer">Open {packet.provider === "gemini" ? "Gemini" : "ChatGPT"}</a>
          <button className="icon-button" type="button" onClick={() => {void navigator.clipboard.writeText(packet.prompt).catch(() => setError("Copy the prompt below."));}}>Copy prompt</button>
          <details><summary>Prompt and reference files</summary><textarea readOnly value={packet.prompt} />
            {packet.attachments.map(asset => <button className="icon-button" type="button" key={asset.role} onClick={() => downloadAttachment(asset.name, asset.data, asset.mime_type)}>Download {asset.role === "product" ? "product photo" : asset.role}</button>)}
          </details>
          <label>Import finished image<input type="file" accept=".png,.jpg,.jpeg,.webp" disabled={Boolean(busy)} onChange={event => {
            const file = event.target.files?.[0]; if(!file) return; setBusy("import"); setError("");
            void importGenerated(packet, file).catch(reason => setError(reason instanceof Error ? reason.message : String(reason))).finally(() => setBusy("")); event.target.value = "";
          }} /></label>
        </div>
      </details>
    </div>}

    {!packet && selection && sessionStorage.getItem(`falkrona-pending:${workspaceId}:${selection.itemId}`) && <div>
      <button className="primary" type="button" disabled={Boolean(busy)} onClick={() => void resumePrepared()}>Continue saved image request</button>
      <details><summary>Recovery options</summary><button className="icon-button" type="button" disabled={Boolean(busy)} onClick={() => void resumePrepared(false)}>Import an existing result</button></details>
    </div>}
    {overflow && <p className="warning-note">Some text does not fit this format. Shorten it before export.</p>}
    {!design || !scene ? (packet ? null : <div className="calendar-empty studio-create"><ImageIcon size={23} /><p>Add a photo of your product. Falkrona will handle the layout, colors and logo.</p><div className="studio-fields">{imageChoices}</div>{canEdit && <button className="primary" type="button" disabled={Boolean(busy) || Boolean(packet) || !imageAppConsent || !logoAssetId || !photoAssetId || !productImageConfirmed} onClick={() => void create()}>Create design</button>}</div>) : <>
      <div className="studio-toolbar"><span>{externalArtwork ? "Generated post" : `Revision ${design.revision}`}{dirty ? " · unsaved" : ""}{design.needs_fact_review && !externalArtwork ? " · fact review needed" : ""}</span>
        <div className="studio-actions"><button className="icon-button" type="button" title="Undo" aria-label="Undo" disabled={!undo.length} onClick={() => {
          const previous = undo.at(-1); if (previous) { setScene(previous.scene); setCaption(previous.caption); setUndo(undo.slice(0, -1)); }
        }}><Undo2 size={17} /></button>
          {canEdit && <button className="icon-button" type="button" disabled={!dirty || Boolean(busy)} onClick={() => void save()}><Save size={16} /> Save changes</button>}
          <button className="icon-button" type="button" disabled={Boolean(busy) || Boolean(dirty) || overflow} onClick={() => void downloadPng()}><Download size={16} /> PNG</button>
          <button className="primary" type="button" disabled={Boolean(busy) || Boolean(dirty) || overflow} onClick={() => void renderAndDownload()}><Download size={16} /> {busy === "render" ? "Rendering..." : "Download post package"}</button></div></div>
      <div className="studio-layout"><div className="studio-workarea">
        <div className="studio-preview" style={{ aspectRatio: `${PRESETS[scene.preset][0]} / ${PRESETS[scene.preset][1]}` }}>
          <SceneSvg scene={scene} slideIndex={slideIndex} imageData={imageData} svgRef={svgRef} />
        </div>
        {scene.slides.length > 1 && <div className="studio-slide-strip" aria-label="Slides">{scene.slides.map((slide, index) => <button key={slide.id}
          className={slideIndex === index ? "selected" : ""} type="button" onClick={() => setSlideIndex(index)}>{index + 1}</button>)}</div>}
        {scene.slides.length > 1 && canEdit && <div className="studio-actions"><button className="icon-button" type="button" disabled={slideIndex === 0} onClick={() => {
          const slides = [...scene.slides]; [slides[slideIndex - 1], slides[slideIndex]] = [slides[slideIndex], slides[slideIndex - 1]];
          update({ ...scene, slides }); setSlideIndex(slideIndex - 1);
        }}><ChevronUp size={15} /> Earlier</button><button className="icon-button" type="button" disabled={slideIndex === scene.slides.length - 1} onClick={() => {
          const slides = [...scene.slides]; [slides[slideIndex + 1], slides[slideIndex]] = [slides[slideIndex], slides[slideIndex + 1]];
          update({ ...scene, slides }); setSlideIndex(slideIndex + 1);
        }}><ChevronDown size={15} /> Later</button></div>}
      </div><div className="studio-inspector">
        <div className="studio-fields"><h3>Your post</h3>
          {!externalArtwork && <label>Headline<textarea value={text("headline")?.text ?? ""} disabled={!canEdit} maxLength={600} onChange={(event) => updateLayer("headline", { text: event.target.value } as Partial<TextLayer>)} /></label>}
          {externalArtwork && <p className="muted">Want a different look? Describe your change in “Create a new version” below.</p>}
          <label>Caption<textarea value={caption} disabled={!canEdit || Boolean(busy) || Boolean(packet)} maxLength={4000} onChange={(event) => update(scene, event.target.value)} /></label>
          <details><summary>Create a new version</summary>{imageChoices}
            {canEdit && <button className="icon-button" type="button" disabled={Boolean(busy) || Boolean(dirty) || !photoAssetId || !productImageConfirmed} onClick={() => void regenerate()}><Sparkles size={16} /> Create a new version</button>}
          </details>
        </div>
      </div></div>
      <details><summary>Design details</summary>
        <div className="studio-facts"><strong>Source facts</strong>{design.factual_refs.map((ref, index) => <span key={index}>{ref.field}: {ref.value}</span>)}</div>
        {design.creative_direction?.image_prompt && <div className="studio-facts"><strong>Gemini design direction</strong><p>{design.creative_direction.design_idea}</p><details><summary>Image prompt</summary><p>{design.creative_direction.image_prompt}</p></details></div>}
      </details>
      {Boolean(design.creative_direction?.missing_information.length) && <p className="warning-note">Needs clarification: {design.creative_direction?.missing_information.join("; ")}</p>}
      <details><summary>Tell Falkrona what you like</summary><LearningPanel key={design.id} workspaceId={workspaceId} designId={design.id} csrf={csrf}
        canEdit={canEdit} canApprove={canApprove} /></details>
    </>}
  </section>;
}
