"""Security primitives for passwords, encrypted credentials, and scoped tool calls."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Iterable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class InvalidCredential(ValueError):
    pass


class PasswordManager:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
        self._dummy_hash = self._hasher.hash("not-a-real-password")

    def hash(self, password: str) -> str:
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        return self._hasher.hash(password)

    def verify(self, encoded: str | None, password: str) -> bool:
        candidate = encoded or self._dummy_hash
        try:
            valid = self._hasher.verify(candidate, password)
        except (VerificationError, InvalidHashError):
            valid = False
        return bool(valid and encoded)


class CredentialCipher:
    """AES-GCM envelope with explicit key version and workspace-bound AAD."""

    def __init__(self, keys: dict[int, bytes], *, current_version: int) -> None:
        if current_version not in keys or any(len(key) != 32 for key in keys.values()):
            raise ValueError("Credential encryption keys must contain 32 bytes")
        self._keys = keys
        self.current_version = current_version

    @staticmethod
    def _aad(workspace_id: str, provider: str) -> bytes:
        return f"brandpilot:{workspace_id}:{provider}".encode("utf-8")

    def encrypt(self, workspace_id: str, provider: str, plaintext: str) -> tuple[bytes, int]:
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._keys[self.current_version]).encrypt(
            nonce, plaintext.encode("utf-8"), self._aad(workspace_id, provider)
        )
        return nonce + encrypted, self.current_version

    def decrypt(
        self, workspace_id: str, provider: str, ciphertext: bytes, key_version: int
    ) -> str:
        key = self._keys.get(key_version)
        if key is None or len(ciphertext) < 29:
            raise InvalidCredential("Credential cannot be decrypted")
        try:
            plaintext = AESGCM(key).decrypt(
                ciphertext[:12], ciphertext[12:], self._aad(workspace_id, provider)
            )
        except Exception as exc:
            raise InvalidCredential("Credential cannot be decrypted") from exc
        return plaintext.decode("utf-8")


@dataclass(frozen=True, slots=True)
class RunCredential:
    workspace_id: str
    job_id: str
    operations: tuple[str, ...]
    expires_at: int
    revision: int


class RunCredentialSigner:
    """Short-lived signed credential binding plugin calls to one workspace/job."""

    def __init__(self, secret_key: bytes) -> None:
        if len(secret_key) < 32:
            raise ValueError("Run credential key must contain at least 32 bytes")
        self._key = secret_key

    def issue(
        self,
        workspace_id: str,
        job_id: str,
        operations: Iterable[str],
        *,
        expires_at: int,
        revision: int = 1,
    ) -> str:
        payload = {
            "exp": expires_at,
            "job_id": job_id,
            "nonce": secrets.token_urlsafe(12),
            "operations": sorted(set(operations)),
            "revision": revision,
            "workspace_id": workspace_id,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=")
        signature = hmac.new(self._key, encoded, hashlib.sha256).digest()
        return f"{encoded.decode('ascii')}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"

    def verify(
        self,
        token: str,
        *,
        workspace_id: str,
        job_id: str,
        operation: str,
        now: datetime | None = None,
    ) -> RunCredential:
        try:
            encoded_text, signature_text = token.split(".", 1)
            encoded = encoded_text.encode("ascii")
            signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
            expected = hmac.new(self._key, encoded, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCredential("Run credential signature is invalid")
            raw = base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
            payload = json.loads(raw)
            credential = RunCredential(
                workspace_id=str(payload["workspace_id"]),
                job_id=str(payload["job_id"]),
                operations=tuple(str(value) for value in payload["operations"]),
                expires_at=int(payload["exp"]),
                revision=int(payload["revision"]),
            )
        except InvalidCredential:
            raise
        except Exception as exc:
            raise InvalidCredential("Run credential is malformed") from exc
        timestamp = int((now or datetime.now(timezone.utc)).timestamp())
        if credential.expires_at < timestamp:
            raise InvalidCredential("Run credential has expired")
        if credential.workspace_id != workspace_id or credential.job_id != job_id:
            raise InvalidCredential("Run credential scope does not match")
        if operation not in credential.operations:
            raise InvalidCredential("Run credential operation is not allowed")
        return credential


class AssetDownloadSigner:
    """Signs a short-lived asset download for one user and workspace."""

    def __init__(self, secret_key: bytes) -> None:
        if len(secret_key) < 32:
            raise ValueError("Download signing key must contain at least 32 bytes")
        self._key = secret_key

    def issue(
        self,
        workspace_id: str,
        asset_id: str,
        user_id: str,
        *,
        expires_at: int,
    ) -> str:
        payload = {
            "asset_id": asset_id,
            "exp": expires_at,
            "user_id": user_id,
            "workspace_id": workspace_id,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).rstrip(b"=")
        signature = hmac.new(self._key, encoded, hashlib.sha256).digest()
        return f"{encoded.decode('ascii')}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"

    def verify(
        self,
        token: str,
        *,
        workspace_id: str,
        asset_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> None:
        try:
            encoded_text, signature_text = token.split(".", 1)
            encoded = encoded_text.encode("ascii")
            signature = base64.urlsafe_b64decode(
                signature_text + "=" * (-len(signature_text) % 4)
            )
            expected = hmac.new(self._key, encoded, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise InvalidCredential("Download signature is invalid")
            payload = json.loads(
                base64.urlsafe_b64decode(
                    encoded_text + "=" * (-len(encoded_text) % 4)
                )
            )
        except InvalidCredential:
            raise
        except Exception as exc:
            raise InvalidCredential("Download token is malformed") from exc
        timestamp = int((now or datetime.now(timezone.utc)).timestamp())
        if int(payload.get("exp", 0)) < timestamp:
            raise InvalidCredential("Download token has expired")
        expected_scope = (workspace_id, asset_id, user_id)
        actual_scope = (
            payload.get("workspace_id"),
            payload.get("asset_id"),
            payload.get("user_id"),
        )
        if actual_scope != expected_scope:
            raise InvalidCredential("Download token scope does not match")


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
