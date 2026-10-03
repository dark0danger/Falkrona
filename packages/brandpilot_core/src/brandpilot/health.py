"""Health aggregation with component-level failure details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .storage import LocalStorage


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: str
    components: dict[str, dict[str, str]]

    @property
    def healthy(self) -> bool:
        return self.status == "ready"


class HealthService:
    def __init__(
        self,
        database_probe: Callable[[], None],
        storage_probe: Callable[[], None],
    ) -> None:
        self._database_probe = database_probe
        self._storage_probe = storage_probe

    @classmethod
    def from_resources(cls, engine: Engine, storage: LocalStorage) -> "HealthService":
        def database_probe() -> None:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

        return cls(database_probe, storage.check)

    def ready(self) -> HealthReport:
        components: dict[str, dict[str, str]] = {}
        for name, probe in (
            ("database", self._database_probe),
            ("storage", self._storage_probe),
        ):
            try:
                probe()
                components[name] = {"status": "ok"}
            except Exception as exc:
                components[name] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
        status = (
            "ready"
            if all(item["status"] == "ok" for item in components.values())
            else "degraded"
        )
        return HealthReport(status, components)
