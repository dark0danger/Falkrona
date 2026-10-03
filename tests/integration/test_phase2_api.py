from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.accounts import AuthenticationError, AuthorizationError
from brandpilot.config import RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.models import CredentialRecord
from brandpilot.settings import AppSettings


ROOT = Path(__file__).resolve().parents[2]


class Phase2ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{self.root / 'phase2.db'}")
        Base.metadata.create_all(self.engine)
        self.settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=self.root / "storage",
            runtime=RuntimeConfig(),
            app_secret_key=b"a" * 32,
            credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
            session_cookie_secure=True,
            login_max_attempts=3,
        )
        self.app = create_app(self.settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        fixtures = json.loads(
            (ROOT / "fixtures" / "phase2" / "workspaces.json").read_text(
                encoding="utf-8"
            )
        )["businesses"]
        first = fixtures[0]
        response = self.client.post(
            "/api/v1/setup/owner",
            headers={"X-Setup-Token": self.settings.owner_setup_token},
            json={
                "email": first["owner_email"],
                "password": "owner-one-password",
                "workspace_name": first["name"],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.user_one = response.json()["user_id"]
        self.workspace_one = response.json()["workspace_id"]
        self.csrf_one = self._login(first["owner_email"], "owner-one-password")

        second = fixtures[1]
        self.user_two = self.app.state.accounts.create_user(
            second["owner_email"], "owner-two-password"
        )
        second_client = TestClient(self.app, base_url="https://testserver")
        self.csrf_two = self._login(
            second["owner_email"], "owner-two-password", client=second_client
        )
        created = second_client.post(
            "/api/v1/workspaces",
            headers={"X-CSRF-Token": self.csrf_two},
            json={"name": second["name"]},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.workspace_two = created.json()["workspace_id"]
        self.client_two = second_client

        self.asset_one_content = first["asset_content"].encode("utf-8")
        self.asset_two_content = second["asset_content"].encode("utf-8")
        key_one = f"workspaces/{self.workspace_one}/assets/{first['asset_name']}"
        key_two = f"workspaces/{self.workspace_two}/assets/{second['asset_name']}"
        self.app.state.storage.put_bytes(key_one, self.asset_one_content)
        self.app.state.storage.put_bytes(key_two, self.asset_two_content)
        self.asset_one = self.app.state.accounts.register_asset(
            self.workspace_one,
            key_one,
            first["asset_name"],
            "text/plain",
            hashlib.sha256(self.asset_one_content).hexdigest(),
            len(self.asset_one_content),
        )
        self.asset_two = self.app.state.accounts.register_asset(
            self.workspace_two,
            key_two,
            second["asset_name"],
            "text/plain",
            hashlib.sha256(self.asset_two_content).hexdigest(),
            len(self.asset_two_content),
        )

    def tearDown(self):
        self.client.close()
        self.client_two.close()
        self.engine.dispose()
        self.temp.cleanup()

    def _login(self, email: str, password: str, *, client=None) -> str:
        active = client or self.client
        response = active.post(
            "/api/v1/session", json={"email": email, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=strict", cookie)
        return response.json()["csrf_token"]

    def _create_job(self, client, workspace_id: str, csrf: str, key: str) -> str:
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/jobs",
            headers={"X-CSRF-Token": csrf},
            json={
                "kind": "fixture.artifact",
                "payload": {"fixture": key},
                "dedupe_key": key,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["job_id"]

    def _download(self, client, workspace_id: str, asset_id: str):
        signed = client.get(
            f"/api/v1/workspaces/{workspace_id}/assets/{asset_id}/download-url"
        )
        if signed.status_code != 200:
            return signed
        return client.get(signed.json()["download_url"])

    def test_unauthorized_api_download_sse_and_job_access_are_denied(self):
        anonymous = TestClient(self.app, base_url="https://testserver")
        paths = (
            f"/api/v1/workspaces/{self.workspace_one}/jobs/not-found",
            f"/api/v1/workspaces/{self.workspace_one}/jobs/not-found/events",
            f"/api/v1/workspaces/{self.workspace_one}/assets/{self.asset_one}/download",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(anonymous.get(path).status_code, 401)
        anonymous.close()

    def test_cross_workspace_ids_and_payload_fields_cannot_escape_scope(self):
        first_job = self._create_job(
            self.client, self.workspace_one, self.csrf_one, "first-job"
        )
        second_job = self._create_job(
            self.client_two, self.workspace_two, self.csrf_two, "second-job"
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/workspaces/{self.workspace_two}/jobs/{second_job}"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/workspaces/{self.workspace_one}/jobs/{second_job}"
            ).status_code,
            404,
        )
        cross_download = self._download(
            self.client, self.workspace_two, self.asset_two
        )
        self.assertEqual(cross_download.status_code, 403)
        own_download = self._download(
            self.client, self.workspace_one, self.asset_one
        )
        self.assertEqual(own_download.content, self.asset_one_content)
        forged_payload = self.client.post(
            f"/api/v1/workspaces/{self.workspace_one}/jobs",
            headers={"X-CSRF-Token": self.csrf_one},
            json={
                "kind": "fixture.artifact",
                "payload": {},
                "dedupe_key": "forged-workspace-field",
                "workspace_id": self.workspace_two,
            },
        )
        self.assertEqual(forged_payload.status_code, 422)
        self.assertTrue(first_job)

    def test_analyst_permissions_and_revocation_apply_immediately(self):
        analyst_email = "analyst@example.test"
        self.app.state.accounts.create_user(analyst_email, "analyst-password-long")
        member = self.client.post(
            f"/api/v1/workspaces/{self.workspace_one}/members",
            headers={"X-CSRF-Token": self.csrf_one},
            json={"email": analyst_email, "role": "analyst"},
        )
        self.assertEqual(member.status_code, 201, member.text)
        analyst = TestClient(self.app, base_url="https://testserver")
        csrf = self._login(analyst_email, "analyst-password-long", client=analyst)
        self.assertEqual(
            self._download(analyst, self.workspace_one, self.asset_one).status_code,
            200,
        )
        denied = analyst.post(
            f"/api/v1/workspaces/{self.workspace_one}/jobs",
            headers={"X-CSRF-Token": csrf},
            json={"kind": "fixture.artifact", "payload": {}, "dedupe_key": "analyst"},
        )
        self.assertEqual(denied.status_code, 403)
        principal = self.app.state.accounts.authenticate(
            analyst.cookies.get("brandpilot_session")
        )
        for permission in ("approve", "publish"):
            with self.subTest(permission=permission), self.assertRaises(AuthorizationError):
                self.app.state.accounts.require_permission(
                    principal, self.workspace_one, permission
                )
        revoked = self.client.delete(
            f"/api/v1/workspaces/{self.workspace_one}/members/{member.json()['membership_id']}",
            headers={"X-CSRF-Token": self.csrf_one},
        )
        self.assertEqual(revoked.status_code, 204, revoked.text)
        self.assertEqual(
            self._download(analyst, self.workspace_one, self.asset_one).status_code,
            403,
        )
        analyst.close()

    def test_csrf_expiry_rate_limit_and_encryption_fail_closed(self):
        no_csrf = self.client.post(
            f"/api/v1/workspaces/{self.workspace_one}/jobs",
            json={"kind": "fixture.artifact", "payload": {}, "dedupe_key": "no-csrf"},
        )
        self.assertEqual(no_csrf.status_code, 403)
        refreshed = self.client.get("/api/v1/session/csrf")
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        stale_csrf = self.client.post(
            f"/api/v1/workspaces/{self.workspace_one}/jobs",
            headers={"X-CSRF-Token": self.csrf_one},
            json={"kind": "fixture.artifact", "payload": {}, "dedupe_key": "stale-csrf"},
        )
        self.assertEqual(stale_csrf.status_code, 403)
        self.csrf_one = refreshed.json()["csrf_token"]
        credential_value = "synthetic-provider-value"
        stored = self.client.post(
            f"/api/v1/workspaces/{self.workspace_one}/credentials",
            headers={"X-CSRF-Token": self.csrf_one},
            json={"provider": "fixture_social", "secret": credential_value},
        )
        self.assertEqual(stored.status_code, 201, stored.text)
        self.assertNotIn(credential_value, stored.text)
        with self.app.state.accounts._sessions() as session:
            record = session.get(CredentialRecord, stored.json()["credential_id"])
            self.assertNotIn(credential_value.encode("utf-8"), record.ciphertext)
        self.assertEqual(
            self.app.state.accounts.decrypt_credential(
                self.workspace_one, stored.json()["credential_id"]
            ),
            credential_value,
        )
        raw_session = self.client.cookies.get("brandpilot_session")
        with self.assertRaises(AuthenticationError):
            self.app.state.accounts.authenticate(
                raw_session,
                now=datetime.now(timezone.utc) + timedelta(days=2),
            )
        attacker = TestClient(self.app, base_url="https://testserver")
        for _ in range(3):
            self.assertEqual(
                attacker.post(
                    "/api/v1/session",
                    json={
                        "email": "owner.one@example.test",
                        "password": "incorrect-password",
                    },
                ).status_code,
                401,
            )
        self.assertEqual(
            attacker.post(
                "/api/v1/session",
                json={
                    "email": "owner.one@example.test",
                    "password": "owner-one-password",
                },
            ).status_code,
            429,
        )
        attacker.close()
        revocable = TestClient(self.app, base_url="https://testserver")
        csrf = self._login(
            "owner.two@example.test", "owner-two-password", client=revocable
        )
        self.assertEqual(
            revocable.delete(
                "/api/v1/session", headers={"X-CSRF-Token": csrf}
            ).status_code,
            204,
        )
        self.assertEqual(revocable.get("/api/v1/me").status_code, 401)
        revocable.close()

    def test_tool_call_credential_rejects_forged_workspace_and_job(self):
        job_id = self._create_job(
            self.client, self.workspace_one, self.csrf_one, "tool-call"
        )
        token = self.app.state.run_credentials.issue(
            self.workspace_one,
            job_id,
            ["asset.read"],
            expires_at=int((datetime.now(timezone.utc) + timedelta(minutes=2)).timestamp()),
        )
        valid_body = {
            "workspace_id": self.workspace_one,
            "job_id": job_id,
            "operation": "asset.read",
        }
        valid = self.client.post(
            "/internal/v1/tool-call/authorize",
            headers={"Authorization": f"Bearer {token}"},
            json=valid_body,
        )
        self.assertEqual(valid.status_code, 204, valid.text)
        forged = self.client.post(
            "/internal/v1/tool-call/authorize",
            headers={"Authorization": f"Bearer {token}"},
            json={**valid_body, "workspace_id": self.workspace_two},
        )
        self.assertEqual(forged.status_code, 403)
        altered = self.client.post(
            "/internal/v1/tool-call/authorize",
            headers={"Authorization": f"Bearer {token}x"},
            json=valid_body,
        )
        self.assertEqual(altered.status_code, 403)


if __name__ == "__main__":
    unittest.main()
