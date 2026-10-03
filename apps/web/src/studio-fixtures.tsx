import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { PRESETS, SceneSvg, textLayout, toPng, type Scene } from "./StudioView";

const headlines = [
  "Fresh coffee for office teams",
  "قهوة طازجة لفريقك",
  "قهوة طازجة لفريقك | Fresh coffee for your team",
  "A thoughtful gathering begins with a question about what your office team truly needs",
  "عرض ٢٥٪ | Coffee 25%",
];

function layer(type: "text" | "rectangle" | "image", role: string, x: number, y: number, w: number, h: number, fields: Record<string, unknown>) {
  return { id: crypto.randomUUID(), type, role, x, y, w, h, rotation: 0, opacity: 1, editable: true, ...fields };
}

function fixture(preset: Scene["preset"], text: string, logo: number): Scene {
  return { schema: 1, layout: "editorial", preset, slides: [{ id: crypto.randomUUID(), layers: [
    layer("rectangle", "background", 0, 0, 1000, 1000, { fill: "#f4f6f3" }),
    layer("rectangle", "accent", 62, 70, 76, 10, { fill: "#b83b32" }),
    layer("rectangle", "cta_panel", 0, 650, 1000, 160, { fill: "#dce4df" }),
    layer("rectangle", "footer", 0, 830, 1000, 170, { fill: "#172d2b" }),
    layer("text", "headline", 62, 130, 876, 350, { text, color: "#17231d", font: "Arial", size: 72,
      weight: 700, direction: "auto", align: "start" }),
    layer("text", "summary", 62, 500, 876, 125, { text: "A sourced, editable local composition.", color: "#445149",
      font: "Arial", size: 28, weight: 400, direction: "auto", align: "start" }),
    layer("text", "cta", 62, 670, 850, 120, { text: "Ask us today", color: "#17231d", font: "Arial", size: 34,
      weight: 700, direction: "auto", align: "start" }),
    layer("text", "brand", 62, 870, 850, 65, { text: "Nile Coffee", color: "#ffffff", font: "Arial", size: 30,
      weight: 700, direction: "auto", align: "start" }),
    layer("image", "logo", 760, 35, 180, 125, { asset_id: `fixture-logo-${logo}`, sha256: "fixture", fit: "contain" }),
  ] as Scene["slides"][number]["layers"] }] };
}

function logos(): Record<string, string> {
  return Object.fromEntries([0, 1, 2].map((index) => {
    const canvas = document.createElement("canvas"); canvas.width = 180; canvas.height = 100;
    const context = canvas.getContext("2d")!;
    context.fillStyle = ["#b83b32", "#172d2b", "#406678"][index];
    context.fillRect(0, 0, 180, 100);
    context.fillStyle = "#ffffff"; context.font = "700 48px Arial";
    context.fillText(["NC", "FK", "CT"][index], 22, 66);
    return [`fixture-logo-${index}`, canvas.toDataURL("image/png")];
  }));
}

function FixtureApp() {
  const scenes = useMemo(() => Object.keys(PRESETS).flatMap((preset) =>
    headlines.map((headline, index) => fixture(preset as Scene["preset"], headline, index % 3))), []);
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<Array<{ name: string; sha256: string; bytes: number; dimensions: string }>>([]);
  const [failure, setFailure] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);
  const imageData = useMemo(logos, []);

  useEffect(() => {
    if (index >= scenes.length) return;
    let cancelled = false;
    void (async () => {
      try {
        await document.fonts.ready;
        await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        if (!svgRef.current || cancelled) return;
        const scene = scenes[index];
        const [width, height] = PRESETS[scene.preset];
        if (scene.slides[0].layers.some((entry) => entry.type === "text" && !textLayout(entry, width, height).fits))
          throw new Error(`Text overflows in ${scene.preset}-${index % 5}`);
        const blob = await toPng(svgRef.current, width, height);
        const bitmap = await createImageBitmap(blob);
        const dimensions = `${bitmap.width}x${bitmap.height}`;
        bitmap.close();
        if (dimensions !== `${width}x${height}`) throw new Error(`Unexpected dimensions: ${dimensions}`);
        const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
        const sha256 = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
        if (!cancelled) {
          setResults((entries) => [...entries, { name: `${scene.preset}-${index % 5}`, sha256, bytes: blob.size, dimensions }]);
          setIndex(index + 1);
        }
      } catch (error) { if (!cancelled) setFailure(String(error)); }
    })();
    return () => { cancelled = true; };
  }, [index]);

  return <main style={{ fontFamily: "Arial, sans-serif", padding: 24 }}>
    <h1>Phase 8 renderer fixtures</h1>
    <p id="fixture-status">{failure ? `Failed: ${failure}` : `${results.length} / ${scenes.length} PNGs rendered`}</p>
    <div style={{ width: 180 }}><SceneSvg scene={scenes[Math.min(index, scenes.length - 1)]}
      slideIndex={0} imageData={imageData} svgRef={svgRef} /></div>
    <ol>{results.map((entry) => <li key={entry.name}>{entry.name}: {entry.dimensions}, {entry.bytes} bytes, SHA-256 {entry.sha256}</li>)}</ol>
  </main>;
}

createRoot(document.getElementById("root")!).render(<FixtureApp />);
