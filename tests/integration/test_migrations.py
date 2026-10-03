from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


class MigrationTests(unittest.TestCase):
    def setUp(self):
        # These cases verify SQLite fixtures even when PostgreSQL tests are enabled.
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("BRANDPILOT_DATABASE_URL", None)
        os.environ.pop("BRANDPILOT_TEST_DATABASE_URL", None)

    def test_clean_database_migrates_to_head(self):
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite+pysqlite:///{Path(directory) / 'clean.db'}"
            command.upgrade(alembic_config(url), "head")
            engine = create_engine(url)
            tables = set(inspect(engine).get_table_names())
            engine.dispose()
            self.assertTrue(
                {
                    "jobs",
                    "job_steps",
                    "outbox_events",
                    "users",
                    "sessions",
                    "workspaces",
                    "workspace_memberships",
                    "credential_records",
                    "workspace_assets",
                    "import_jobs",
                    "products",
                    "brand_profile_versions",
                    "onboarding_interviews",
                    "onboarding_turns",
                    "agent_runs",
                    "budget_reservations",
                    "usage_ledger",
                    "agent_tool_calls",
                    "oauth_transactions",
                    "social_connections",
                    "social_posts",
                    "metric_observations",
                    "audit_comments",
                    "weekly_plans",
                    "design_versions",
                    "render_artifacts",
                }
                <= tables
            )

    def test_prior_fixture_schema_upgrades_without_data_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite+pysqlite:///{Path(directory) / 'upgrade.db'}"
            config = alembic_config(url)
            command.upgrade(config, "0001_phase0_fixture")
            engine = create_engine(url)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO phase0_fixtures (id, name, payload) "
                        "VALUES (:id, :name, :payload)"
                    ),
                    {"id": "fixture-1", "name": "Sample data", "payload": "{}"},
                )
            command.upgrade(config, "head")
            with engine.connect() as connection:
                row = connection.execute(
                    text(
                        "SELECT name, schema_version FROM phase0_fixtures WHERE id='fixture-1'"
                    )
                ).one()
            engine.dispose()
            self.assertEqual(tuple(row), ("Sample data", 1))


if __name__ == "__main__":
    unittest.main()
