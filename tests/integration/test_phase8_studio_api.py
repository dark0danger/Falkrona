from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.settings import AppSettings
from tests.integration.branding_fixture import complete_branding


class StudioApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'studio.db'}")
        Base.metadata.create_all(self.engine)
        settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:", storage_root=root / "storage",
            runtime=RuntimeConfig(execution_mode=ExecutionMode.OFFLINE_TEST, model_provider=ModelProvider.NONE),
            app_secret_key=b"a" * 32, credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
        )
        self.client = TestClient(create_app(settings, engine=self.engine), base_url="https://testserver")
        setup = self.client.post("/api/v1/setup/owner", headers={"X-Setup-Token": settings.owner_setup_token},
                                 json={"email": "owner@example.test", "password": "owner-password-long", "workspace_name": "A"})
        self.assertEqual(setup.status_code, 201, setup.text)
        self.workspace = setup.json()["workspace_id"]
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        self.base = f"/api/v1/workspaces/{self.workspace}"
        proposal = self.client.post(f"{self.base}/brand/proposals", headers=self.csrf,
                                    json={"fields": {"brand_name": "Nile Coffee", "category": "coffee"}})
        self.client.post(f"{self.base}/brand/versions/{proposal.json()['version']}/confirm", headers=self.csrf)
        self.branding = complete_branding(self.client, self.base, self.csrf)
        plan = self.client.post(f"{self.base}/plans", headers=self.csrf,
                                json={"week_start": "2026-12-28", "goal": "awareness",
                                      "platforms": ["instagram"], "cadence": 1}).json()
        self.plan_id = plan["id"]
        self.item_id = plan["items"][0]["id"]
        self.design_path = f"{self.base}/plans/{self.plan_id}/items/{self.item_id}/design"

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    @staticmethod
    def png(size: tuple[int, int]) -> bytes:
        image = Image.new("RGB", size, "#182d2b")
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()

    def test_immutable_revisions_undo_source_and_export_package(self):
        self.assertEqual(self.client.post(self.design_path).status_code, 403)
        created = self.client.post(self.design_path, headers=self.csrf)
        self.assertEqual(created.status_code, 201, created.text)
        first = created.json()
        self.assertEqual(len(first["scene"]["slides"]), 2)
        scene = deepcopy(first["scene"])
        headline = next(layer for layer in scene["slides"][0]["layers"] if layer["role"] == "headline")
        headline["text"] = "A fresh coffee story"
        revised = self.client.post(f"{self.base}/designs/{first['id']}/revisions", headers=self.csrf,
                                   json={"scene": scene, "caption": "Ask us about coffee"})
        self.assertEqual(revised.status_code, 201, revised.text)
        second = revised.json()
        self.assertEqual(second["revision"], 2)
        self.assertTrue(second["needs_fact_review"])
        self.assertEqual(self.client.get(f"{self.base}/designs/{first['id']}").json()["scene"], first["scene"])
        self.assertEqual(self.client.post(f"{self.base}/designs/{first['id']}/revisions", headers=self.csrf,
                                          json={"scene": scene, "caption": "X"}).status_code, 409)
        restored = self.client.post(f"{self.base}/designs/{second['id']}/revisions", headers=self.csrf,
                                    json={"scene": first["scene"], "caption": first["caption"]})
        self.assertEqual(restored.status_code, 201, restored.text)
        self.assertEqual(restored.json()["scene"], first["scene"])
        self.assertEqual(self.client.get(self.design_path).json()["current"]["revision"], 3)
        version = restored.json()
        for slide in version["scene"]["slides"]:
            path = f"{self.base}/designs/{version['id']}/slides/{slide['id']}/renders"
            wrong = self.client.post(path, headers=self.csrf, data={"preset": "portrait"},
                                     files={"file": ("wrong.png", self.png((100, 100)), "image/png")})
            self.assertEqual(wrong.status_code, 422)
            good = self.client.post(path, headers=self.csrf, data={"preset": "portrait"},
                                    files={"file": ("slide.png", self.png((1080, 1350)), "image/png")})
            self.assertEqual(good.status_code, 200, good.text)
        package = self.client.get(f"{self.base}/designs/{version['id']}/package")
        self.assertEqual(package.status_code, 200, package.text)
        with ZipFile(BytesIO(package.content)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["caption"], first["caption"])
            self.assertEqual([slide["order"] for slide in manifest["slides"]], [1, 2])
            self.assertEqual([slide["filename"] for slide in manifest["slides"]],
                             ["01-portrait.png", "02-portrait.png"])
            self.assertEqual([slide["jpeg_filename"] for slide in manifest["slides"]],
                             ["01-portrait.jpg", "02-portrait.jpg"])
            self.assertEqual(archive.read("caption.txt").decode(), first["caption"])
            self.assertEqual(json.loads(archive.read("scene.json")), first["scene"])
            self.assertEqual(len(archive.read("01-portrait.png")) > 100, True)
            with Image.open(BytesIO(archive.read("01-portrait.jpg"))) as jpeg:
                self.assertEqual(jpeg.size, (1080, 1350))

    def test_asset_hash_reference_and_workspace_boundary(self):
        created = self.client.post(self.design_path, headers=self.csrf).json()
        image = self.png((120, 120))
        uploaded = self.client.post(f"{self.base}/assets", headers=self.csrf,
                                    files={"file": ("logo.png", image, "image/png")})
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        asset = uploaded.json()
        traits = self.client.get(f"{self.base}/assets/{asset['id']}/reference-traits")
        self.assertEqual(traits.status_code, 200, traits.text)
        self.assertFalse(traits.json()["source_logo_used"])
        scene = deepcopy(created["scene"])
        scene["slides"][0]["layers"].append({"id": "c6563758-9977-452e-9b53-4819d9acda9d", "type": "image",
            "role": "logo", "asset_id": asset["id"], "sha256": "0" * 64, "fit": "contain",
            "x": 780, "y": 80, "w": 150, "h": 150, "rotation": 0, "opacity": 1, "editable": True})
        invalid = self.client.post(f"{self.base}/designs/{created['id']}/revisions", headers=self.csrf,
                                   json={"scene": scene, "caption": created["caption"]})
        self.assertEqual(invalid.status_code, 422)
        scene["slides"][0]["layers"][-1]["sha256"] = asset["sha256"]
        valid = self.client.post(f"{self.base}/designs/{created['id']}/revisions", headers=self.csrf,
                                 json={"scene": scene, "caption": created["caption"]})
        self.assertEqual(valid.status_code, 201, valid.text)
        other = self.client.post("/api/v1/workspaces", headers=self.csrf, json={"name": "B"}).json()["workspace_id"]
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{other}/designs/{valid.json()['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{other}/assets/{asset['id']}/reference-traits").status_code, 422)

    def test_regenerate_uses_workspace_images_logo_colors_and_audience_language(self):
        complete_branding(self.client, self.base, self.csrf, fields={"audience": "فرق القاهرة"})
        first = self.client.post(self.design_path, headers=self.csrf).json()
        logo_image = Image.new("RGBA", (120, 80), "#ffffff")
        for x in range(60):
            for y in range(80):
                logo_image.putpixel((x, y), (23, 45, 43, 255))
        logo_image.putpixel((119, 79), (0, 0, 0, 0))
        buffer = BytesIO()
        logo_image.save(buffer, "PNG")
        logo = self.client.post(f"{self.base}/branding/assets/logo", headers=self.csrf,
                                files={"file": ("brand-logo.png", buffer.getvalue(), "image/png")}).json()
        complete_branding(self.client, self.base, self.csrf, logo=logo["id"])
        photo = self.client.post(f"{self.base}/assets", headers=self.csrf,
                                 files={"file": ("office-photo.png", self.png((500, 625)), "image/png")}).json()
        path = f"{self.base}/designs/{first['id']}/regenerate"
        payload = {"logo_asset_id": logo["id"], "photo_asset_id": photo["id"],
                   "language": "auto", "product_image_confirmed": True, "logo_includes_name": True}
        self.assertEqual(self.client.post(path, json=payload).status_code, 403)
        unconfirmed = self.client.post(path, headers=self.csrf,
                                       json={**payload, "product_image_confirmed": False})
        self.assertEqual(unconfirmed.status_code, 422)
        response = self.client.post(path, headers=self.csrf, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        revised = response.json()
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["scene"]["preset"], "portrait")
        layers = revised["scene"]["slides"][0]["layers"]
        by_role = {layer["role"]: layer for layer in layers}
        self.assertEqual(by_role["background"]["fill"], "#ffffff")
        self.assertEqual(by_role["headline"]["color"], "#172d2b")
        self.assertEqual(by_role["headline"]["direction"], "rtl")
        self.assertEqual(by_role["brand"]["text"], "")
        self.assertEqual(by_role["logo"]["x"], 810)
        self.assertEqual(by_role["photo"]["h"], 500)
        self.assertNotIn("copy_field", by_role)
        self.assertEqual(by_role["photo"]["fit"], "contain")
        self.assertEqual(by_role["photo"]["sha256"], photo["sha256"])
        self.assertNotIn("summary", by_role)
        self.assertNotIn("Invite", by_role["headline"]["text"])
        self.assertEqual(self.client.get(f"{self.base}/designs/{first['id']}").json()["scene"], first["scene"])
        self.assertEqual(self.client.post(path, headers=self.csrf, json=payload).status_code, 409)


if __name__ == "__main__":
    unittest.main()
