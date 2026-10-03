from pathlib import Path
import tempfile
import unittest

from brandpilot.storage import LocalStorage, StorageConflict, StorageError


class LocalStorageTests(unittest.TestCase):
    def test_idempotent_write_does_not_duplicate_output(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(Path(directory))
            first = storage.put_bytes("jobs/1/result.json", b"same")
            second = storage.put_bytes("jobs/1/result.json", b"same")
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(len(list(Path(directory).rglob("result.json"))), 1)

    def test_conflicting_write_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(Path(directory))
            storage.put_bytes("safe.txt", b"one")
            with self.assertRaises(StorageConflict):
                storage.put_bytes("safe.txt", b"two")
            with self.assertRaises(StorageError):
                storage.put_bytes("../escape.txt", b"no")


if __name__ == "__main__":
    unittest.main()
