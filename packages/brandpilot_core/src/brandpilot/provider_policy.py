"""Admission policy applied before any external model transport."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ExecutionMode, ModelProvider, RuntimeConfig
from .outcomes import OutcomeCode, RunOutcome


@dataclass(frozen=True, slots=True)
class ModelRequest:
    provider: ModelProvider
    contains_private_data: bool = False
    image_generation: bool = False


def admit_model_request(config: RuntimeConfig, request: ModelRequest) -> RunOutcome:
    if config.execution_mode is ExecutionMode.OFFLINE_TEST:
        return RunOutcome(
            OutcomeCode.BLOCKED_COST_POLICY,
            "External model transport is disabled in offline_test.",
        )

    if request.provider is not config.model_provider:
        return RunOutcome(
            OutcomeCode.BLOCKED_COST_POLICY,
            "The requested provider is not the explicitly selected provider.",
        )

    if config.execution_mode is ExecutionMode.GEMINI_FREE and request.contains_private_data:
        return RunOutcome(
            OutcomeCode.BLOCKED_DATA_POLICY,
            "Private or confidential data cannot be sent in gemini_free mode.",
        )

    if request.image_generation and not config.image_api_enabled:
        return RunOutcome(
            OutcomeCode.BLOCKED_COST_POLICY,
            "Image API calls are disabled.",
        )

    return RunOutcome(OutcomeCode.OK, "Request admitted.")
