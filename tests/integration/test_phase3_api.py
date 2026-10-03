from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from apps.api.app import create_app
from brandpilot.config import RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.settings import AppSettings


class Phase3ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'phase3.db'}")
        Base.metadata.create_all(self.engine)
        self.settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=root / "storage",
            runtime=RuntimeConfig(),
            app_secret_key=b"a" * 32,
            credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
            session_cookie_secure=True,
        )
        self.app = create_app(self.settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        setup = self.client.post(
            "/api/v1/setup/owner",
            headers={"X-Setup-Token": self.settings.owner_setup_token},
            json={"email": "owner@example.test", "password": "owner-password-long", "workspace_name": "Falkrona Demo"},
        )
        self.assertEqual(setup.status_code, 201, setup.text)
        self.workspace_id = setup.json()["workspace_id"]
        login = self.client.post("/api/v1/session", json={"email": "owner@example.test", "password": "owner-password-long"})
        self.assertEqual(login.status_code, 200, login.text)
        self.csrf = login.json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_asset_gallery_and_upload_retry_are_deduplicated_by_client_key(self):
        image = BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 120)).save(image, format="PNG")
        headers = {"X-CSRF-Token": self.csrf}
        first = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/assets",
            headers=headers,
            files={"file": ("logo.png", image.getvalue(), "image/png")},
        )
        self.assertEqual(first.status_code, 201, first.text)
        listed = self.client.get(f"/api/v1/workspaces/{self.workspace_id}/assets")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["assets"]), 1)
        retry = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/assets",
            headers=headers,
            files={"file": ("logo.png", image.getvalue(), "image/png")},
        )
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/v1/workspaces/{self.workspace_id}/assets").json()["assets"]), 1)

    def test_product_import_preview_confirm_and_onboarding_resume(self):
        csv = "اسم المنتج,السعر,التوفر\nقهوة,125,متاح\n".encode("utf-8")
        headers = {"X-CSRF-Token": self.csrf}
        imported = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/imports",
            headers=headers,
            data={"dedupe_key": "catalog-1"},
            files={"file": ("catalog.csv", csv, "text/csv")},
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(imported.json()["preview"]["rows"][0]["name"], "قهوة")
        import_id = imported.json()["id"]
        confirmed = self.client.post(f"/api/v1/workspaces/{self.workspace_id}/imports/{import_id}/confirm", headers=headers)
        self.assertEqual(confirmed.json()["products_created"], 1)
        repeated = self.client.post(f"/api/v1/workspaces/{self.workspace_id}/imports/{import_id}/confirm", headers=headers)
        self.assertEqual(repeated.json()["products_created"], 1)

        status = self.client.get(f"/api/v1/workspaces/{self.workspace_id}/onboarding/status").json()
        self.assertEqual(status["next_question"], "brand_name")
        first_turn = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/interview/turns",
            headers=headers,
            json={"question_key": "brand_name", "answer": "Falkrona", "confirmed": True},
        )
        self.assertEqual(first_turn.json()["next_question"], "category")
        contradiction = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/interview/turns",
            headers=headers,
            json={"question_key": "brand_name", "answer": "Falkrona Studio", "confirmed": True},
        )
        self.assertIsNotNone(contradiction.json()["contradiction"])
        resumed = self.client.get(f"/api/v1/workspaces/{self.workspace_id}/onboarding/status")
        self.assertEqual(resumed.json()["next_question"], "category")

    def test_manual_profile_and_safe_url_import(self):
        headers = {"X-CSRF-Token": self.csrf}
        proposal = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/brand/proposals",
            headers=headers,
            json={"fields": {"brand_name": "Falkrona", "price": "125 EGP", "address": "Cairo"}},
        )
        self.assertEqual(proposal.status_code, 201, proposal.text)
        version = proposal.json()["version"]
        confirmed = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/brand/versions/{version}/confirm",
            headers=headers,
        )
        self.assertEqual(confirmed.json()["status"], "confirmed")
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{self.workspace_id}/brand").json()["profile"]["fields"]["brand_name"], "Falkrona")

        blocked = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/imports/url",
            headers=headers,
            json={"url": "https://example.com", "dedupe_key": "site-1"},
        )
        self.assertEqual(blocked.status_code, 201, blocked.text)
        self.assertEqual(blocked.json()["status"], "blocked_offline")
        rejected = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/imports/url",
            headers=headers,
            json={"url": "http://127.0.0.1", "dedupe_key": "site-2"},
        )
        self.assertEqual(rejected.status_code, 422)


if __name__ == "__main__":
    unittest.main()
