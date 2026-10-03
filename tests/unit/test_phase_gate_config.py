import os
import unittest
from unittest.mock import patch

from sqlalchemy.engine import make_url

from scripts.phase_gate import postgres_test_url


class PhaseGateDatabaseTests(unittest.TestCase):
    def test_default_uses_dedicated_database(self):
        with patch.dict(os.environ, {
            "BRANDPILOT_DATABASE_URL": "postgresql+psycopg://user:secret@127.0.0.1:5432/live",
        }, clear=True):
            self.assertEqual(make_url(postgres_test_url()).database, "live_phase_gate")

    def test_refuses_live_or_remote_database(self):
        application = "postgresql+psycopg://user:secret@127.0.0.1:5432/live"
        for candidate in (
            application,
            "postgresql+psycopg://user:secret@remote.example:5432/live_phase_gate",
            "postgresql+psycopg://other:secret@127.0.0.1:5432/live_phase_gate",
        ):
            with self.subTest(candidate=make_url(candidate).database):
                with patch.dict(os.environ, {
                    "BRANDPILOT_DATABASE_URL": application,
                    "BRANDPILOT_TEST_DATABASE_URL": candidate,
                }, clear=True):
                    with self.assertRaises(ValueError):
                        postgres_test_url()

        with patch.dict(os.environ, {
            "BRANDPILOT_DATABASE_URL": "postgresql+psycopg://user:secret@127.0.0.1:5432/live_phase_gate",
            "BRANDPILOT_TEST_DATABASE_URL": "postgresql+psycopg://user:secret@127.0.0.1:5432/live_phase_gate",
        }, clear=True):
            with self.assertRaises(ValueError):
                postgres_test_url()


if __name__ == "__main__":
    unittest.main()
