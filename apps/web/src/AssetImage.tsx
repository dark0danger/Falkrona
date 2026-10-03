import { useEffect, useState } from "react";
import { ImageIcon } from "lucide-react";

export function AssetImage({ workspaceId, assetId, alt, className = "" }: {
  workspaceId: string; assetId?: string | null; alt: string; className?: string;
}) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    setUrl("");
    if (!assetId) return;
    const controller = new AbortController();
    void fetch(`/api/v1/workspaces/${workspaceId}/assets/${assetId}/download-url`, { credentials: "include", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Image unavailable"); return response.json(); })
      .then(data => setUrl(data.download_url)).catch(() => {});
    return () => controller.abort();
  }, [workspaceId, assetId]);
  return <div className={`asset-image ${className}`}>
    {url ? <img src={url} alt={alt} loading="lazy" onError={() => setUrl("")} /> : <ImageIcon size={28} aria-label={`${alt}: preview unavailable`} />}
  </div>;
}
