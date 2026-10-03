import unittest

from brandpilot.publication import PublicationError, recover_remote_attempt, remote_transition


class PublicationRecoveryTests(unittest.TestCase):
    def test_remote_success_lost_response_requires_reconciliation(self):
        status = remote_transition("queued", "start_upload")
        status = remote_transition(status, "uploaded", upload_id="media-123")
        status = remote_transition(status, "start_publish", upload_id="media-123")
        status = remote_transition(status, "timeout", upload_id="media-123")
        self.assertEqual(status, "publish_unknown")
        with self.assertRaises(PublicationError):
            remote_transition(status, "start_publish", upload_id="media-123")
        self.assertEqual(remote_transition(status, "reconciled_published", publish_id="post-456"),
                         "published")

    def test_four_crash_points_do_not_blindly_retry(self):
        cases = [
            ("queued", "queued"),               # before any remote request
            ("uploading", "upload_unknown"),    # upload may have completed
            ("uploaded", "uploaded"),           # checkpointed container, before publish
            ("publishing", "publish_unknown"),  # post may have completed
        ]
        for before, expected in cases:
            with self.subTest(before=before):
                self.assertEqual(recover_remote_attempt(before), expected)
        for unknown in ("upload_unknown", "publish_unknown"):
            with self.subTest(unknown=unknown):
                with self.assertRaises(PublicationError):
                    remote_transition(unknown, "start_upload")
                with self.assertRaises(PublicationError):
                    remote_transition(unknown, "start_publish", upload_id="media-123")

    def test_remote_ids_are_required_before_advancing(self):
        for status, event in (("uploading", "uploaded"), ("uploaded", "start_publish"),
                              ("publishing", "published")):
            with self.subTest(event=event):
                with self.assertRaises(PublicationError):
                    remote_transition(status, event)
        self.assertEqual(remote_transition("publish_unknown", "reconciled_absent"),
                         "needs_manual_review")
