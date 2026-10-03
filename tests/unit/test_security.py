from datetime import datetime, timedelta, timezone
import unittest

from brandpilot.security import (
    CredentialCipher,
    InvalidCredential,
    PasswordManager,
    RunCredentialSigner,
)


class SecurityPrimitiveTests(unittest.TestCase):
    def test_argon2_password_hash_does_not_store_plaintext(self):
        passwords = PasswordManager()
        encoded = passwords.hash("a-long-owner-password")
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertNotIn("a-long-owner-password", encoded)
        self.assertTrue(passwords.verify(encoded, "a-long-owner-password"))
        self.assertFalse(passwords.verify(encoded, "wrong-password"))

    def test_credentials_are_encrypted_and_bound_to_workspace(self):
        cipher = CredentialCipher({1: b"k" * 32}, current_version=1)
        encrypted, version = cipher.encrypt("workspace-a", "gemini", "fixture-value")
        self.assertNotIn(b"fixture-value", encrypted)
        self.assertEqual(
            cipher.decrypt("workspace-a", "gemini", encrypted, version),
            "fixture-value",
        )
        with self.assertRaises(InvalidCredential):
            cipher.decrypt("workspace-b", "gemini", encrypted, version)

    def test_run_credential_rejects_forged_scope_and_expiry(self):
        signer = RunCredentialSigner(b"s" * 32)
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        token = signer.issue(
            "workspace-a",
            "job-a",
            ["asset.read"],
            expires_at=int((now + timedelta(minutes=1)).timestamp()),
        )
        signer.verify(
            token,
            workspace_id="workspace-a",
            job_id="job-a",
            operation="asset.read",
            now=now,
        )
        with self.assertRaises(InvalidCredential):
            signer.verify(
                token,
                workspace_id="workspace-b",
                job_id="job-a",
                operation="asset.read",
                now=now,
            )
        with self.assertRaises(InvalidCredential):
            signer.verify(
                token + "x",
                workspace_id="workspace-a",
                job_id="job-a",
                operation="asset.read",
                now=now,
            )
        with self.assertRaises(InvalidCredential):
            signer.verify(
                token,
                workspace_id="workspace-a",
                job_id="job-a",
                operation="asset.read",
                now=now + timedelta(minutes=2),
            )


if __name__ == "__main__":
    unittest.main()
