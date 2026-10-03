"""Private local storage abstraction with traversal and duplicate protection."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import uuid


class StorageError(RuntimeError):
    pass


class StorageConflict(StorageError):
    pass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    created: bool


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _target(self, key: str) -> Path:
        normalized = PurePosixPath(key)
        if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
            raise StorageError("Storage key must be a relative path without traversal")
        target = self.root.joinpath(*normalized.parts).resolve()
        if target != self.root and self.root not in target.parents:
            raise StorageError("Storage key escapes the configured root")
        return target

    def put_bytes(self, key: str, data: bytes) -> StoredObject:
        target = self._target(key)
        digest = hashlib.sha256(data).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing = target.read_bytes()
            if existing != data:
                raise StorageConflict(f"Storage key already has different content: {key}")
            return StoredObject(key, len(existing), digest, False)

        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
                created = True
            except FileExistsError:
                existing = target.read_bytes()
                if existing != data:
                    raise StorageConflict(
                        f"Storage key already has different content: {key}"
                    )
                created = False
        except OSError as exc:
            raise StorageError(f"Unable to write storage object: {key}") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return StoredObject(key, len(data), digest, created)

    def read_bytes(self, key: str) -> bytes:
        try:
            return self._target(key).read_bytes()
        except OSError as exc:
            raise StorageError(f"Unable to read storage object: {key}") from exc

    def check(self) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".health"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise StorageError("Storage root is not writable") from exc
