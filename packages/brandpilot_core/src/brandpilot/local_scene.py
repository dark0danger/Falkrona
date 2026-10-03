"""Execute Gemini's bounded scene recipe locally, preserving actual product pixels."""
from io import BytesIO
import hashlib
import math
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from .phase4 import Phase4Error


def product_cutout(content, points, segmenter=None):
    try:
        with Image.open(BytesIO(content)) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError("Product image is too large")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.info.clear()
        alpha = image.getchannel("A")
        histogram = alpha.histogram()
        transparent = sum(histogram[:128]) / (image.width * image.height)
        if transparent < .02:
            if len(points) < 8:
                raise Phase4Error("product_cutout_required", "Gemini could not isolate the product. Use a transparent product photo or prepare a new direction.")
            if len({(p["x"], p["y"]) for p in points}) < 8:
                raise Phase4Error("invalid_product_mask", "The product outline is incomplete; prepare a new direction.")
            if segmenter is None:
                from .product_segmentation import segment_product
                segmenter = segment_product
            mask = segmenter(image, points).convert("L")
            if mask.size != image.size:
                raise Phase4Error("invalid_product_mask", "The local product mask has incorrect dimensions.")
            area = sum(mask.histogram()[128:]) / (image.width * image.height)
            if not .01 <= area <= .9:
                raise Phase4Error("invalid_product_mask", "The outline must isolate the product, not the whole photograph.")
            image.putalpha(ImageChops.multiply(alpha, mask))
            method = "local_sam_segmentation"
        else:
            method = "owner_transparent_upload"
        bounds = image.getchannel("A").getbbox()
        if not bounds:
            raise Phase4Error("invalid_product_mask", "No visible product was isolated.")
        return image.crop(bounds), method
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise Phase4Error("invalid_product_image", "Upload a readable product photo.") from exc


class LocalSceneExecutor:
    def __init__(self, segmenter=None):
        self.segmenter = segmenter

    def __call__(self, recipe, identity, palette, progress):
        from .design_direction import SceneRecipe
        recipe = SceneRecipe.model_validate(recipe).model_dump()
        allowed = {color.lower() for color in palette}
        if recipe["background_color"].lower() not in allowed or recipe["accent_color"].lower() not in allowed:
            raise Phase4Error("invalid_scene_palette", "The local design must use colors from the brand logo.")
        if recipe["background_color"].lower() != palette[1].lower():
            raise Phase4Error("invalid_scene_palette", "Use the brand's light palette color for the reserved copy area.")
        progress()
        # CPU model initialization/inference may outlast the job lease. Keep
        # cancellation and lease renewal responsive while the local task runs.
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(product_cutout, identity, recipe["product_mask"], self.segmenter)
        deadline = time.monotonic() + 180
        try:
            while True:
                try:
                    product, method = future.result(timeout=2)
                    break
                except TimeoutError:
                    progress()
                    if time.monotonic() >= deadline:
                        raise Phase4Error("local_render_timeout", "Product isolation timed out. The saved Gemini direction is preserved.")
        except Phase4Error:
            raise
        except Exception as exc:
            raise Phase4Error("local_render_failed", "The local product renderer failed. The saved Gemini direction is preserved.") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        base = tuple(bytes.fromhex(recipe["background_color"][1:]))
        accent = tuple(bytes.fromhex(recipe["accent_color"][1:]))
        # Gentle brand-color atmosphere below the clear copy area; no scenery
        # from the uploaded product photo enters this background.
        low = Image.new("RGB", (240, 300), base)
        pixels = []
        for y in range(300):
            for x in range(240):
                lower = max(0, (y / 300 - .45) / .55)
                intensity = 0
                if recipe["background_style"] == "soft_gradient":
                    intensity = .18 * lower
                elif recipe["background_style"] == "spotlight":
                    distance = math.hypot((x / 240 - recipe["product_center_x"] / 1000) * 1.5, y / 300 - .76)
                    intensity = .16 * lower * min(1, distance * 2)
                pixels.append(tuple(round(base[c] * (1 - intensity) + accent[c] * intensity) for c in range(3)))
        low.putdata(pixels)
        canvas = low.resize((1080, 1350), Image.Resampling.BICUBIC).convert("RGBA")
        # Enforce exact, quiet headline background rather than relying on prose.
        ImageDraw.Draw(canvas).rectangle((0, 0, 1079, 606), fill=base + (255,))
        max_size = (round(recipe["product_width"] * 1.08), round(recipe["product_height"] * 1.35))
        product.thumbnail(max_size, Image.Resampling.LANCZOS)
        x = round(recipe["product_center_x"] * 1.08 - product.width / 2)
        y = round(recipe["product_top"] * 1.35)
        shadow = Image.new("RGBA", canvas.size)
        bottom = y + product.height
        ImageDraw.Draw(shadow).ellipse((x - 20, bottom - 22, x + product.width + 20, bottom + 18), fill=(0, 0, 0, 45))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        canvas.alpha_composite(shadow)
        canvas.alpha_composite(product, (x, y))
        progress()
        output = BytesIO(); canvas.convert("RGB").save(output, "PNG")
        return {"image": output.getvalue(), "cutout_method": method,
                "product_identity_sha256": hashlib.sha256(identity).hexdigest(), "product_cutout_review_required": method == "local_sam_segmentation"}


def validate_local_scene(content, identity_sha):
    if hashlib.sha256(content).hexdigest() == identity_sha:
        raise Phase4Error("invalid_local_scene", "The renderer must create a new composition.")
    with Image.open(BytesIO(content)) as image:
        if image.size != (1080, 1350) or image.format != "PNG":
            raise Phase4Error("invalid_local_scene", "The local scene must be a 1080×1350 PNG.")
    return content
