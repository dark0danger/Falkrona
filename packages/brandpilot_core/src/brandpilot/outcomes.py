"""Typed outcomes shared by provider and Hermes integration boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OutcomeCode(StrEnum):
    OK = "ok"
    MISSING_KEY = "missing_key"
    UNAUTHORIZED = "unauthorized"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TOOL_ERROR = "tool_error"
    CANCELLED = "cancelled"
    MALFORMED_OUTPUT = "malformed_output"
    BLOCKED_COST_POLICY = "blocked_cost_policy"
    BLOCKED_DATA_POLICY = "blocked_data_policy"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True, slots=True)
class RunOutcome:
    code: OutcomeCode
    message: str
    run_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code is OutcomeCode.OK
