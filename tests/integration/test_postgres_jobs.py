from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from brandpilot.database import build_engine, build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.models import Job, JobStep, OutboxEvent
from brandpilot.storage import LocalStorage
from brandpilot.worker import ArtifactJobHandler, WorkerTerminated


DATABASE_URL = os.getenv("BRANDPILOT_TEST_DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "BRANDPILOT_TEST_DATABASE_URL is not configured")
class PostgresJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
        command.upgrade(config, "head")

    def setUp(self):
        self.engine = build_engine(DATABASE_URL)
        with build_session_factory(self.engine)() as session, session.begin():
            session.execute(delete(JobStep))
            session.execute(delete(OutboxEvent))
            session.execute(delete(Job))

    def tearDown(self):
        self.engine.dispose()

    def test_separate_workers_claim_once_and_recover_expired_lease(self):
        sessions = build_session_factory(self.engine)
        producer = JobStore(sessions, lease_seconds=2)
        started = datetime.now(timezone.utc)
        job_id = producer.enqueue(
            "fixture.artifact",
            {"source": "postgres"},
            dedupe_key="postgres-claim",
            available_at=started,
        )
        workers = [JobStore(sessions, lease_seconds=2), JobStore(sessions, lease_seconds=2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda pair: pair[0].claim_next(pair[1], now=started),
                    zip(workers, ("pg-a", "pg-b")),
                )
            )
        claimed = [claim for claim in claims if claim is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, job_id)
        recovered = producer.claim_next(
            "pg-recovery", now=started + timedelta(seconds=3)
        )
        self.assertEqual(recovered.id, job_id)
        self.assertEqual(recovered.attempts, 2)

    def test_job_and_outbox_dedupe_keys_are_idempotent(self):
        store = JobStore(build_session_factory(self.engine))
        first_job = store.enqueue("fixture.artifact", {}, dedupe_key="job-dedupe")
        second_job = store.enqueue("fixture.artifact", {}, dedupe_key="job-dedupe")
        first_event = store.add_outbox("fixture.ready", {}, dedupe_key="event-dedupe")
        second_event = store.add_outbox("fixture.ready", {}, dedupe_key="event-dedupe")
        self.assertEqual(first_job, second_job)
        self.assertEqual(first_event, second_event)

    def test_checkpoint_survives_engine_restart_without_duplicate_output(self):
        started = datetime.now(timezone.utc)
        store = JobStore(build_session_factory(self.engine), lease_seconds=2)
        job_id = store.enqueue(
            "fixture.artifact",
            {"source": "postgres-restart"},
            dedupe_key="postgres-restart",
            available_at=started,
        )
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(Path(directory))
            first = store.claim_next("pg-before-restart", now=started)
            with self.assertRaises(WorkerTerminated):
                ArtifactJobHandler(store, storage).run(
                    first, terminate_after_checkpoint=True
                )

            self.engine.dispose()
            restarted_engine = build_engine(DATABASE_URL)
            restarted_store = JobStore(
                build_session_factory(restarted_engine), lease_seconds=2
            )
            recovered = restarted_store.claim_next(
                "pg-after-restart", now=started + timedelta(seconds=3)
            )
            ArtifactJobHandler(restarted_store, storage).run(recovered)
            self.assertEqual(restarted_store.get(job_id)["status"], "completed")
            self.assertEqual(len(list(Path(directory).rglob("result.json"))), 1)
            restarted_engine.dispose()


if __name__ == "__main__":
    unittest.main()
