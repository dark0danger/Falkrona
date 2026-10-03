# Security Operations

## Local secrets

Generate unique values for `BRANDPILOT_APP_SECRET_KEY`,
`BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY`, and `BRANDPILOT_OWNER_SETUP_TOKEN` before
starting the application. The credential key must be URL-safe base64 encoding of
exactly 32 random bytes. Keep these values outside the repository and backups of the
database; back them up separately with restricted access.

## Credential key rotation

1. Preserve the existing key and its numeric version in the deployment secret store.
2. Add the new 32-byte key under the next version and make that version current.
3. In a workspace-scoped transaction, decrypt each credential with its recorded old
   version and re-encrypt it with the current key and the same workspace/provider AAD.
4. Verify every credential can be decrypted, take a fresh encrypted backup, then
   retire the old key only after the rollback window closes.

The current pilot configuration exposes version `1`; adding a deployment key ring and
re-encryption command is required before rotating a live credential set.

## Incident recovery

Revoke affected server sessions and memberships immediately. If credential plaintext
may have been exposed, rotate the provider credential as well as the encryption key;
re-encryption alone does not invalidate a leaked provider token. Disable a compromised
endpoint or connector until its workspace checks and adversarial tests pass again.
