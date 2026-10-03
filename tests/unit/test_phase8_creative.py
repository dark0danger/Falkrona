from copy import deepcopy
from io import BytesIO
import unittest
import uuid

from PIL import Image, ImageDraw

from brandpilot.creative import CreativeError, PRESETS, _logo_palette, reference_traits, starter_scene, validate_scene


class CreativeSceneTests(unittest.TestCase):
    def test_thirty_language_and_preset_scenes_have_valid_bounds(self):
        headlines = [
            "Fresh coffee for office teams",
            "قهوة طازجة لفريقك",
            "قهوة طازجة | Coffee for your team",
            "An intentionally long headline about planning a thoughtful office gathering together",
            "عرض 25% until 2026-12-31 | Coffee ٢٥٪",
        ]
        for preset in PRESETS:
            for headline in headlines:
                with self.subTest(preset=preset, headline=headline):
                    scene = starter_scene({"title": headline, "concept": headline,
                                           "cta": "اسألنا | Ask us", "format": "post",
                                           "factual_refs": [{"field": "brand_name", "value": "Nile Coffee"}]})
                    scene["preset"] = preset
                    self.assertEqual(validate_scene(scene, {}), scene)

    def test_untrusted_layers_and_out_of_bounds_fail_closed(self):
        scene = starter_scene({"title": "Coffee", "concept": "Coffee", "cta": "Ask",
                               "format": "post", "factual_refs": []})
        for edit in (
            lambda copy: copy["slides"][0]["layers"][2].update({"type": "script"}),
            lambda copy: copy["slides"][0]["layers"][2].update({"x": 900}),
            lambda copy: copy["slides"][0]["layers"][2].update({"font": "MissingFont"}),
            lambda copy: copy["slides"][0]["layers"][2].update({"text": "<script>alert(1)</script>"}),
        ):
            changed = deepcopy(scene)
            edit(changed)
            with self.assertRaises(CreativeError):
                validate_scene(changed, {})

    def test_reference_extracts_traits_not_source_copy(self):
        image = Image.new("RGB", (48, 24), "#e35b46")
        buffer = BytesIO()
        image.save(buffer, "PNG")
        traits = reference_traits(buffer.getvalue())
        self.assertEqual(traits["aspect_ratio"], 2)
        self.assertTrue(traits["palette"])
        self.assertFalse(traits["source_copy_used"])
        self.assertFalse(traits["source_logo_used"])

    def test_antialiased_jpeg_logo_keeps_dark_brand_color(self):
        image = Image.new("RGB", (200, 200), "white")
        ImageDraw.Draw(image).ellipse((45, 35, 155, 145), fill="#0b565a")
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=82)
        ink, paper, _ = _logo_palette(buffer.getvalue())
        self.assertLess(sum(abs(int(ink[index:index + 2], 16) - int("#0b565a"[index:index + 2], 16))
                            for index in (1, 3, 5)), 30)
        self.assertEqual(paper, "#ffffff")

    def test_transparent_colored_logo_adds_neutral_contrast_without_falkrona_ink(self):
        image=Image.new('RGBA',(120,80),(0,0,0,0))
        ImageDraw.Draw(image).rectangle((10,10,60,70),fill='#0b565a')
        ImageDraw.Draw(image).rectangle((65,10,110,70),fill='#258f45')
        stream=BytesIO();image.save(stream,'PNG')
        ink,paper,accent=_logo_palette(stream.getvalue())
        self.assertEqual(ink,'#0b565a');self.assertEqual(paper,'#ffffff')
        self.assertNotIn('#172d2b',(ink,paper,accent))


if __name__ == "__main__":
    unittest.main()
