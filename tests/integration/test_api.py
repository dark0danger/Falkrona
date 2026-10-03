from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.app import create_app
from brandpilot.config import RuntimeConfig
from brandpilot.database import Base, build_engine
from brandpilot.settings import AppSettings
from brandpilot.storage import LocalStorage, StorageError


class BrokenStorage(LocalStorage):
    def check(self) -> None:
        raise StorageError("storage unavailable")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{self.root / 'api.db'}")
        Base.metadata.create_all(self.engine)
        self.settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=self.root / "storage",
            runtime=RuntimeConfig(),
        )

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_health_and_job_error_are_usable(self):
        app = create_app(self.settings, engine=self.engine)
        with TestClient(app, raise_server_exceptions=False) as client:
            self.assertEqual(client.get("/health/live").json(), {"status": "alive"})
            ready = client.get("/health/ready")
            self.assertEqual(ready.status_code, 200)
            missing = client.get("/api/not-found")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["detail"], "Not Found")
            self.assertTrue(missing.headers["X-Request-ID"])

    def test_storage_failure_degrades_readiness(self):
        app = create_app(
            self.settings,
            engine=self.engine,
            storage=BrokenStorage(self.root / "storage"),
        )
        with TestClient(app) as client:
            response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["components"]["storage"]["status"], "failed")

    def test_offline_boot_makes_no_external_connection(self):
        app = create_app(self.settings, engine=self.engine)
        original_connect = socket.socket.connect

        def loopback_only(sock, address):
            host = address[0] if isinstance(address, tuple) else ""
            if host not in {"127.0.0.1", "::1", "localhost"}:
                raise AssertionError(f"external network attempted: {address}")
            return original_connect(sock, address)

        with patch.object(socket.socket, "connect", new=loopback_only):
            with TestClient(app) as client:
                response = client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["execution_mode"], "offline_test")
        self.assertFalse(response.json()["paid_calls_enabled"])


if __name__ == "__main__":
    unittest.main()
