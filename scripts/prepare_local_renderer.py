"""One-time operator setup: download pinned local CPU segmentation weights."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "brandpilot_core" / "src"))
from brandpilot.product_segmentation import MODEL_FILES, MODEL_ROOT

if __name__ == "__main__":
    import pooch
    for name, checksum in MODEL_FILES.items():
        pooch.retrieve("https://github.com/danielgatis/rembg/releases/download/v0.0.0/" + name,
                       known_hash="md5:" + checksum, fname=name, path=MODEL_ROOT)
        print("Ready:", name)
