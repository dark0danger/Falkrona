import tempfile
import unittest
import base64

from brandpilot.settings import AppSettings, ConfigurationError


class AppSettingsTests(unittest.TestCase):
    def test_https_meta_callback_requires_secure_cookies(self):
        values = {
            "BRANDPILOT_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "BRANDPILOT_STORAGE_ROOT": ".runtime/storage",
            "BRANDPILOT_APP_SECRET_KEY": "a" * 32,
            "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(
                b"b" * 32
            ).decode("ascii"),
            "BRANDPILOT_OWNER_SETUP_TOKEN": "setup-token-with-20-characters",
            "BRANDPILOT_META_APP_ID": "test-app",
            "BRANDPILOT_META_APP_SECRET": "test-secret",
            "BRANDPILOT_META_GRAPH_VERSION": "v23.0",
            "BRANDPILOT_META_CALLBACK_URL": "https://test.example/api/v1/social/meta/callback",
            "BRANDPILOT_SESSION_COOKIE_SECURE": "false",
        }
        with self.assertRaisesRegex(ConfigurationError, "SESSION_COOKIE_SECURE=true"):
            AppSettings.from_env(values)
        values["BRANDPILOT_SESSION_COOKIE_SECURE"] = "true"
        self.assertTrue(AppSettings.from_env(values).session_cookie_secure)

    def test_valid_offline_configuration(self):
        with tempfile.TemporaryDirectory() as storage:
            settings = AppSettings.from_env(
                {
                    "BRANDPILOT_DATABASE_URL": "sqlite+pysqlite:///:memory:",
                    "BRANDPILOT_STORAGE_ROOT": storage,
                    "BRANDPILOT_EXECUTION_MODE": "offline_test",
                    "BRANDPILOT_MODEL_PROVIDER": "none",
                    "BRANDPILOT_APP_SECRET_KEY": "a" * 32,
                    "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(
                        b"b" * 32
                    ).decode("ascii"),
                    "BRANDPILOT_OWNER_SETUP_TOKEN": "setup-token-with-20-characters",
                }
            )
        self.assertEqual(settings.job_lease_seconds, 30)
        self.assertFalse(settings.runtime.openai_paid_enabled)

    def test_missing_database_fails_clearly(self):
        with self.assertRaisesRegex(ConfigurationError, "DATABASE_URL is required"):
            AppSettings.from_env({"BRANDPILOT_STORAGE_ROOT": ".runtime/storage"})

    def test_invalid_lease_fails_clearly(self):
        with self.assertRaisesRegex(ConfigurationError, "greater than zero"):
            AppSettings.from_env(
                {
                    "BRANDPILOT_DATABASE_URL": "sqlite+pysqlite:///:memory:",
                    "BRANDPILOT_STORAGE_ROOT": ".runtime/storage",
                    "BRANDPILOT_JOB_LEASE_SECONDS": "0",
                    "BRANDPILOT_APP_SECRET_KEY": "a" * 32,
                    "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(
                        b"b" * 32
                    ).decode("ascii"),
                    "BRANDPILOT_OWNER_SETUP_TOKEN": "setup-token-with-20-characters",
                }
            )


if __name__ == "__main__":
    unittest.main()
