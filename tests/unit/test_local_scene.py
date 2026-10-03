from copy import deepcopy
from io import BytesIO
import unittest

from PIL import Image, ImageDraw

from brandpilot.design_direction import DesignDirection
from brandpilot.local_scene import LocalSceneExecutor, product_cutout
from brandpilot.phase4 import Phase4Error
from tests.integration.test_design_direction import DIRECTION as BROWSER_DIRECTION

# Historic renderer fixtures remain independent of the current browser pipeline.
DIRECTION = {**BROWSER_DIRECTION, "scene_recipe": {
    "background_style": "soft_gradient", "background_color": "#ffffff", "accent_color": "#172d2b",
    "product_center_x": 500, "product_top": 480, "product_width": 450, "product_height": 440,
    "logo_corner": "upper_left", "product_mask": [{"x": x, "y": y} for x, y in
        [(350,100),(450,80),(550,80),(650,100),(680,300),(680,850),(620,900),(500,920),(380,900),(320,850),(320,300),(340,180)]]}}


def identity(transparent=False):
    image = Image.new("RGBA", (400, 500), (0, 100, 255, 0 if transparent else 255))
    ImageDraw.Draw(image).polygon([(140, 50), (180, 40), (220, 40), (260, 50), (272, 150),
        (272, 425), (248, 450), (200, 460), (152, 450), (128, 425), (128, 150), (136, 90)], fill="orange")
    ImageDraw.Draw(image).rectangle((160, 180, 240, 250), fill="red")
    output = BytesIO(); image.save(output, "PNG")
    return output.getvalue()


def fixture_segmenter(image, points):
    mask = Image.new("L", image.size)
    mask.putdata([255 if rgb[:3] in {(255, 165, 0), (255, 0, 0)} else 0 for rgb in image.getdata()])
    return mask


class LocalSceneTests(unittest.TestCase):
    def test_outline_removes_original_scenery_preserves_product_pixels(self):
        cutout, method = product_cutout(identity(), DIRECTION["scene_recipe"]["product_mask"], fixture_segmenter)
        self.assertEqual(method, "local_sam_segmentation")
        self.assertLess(cutout.width, 400)
        self.assertEqual(cutout.getpixel((cutout.width // 2, 180))[0:3], (255, 0, 0))
        self.assertEqual(cutout.getpixel((0, 0))[3], 0)
        self.assertTrue(cutout.getchannel("A").getextrema()[0] < 255)

    def test_local_recipe_controls_background_and_product_position_with_clear_copy_space(self):
        executor = LocalSceneExecutor(fixture_segmenter)
        recipe = deepcopy(DIRECTION["scene_recipe"])
        left = executor({**recipe, "product_center_x": 360}, identity(), ["#172d2b", "#ffffff", "#172d2b"], lambda: None)
        right = executor({**recipe, "product_center_x": 640}, identity(), ["#172d2b", "#ffffff", "#172d2b"], lambda: None)
        self.assertNotEqual(left["image"], right["image"])
        with Image.open(BytesIO(left["image"])) as scene:
            self.assertEqual(scene.size, (1080, 1350))
            self.assertEqual(scene.getpixel((500, 300)), (255, 255, 255))
            self.assertNotEqual(scene.getpixel((40, 1100)), (0, 100, 255))

    def test_transparent_product_skips_estimated_mask_and_whole_photo_mask_rejected(self):
        cutout, method = product_cutout(identity(True), [])
        self.assertEqual(method, "owner_transparent_upload")
        self.assertLess(cutout.width, 400)
        with self.assertRaises(Phase4Error): product_cutout(identity(), [])
        whole_photo = [{"x": x, "y": y} for x, y in [(0, 0), (500, 0), (1000, 0), (1000, 500), (1000, 1000), (500, 1000), (0, 1000), (0, 500)]]
        with self.assertRaises(Phase4Error): product_cutout(identity(), whole_photo, lambda img, _: Image.new("L", img.size, 255))

    def test_gemini_hint_does_not_clip_the_actual_product_boundary(self):
        points = [{"x": p["x"], "y": max(300, p["y"])} for p in DIRECTION["scene_recipe"]["product_mask"]]
        cutout, _ = product_cutout(identity(), points, fixture_segmenter)
        self.assertEqual(cutout.height, 421)

    def test_missing_local_weights_fail_without_downloading(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        from brandpilot import product_segmentation
        product_segmentation._session.cache_clear()
        with TemporaryDirectory() as folder, patch.object(product_segmentation, "MODEL_ROOT", Path(folder)):
            with self.assertRaises(Phase4Error) as failure:
                product_segmentation._session()
        self.assertEqual(failure.exception.code, "local_model_missing")

    def test_label_artwork_is_not_removed_as_a_hole_in_the_product(self):
        from brandpilot.product_segmentation import solid_product_mask
        mask = Image.new("L", (200, 300))
        draw = ImageDraw.Draw(mask)
        draw.rectangle((60, 20, 140, 280), fill=255)
        draw.ellipse((80, 150, 120, 210), fill=0)
        cleaned = solid_product_mask(mask)
        self.assertEqual(cleaned.getpixel((100, 180)), 255)
        self.assertEqual(cleaned.getpixel((10, 180)), 0)

    def test_recipe_bounds_and_copy_validation(self):
        for changes in [{"product_top": 100}, {"background_color": "url(unsafe)"}, {"product_mask": [{"x": 1, "y": 1}]}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DesignDirection.model_validate({**DIRECTION, "scene_recipe": {**DIRECTION["scene_recipe"], **changes}})
        with self.assertRaises(ValueError): DesignDirection.model_validate({**DIRECTION, "headline": "A truncated sentence…"})


if __name__ == "__main__": unittest.main()
