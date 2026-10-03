"""Fail-closed runtime configuration for provider and cost controls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
from typing import Mapping


class ExecutionMode(StrEnum):
    OFFLINE_TEST = "offline_test"
    GEMINI_FREE = "gemini_free"
    PAID_OPT_IN = "paid_opt_in"


class ModelProvider(StrEnum):
    NONE = "none"
    GEMINI = "gemini"
    OPENAI = "openai"


def _env_bool(
    name: str,
    default: bool = False,
    environ: Mapping[str, str] | None = None,
) -> bool:
    values = os.environ if environ is None else environ
    value = values.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    execution_mode: ExecutionMode = ExecutionMode.OFFLINE_TEST
    model_provider: ModelProvider = ModelProvider.NONE
    openai_paid_enabled: bool = False
    image_api_enabled: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RuntimeConfig":
        values = os.environ if environ is None else environ
        config = cls(
            execution_mode=ExecutionMode(
                values.get("BRANDPILOT_EXECUTION_MODE", ExecutionMode.OFFLINE_TEST)
            ),
            model_provider=ModelProvider(
                values.get("BRANDPILOT_MODEL_PROVIDER", ModelProvider.NONE)
            ),
            openai_paid_enabled=_env_bool(
                "BRANDPILOT_OPENAI_PAID_ENABLED", environ=values
            ),
            image_api_enabled=_env_bool(
                "BRANDPILOT_IMAGE_API_ENABLED", environ=values
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.execution_mode is ExecutionMode.OFFLINE_TEST:
            if self.model_provider is not ModelProvider.NONE:
                raise ValueError("offline_test cannot select an external model provider")
            if self.openai_paid_enabled or self.image_api_enabled:
                raise ValueError("offline_test cannot enable paid or image API calls")
            return

        if self.execution_mode is ExecutionMode.GEMINI_FREE:
            if self.model_provider is not ModelProvider.GEMINI:
                raise ValueError("gemini_free requires the Gemini provider")
            if self.openai_paid_enabled or self.image_api_enabled:
                raise ValueError("gemini_free cannot enable paid OpenAI or image calls")
            return

        if self.model_provider is ModelProvider.NONE:
            raise ValueError("paid_opt_in requires an explicitly selected provider")
        if self.model_provider is ModelProvider.OPENAI and not self.openai_paid_enabled:
            raise ValueError("OpenAI requires BRANDPILOT_OPENAI_PAID_ENABLED=true")
