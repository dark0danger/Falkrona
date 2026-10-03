"""CPU product segmentation. Only the operator setup step downloads weights."""
from functools import lru_cache
import hashlib
from pathlib import Path

from .phase4 import Phase4Error

MODEL_ROOT = Path(__file__).resolve().parents[4] / ".runtime" / "models"
MODEL_FILES = {
    "sam_vit_b_01ec64.encoder.quant.onnx": "26fc0e01d2fa34ed2d3f91259118482d",
    "sam_vit_b_01ec64.decoder.quant.onnx": "45391530307d1aee79b2a1507769e6c7",
}


@lru_cache(maxsize=1)
def _session():
    paths = []
    for name, checksum in MODEL_FILES.items():
        path = MODEL_ROOT / name
        if not path.is_file():
            raise Phase4Error("local_model_missing", "The local product renderer needs setup. Run scripts/prepare_local_renderer.py.")
        if hashlib.md5(path.read_bytes()).hexdigest() != checksum:
            raise Phase4Error("local_model_invalid", "The local segmentation model failed its integrity check.")
        paths.append(str(path))
    import onnxruntime as ort
    from rembg.sessions.sam import SamSession

    class OfflineSamSession(SamSession):
        @classmethod
        def download_models(cls, *args, **kwargs):
            return tuple(paths)

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    session = OfflineSamSession("sam", options)
    # rembg unions SAM's alternative masks. Pick the highest-confidence
    # alternative instead, so unrelated objects do not enter the cutout.
    decoder = session.decoder
    class BestMaskDecoder:
        def run(self, *args, **kwargs):
            masks, scores, low = decoder.run(*args, **kwargs)
            index = int(scores[0].argmax())
            return masks[:, index:index + 1], scores[:, index:index + 1], low
    session.decoder = BestMaskDecoder()
    return session


def segment_product(image, points):
    """Gemini points locate the subject; SAM determines its actual pixel edges."""
    if len(points) < 8:
        raise Phase4Error("product_cutout_required", "Prepare a product direction before rendering.")
    xs, ys = [p["x"] for p in points], [p["y"] for p in points]
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    pad_x, pad_y = (right - left) * .25, (bottom - top) * .2
    box = [max(0, left - pad_x) * image.width / 1000,
           max(0, top - pad_y) * image.height / 1000,
           min(1000, right + pad_x) * image.width / 1000,
           min(1000, bottom + pad_y) * image.height / 1000]
    prompt = [{"type": "rectangle", "data": box}]
    # Multiple interior anchors keep printed fruit/artwork attached to its
    # packaging instead of segmenting those pictures away from the bottle.
    for fraction in (.2, .5, .8):
        prompt.append({"type": "point", "data": [(left + right) * image.width / 2000,
                       (top + (bottom - top) * fraction) * image.height / 1000], "label": 1})
    mask = _session().predict(image.convert("RGB"), sam_prompt=prompt)[0]
    return solid_product_mask(mask)


def solid_product_mask(mask):
    """Packaging artwork/reflections are inside the product, not holes in it."""
    import cv2
    import numpy as np
    from PIL import Image
    binary = (np.asarray(mask) >= 128).astype(np.uint8) * 255
    size = max(3, round(min(mask.size) * .025) | 1)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise Phase4Error("invalid_product_mask", "The local renderer could not find the product.")
    largest = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(binary)
    cv2.drawContours(filled, [largest], -1, 255, cv2.FILLED)
    return Image.fromarray(filled)
