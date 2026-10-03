from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from brandpilot.database import Base, build_engine, build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.storage import LocalStorage
from brandpilot.worker import ArtifactJobHandler, WorkerTerminated


class DurableJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp.name) / "jobs.db"
        self.storage_path = Path(self.temp.name) / "storage"
        self.engine = build_engine(f"sqlite+pysqlite:///{self.database_path}")
        Base.metadata.create_all(self.engine)
        self.store = JobStore(build_session_factory(self.engine), lease_seconds=5)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def test_two_workers_claim_one_job_once(self):
        job_id = self.store.enqueue(
            "fixture.artifact", {"value": 1}, dedupe_key="claim-once"
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda worker: self.store.claim_next(worker),
                    ("worker-a", "worker-b"),
                )
            )
        claimed = [claim for claim in claims if claim is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, job_id)

    def test_expired_lease_is_recovered(self):
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job_id = self.store.enqueue(
            "fixture.artifact",
            {"value": 1},
            dedupe_key="expired-lease",
            available_at=started,
        )
        first = self.store.claim_next("worker-a", now=started)
        second = self.store.claim_next("worker-b", now=started + timedelta(seconds=6))
        self.assertEqual(first.id, job_id)
        self.assertEqual(second.id, job_id)
        self.assertEqual(second.attempts, 2)

    def test_restart_after_checkpoint_does_not_duplicate_output(self):
        started = datetime.now(timezone.utc)
        job_id = self.store.enqueue(
            "fixture.artifact",
            {"value": "durable"},
            dedupe_key="restart-safe",
            available_at=started,
        )
        first = self.store.claim_next("worker-a", now=started)
        handler = ArtifactJobHandler(self.store, LocalStorage(self.storage_path))
        with self.assertRaises(WorkerTerminated):
            handler.run(first, terminate_after_checkpoint=True)

        self.engine.dispose()
        restarted_engine = build_engine(f"sqlite+pysqlite:///{self.database_path}")
        restarted_store = JobStore(
            build_session_factory(restarted_engine), lease_seconds=5
        )
        recovered = restarted_store.claim_next(
            "worker-b", now=started + timedelta(seconds=6)
        )
        ArtifactJobHandler(restarted_store, LocalStorage(self.storage_path)).run(recovered)
        self.assertEqual(restarted_store.get(job_id)["status"], "completed")
        self.assertEqual(len(list(self.storage_path.rglob("result.json"))), 1)
        restarted_engine.dispose()


if __name__ == "__main__":
    unittest.main()
