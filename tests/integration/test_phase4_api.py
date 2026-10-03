from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.models import AgentToolCall, BudgetReservation
from brandpilot.settings import AppSettings


class Phase4ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'phase4.db'}")
        Base.metadata.create_all(self.engine)
        runtime = RuntimeConfig(
            execution_mode=ExecutionMode.GEMINI_FREE,
            model_provider=ModelProvider.GEMINI,
        )
        self.settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=root / "storage",
            runtime=runtime,
            app_secret_key=b"a" * 32,
            credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
            session_cookie_secure=True,
            gemini_model="gemini-contract-fixture",
            agent_max_model_calls=1,
            agent_max_input_tokens=100,
            agent_max_output_tokens=50,
        )
        self.app = create_app(self.settings, engine=self.engine)
        self.client = TestClient(self.app, base_url="https://testserver")
        setup = self.client.post(
            "/api/v1/setup/owner",
            headers={"X-Setup-Token": self.settings.owner_setup_token},
            json={"email": "owner@example.test", "password": "owner-password-long", "workspace_name": "Falkrona"},
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

    def _create_run(self, prompt="Draft a public launch caption."):
        response = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/agent-runs",
            headers={"X-CSRF-Token": self.csrf},
            json={"prompt": prompt, "dedupe_key": "phase4-run"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_public_run_has_single_provider_and_atomic_reserved_budget(self):
        run = self._create_run()
        self.assertEqual(run["provider"], "gemini")
        self.assertEqual(run["model"], "gemini-contract-fixture")
        self.app.state.phase4.admit_model_call(self.workspace_id, run["id"], input_tokens=60, output_tokens=30)
        with self.assertRaisesRegex(ValueError, "budget"):
            self.app.state.phase4.admit_model_call(self.workspace_id, run["id"], input_tokens=1, output_tokens=1)
        sessions = self.app.state.phase4._sessions
        with sessions() as session:
            reservation = session.query(BudgetReservation).one()
            self.assertEqual(reservation.used_model_calls, 1)
            self.assertEqual(reservation.status, "exhausted")

    def test_private_gemini_prompt_is_rejected_before_run_or_transport(self):
        response = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/agent-runs",
            headers={"X-CSRF-Token": self.csrf},
            json={"prompt": "Contact jane@example.test about the launch.", "dedupe_key": "private"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "blocked_data_policy")

    def test_reviewed_tool_credential_stores_an_artifact_and_rejects_forged_workspace(self):
        run = self._create_run()
        token = self.app.state.run_credentials.issue(
            self.workspace_id,
            run["job_id"],
            ["brand.read", "artifact.write"],
            expires_at=2_000_000_000,
        )
        headers = {"Authorization": f"Bearer {token}"}
        context = self.client.post(
            "/internal/v1/agent-tools/brand-context",
            headers=headers,
            json={"workspace_id": self.workspace_id, "job_id": run["job_id"]},
        )
        self.assertEqual(context.status_code, 200, context.text)
        artifact = self.client.post(
            "/internal/v1/agent-tools/artifacts",
            headers=headers,
            json={"workspace_id": self.workspace_id, "job_id": run["job_id"], "title": "launch-caption", "content": "Public launch caption."},
        )
        self.assertEqual(artifact.status_code, 201, artifact.text)
        forged = self.client.post(
            "/internal/v1/agent-tools/artifacts",
            headers=headers,
            json={"workspace_id": "00000000-0000-0000-0000-000000000000", "job_id": run["job_id"], "title": "escape", "content": "no"},
        )
        self.assertEqual(forged.status_code, 403, forged.text)
        sessions = self.app.state.phase4._sessions
        with sessions() as session:
            calls = session.query(AgentToolCall).filter_by(agent_run_id=run["id"]).all()
            self.assertGreaterEqual(len(calls), 2)

    def test_cancel_is_durable_before_worker_claims_the_job(self):
        run = self._create_run()
        cancelled = self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}/agent-runs/{run['id']}/cancel",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
