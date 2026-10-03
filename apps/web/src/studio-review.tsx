import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { SceneSvg, toPng, type Scene } from "./StudioView";
import "./styles.css";
import designPolicy from "../../../infra/hermes/skills/social-media-graphic-design/references/design-policy.json";
import photoData from "./assets/tepes-unbranded-juice-draft-v2.png?inline";
import logoData from "./assets/tepes-page-profile-draft.jpg?inline";

const scene: Scene = { schema: 1, layout: "product", preset: designPolicy.canvas.preset as Scene["preset"], slides: [{ id: crypto.randomUUID(), layers: [
  { id: crypto.randomUUID(), type: "rectangle", role: "background", x: 0, y: 0, w: 1000, h: 1000,
    rotation: 0, opacity: 1, editable: true, fill: "#ffffff" },
  { id: crypto.randomUUID(), type: "image", role: "photo", x: 0, y: 0, w: 1000, h: 1000,
    rotation: 0, opacity: 1, editable: true, asset_id: "sample-photo", sha256: "sample", fit: "cover" },
  { id: crypto.randomUUID(), type: "image", role: "logo", x: 50, y: 32, w: 145, h: 145,
    rotation: 0, opacity: 1, editable: true, asset_id: "sample-logo", sha256: "sample", fit: "contain" },
  { id: crypto.randomUUID(), type: "text", role: "brand", x: 215, y: 69, w: 300, h: 65,
    rotation: 0, opacity: 1, editable: true, text: "", color: "#0f5155", font: "Arial",
    size: designPolicy.type_scale.brand, weight: 700, direction: "ltr", align: "start" },
  { id: crypto.randomUUID(), type: "text", role: "headline", x: 65, y: 180, w: 870, h: 165,
    rotation: 0, opacity: 1, editable: true, text: "عصير\nعلى مزاجك", color: "#0f5155",
    font: "Arial", size: designPolicy.type_scale.headline, weight: 700, direction: "rtl", align: "center" },
  { id: crypto.randomUUID(), type: "text", role: "cta", x: 65, y: 365, w: 870, h: 58,
    rotation: 0, opacity: 1, editable: true, text: "خذ لحظتك", color: "#0f5155",
    font: "Arial", size: designPolicy.type_scale.cta, weight: 400, direction: "rtl", align: "center" },
] }] };

const englishScene: Scene = { ...scene, slides: scene.slides.map((slide) => ({ ...slide,
  layers: slide.layers.map((layer) => {
    if (layer.type === "text" && layer.role === "headline")
      return { ...layer, text: "A moment for juice", direction: "ltr" as const };
    if (layer.type === "text" && layer.role === "cta")
      return { ...layer, text: "Make it yours", direction: "ltr" as const };
    return layer;
  }),
})) };

function Review() {
  const [language, setLanguage] = useState<"en" | "ar">("ar");
  const images: Record<string, string> = { "sample-photo": photoData, "sample-logo": logoData };
  const [error, setError] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);
  const renderOnly = new URLSearchParams(window.location.search).has("render");
  async function save() {
    if (!svgRef.current) return;
    try {
      const png = await toPng(svgRef.current, designPolicy.canvas.width, designPolicy.canvas.height);
      const url = URL.createObjectURL(png);
      const link = document.createElement("a"); link.href = url; link.download = `tepes-review-v3-${language}.png`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (reason) { setError(String(reason)); }
  }
  if (renderOnly) return <><style>{"html, body, #root { margin: 0; width: 1080px; height: 1350px; overflow: hidden; }"}</style>
    <div style={{ width: 1080, height: 1350 }}><SceneSvg scene={scene} slideIndex={0} imageData={images} svgRef={svgRef} /></div></>;
  return <main style={{ fontFamily: "Arial, sans-serif", margin: "24px auto", maxWidth: 680, padding: 16 }}>
    <h1 style={{ fontSize: 22 }}>TepeS design review</h1>
    <p>Page profile image and illustrative unbranded bottle. 1080 × 1350 PNG. Draft only.</p>
    {error && <p role="alert">{error}</p>}
    <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
      <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
      <button type="button" aria-pressed={language === "ar"} onClick={() => setLanguage("ar")}>العربية</button>
      <button type="button" disabled={!images["sample-photo"] || !images["sample-logo"]} onClick={() => void save()}>Download review PNG</button>
    </div>
    <div style={{ marginTop: 20, width: "100%", aspectRatio: "4 / 5" }}>
      <SceneSvg scene={language === "ar" ? scene : englishScene} slideIndex={0} imageData={images} svgRef={svgRef} />
    </div>
  </main>;
}

createRoot(document.getElementById("root")!).render(<Review />);
