"""Bounded, workspace-isolated orchestration contracts for Hermes runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, AuthorizationError, Principal
from .config import ExecutionMode, ModelProvider, RuntimeConfig
from .database import set_workspace_context
from .models import AgentRun, AgentToolCall, BudgetReservation, Job, UsageLedger, Workspace, WorkspaceAsset
from .provider_policy import ModelRequest, admit_model_request
from .storage import LocalStorage


class Phase4Error(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClassifiedPrompt:
    redacted_text: str
    labels: tuple[str, ...]

    @property
    def contains_private_data(self) -> bool:
        return bool(self.labels)


_SENSITIVE_PATTERNS = (
    ("secret", re.compile(r"(?i)\b(?:api[_ -]?key|password|secret|authorization)\s*[:=]\s*\S+")),
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("phone", re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")),
)


def classify_and_redact(text: str) -> ClassifiedPrompt:
    if not isinstance(text, str) or not text.strip():
        raise Phase4Error("empty_prompt", "An agent request cannot be empty.")
    if len(text) > 20_000:
        raise Phase4Error("prompt_too_large", "An agent request is too large.")
    labels: list[str] = []
    redacted = text
    for label, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(redacted):
            labels.append(label)
            redacted = pattern.sub(f"[{label.upper()}_REDACTED]", redacted)
    return ClassifiedPrompt(redacted_text=redacted, labels=tuple(labels))


class Phase4Service:
    """Creates durable runs and accepts only the two reviewed plugin operations."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        accounts: AccountService,
        storage: LocalStorage,
        runtime: RuntimeConfig,
        *,
        gemini_model: str = "",
        openai_model: str = "",
        max_model_calls: int = 12,
        max_input_tokens: int = 24_000,
        max_output_tokens: int = 12_000,
    ) -> None:
        self._sessions = sessions
        self._accounts = accounts
        self._storage = storage
        self._runtime = runtime
        self._models = {ModelProvider.GEMINI: gemini_model, ModelProvider.OPENAI: openai_model}
        self._max_model_calls = max_model_calls
        self._max_input_tokens = max_input_tokens
        self._max_output_tokens = max_output_tokens
        self._sqlite_budget_lock = threading.Lock()

    def create_run(
        self, principal: Principal, workspace_id: str, prompt: str, dedupe_key: str,
        *, job_kind: str = "agent.hermes", checkpoint: dict | None = None,
    ) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "write")
        if job_kind not in {"agent.hermes", "creative.direction", "branding.survey", "planning.week"}:
            raise Phase4Error("invalid_job_kind", "The agent job kind is unsupported.")
        classified = classify_and_redact(prompt)
        provider = self._runtime.model_provider
        if provider is ModelProvider.NONE:
            raise Phase4Error("provider_not_configured", "Select a provider before starting an agent run.")
        model = self._models.get(provider, "").strip()
        if not model:
            raise Phase4Error("model_not_configured", "The selected provider has no configured model.")
        admitted = admit_model_request(
            self._runtime,
            ModelRequest(provider=provider, contains_private_data=classified.contains_private_data),
        )
        if not admitted.ok:
            raise Phase4Error(str(admitted.code), admitted.message)
        if not dedupe_key.strip() or len(dedupe_key) > 160:
            raise Phase4Error("invalid_dedupe_key", "The request key is invalid.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                session.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
            existing = session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == workspace_id, AgentRun.dedupe_key == dedupe_key
                )
            )
            if existing is not None:
                return self._run_payload(existing)
            job = Job(
                workspace_id=workspace_id,
                created_by_user_id=principal.user_id,
                kind=job_kind,
                payload={"agent_request": True},
                dedupe_key=f"agent:{workspace_id}:{dedupe_key}",
                max_attempts=1 if job_kind in {"creative.direction", "branding.survey", "planning.week"} else 3,
            )
            session.add(job)
            session.flush()
            run = AgentRun(
                workspace_id=workspace_id,
                job_id=job.id,
                created_by_user_id=principal.user_id,
                dedupe_key=dedupe_key,
                provider=provider.value,
                model=model,
                prompt_classification={"labels": list(classified.labels)},
                redacted_prompt=classified.redacted_text,
                checkpoint={"max_tool_calls": 20, "max_repair_cycles": 2, "network_retries": 3, **(checkpoint or {})},
            )
            session.add(run)
            session.flush()
            session.add(
                BudgetReservation(
                    workspace_id=workspace_id,
                    agent_run_id=run.id,
                    provider=provider.value,
                    max_model_calls=self._max_model_calls,
                    max_input_tokens=self._max_input_tokens,
                    max_output_tokens=self._max_output_tokens,
                )
            )
            return self._run_payload(run)

    def get_run(self, principal: Principal, workspace_id: str, run_id: str) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.id == run_id))
            if run is None:
                raise Phase4Error("run_not_found", "Agent run was not found.")
            return self._run_payload(run)

    def cancel_run(self, principal: Principal, workspace_id: str, run_id: str) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "write")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.id == run_id))
            if run is None:
                raise Phase4Error("run_not_found", "Agent run was not found.")
            if run.status not in {"completed", "failed", "cancelled"}:
                run.cancel_requested = True
                run.status = "cancelling"
                job = session.scalar(select(Job).where(Job.id == run.job_id))
                if job and job.status == "queued":
                    job.status = "cancelled"
                    run.status = "cancelled"
                    run.completed_at = datetime.now(timezone.utc)
            return self._run_payload(run)

    def admit_model_call(
        self, workspace_id: str, run_id: str, *, input_tokens: int, output_tokens: int
    ) -> None:
        if input_tokens < 0 or output_tokens < 0:
            raise Phase4Error("invalid_usage", "Usage values cannot be negative.")
        exhausted = False
        with self._sqlite_budget_lock:
            with self._sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                statement = select(BudgetReservation).where(
                    BudgetReservation.workspace_id == workspace_id,
                    BudgetReservation.agent_run_id == run_id,
                )
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    statement = statement.with_for_update()
                reservation = session.scalar(statement)
                run = session.scalar(select(AgentRun).where(AgentRun.id == run_id))
                if reservation is None or run is None or run.cancel_requested:
                    raise Phase4Error("run_not_admissible", "The agent run is not available for another model call.")
                if (
                    reservation.used_model_calls + 1 > reservation.max_model_calls
                    or reservation.used_input_tokens + input_tokens > reservation.max_input_tokens
                    or reservation.used_output_tokens + output_tokens > reservation.max_output_tokens
                ):
                    reservation.status = "exhausted"
                    exhausted = True
                else:
                    reservation.used_model_calls += 1
                    reservation.used_input_tokens += input_tokens
                    reservation.used_output_tokens += output_tokens
                    session.add(
                        UsageLedger(
                            workspace_id=workspace_id,
                            agent_run_id=run_id,
                            provider=run.provider,
                            model=run.model,
                            kind="model",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )
                    )
        if exhausted:
            raise Phase4Error("quota_exhausted", "The reserved run budget is exhausted.")

    def get_brand_context(self, workspace_id: str, job_id: str) -> dict[str, Any]:
        run = self._tool_run(workspace_id, job_id, "brand.read", {})
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            from .models import BrandProfileVersion

            profile = session.scalar(
                select(BrandProfileVersion)
                .where(BrandProfileVersion.workspace_id == workspace_id, BrandProfileVersion.status == "confirmed")
                .order_by(BrandProfileVersion.version.desc())
            )
            fields = dict(profile.fields) if profile else {}
            if self._runtime.execution_mode is ExecutionMode.GEMINI_FREE:
                classified = classify_and_redact(json.dumps(fields, ensure_ascii=False))
                if classified.contains_private_data:
                    raise Phase4Error("blocked_data_policy", "Private brand context cannot be returned to Gemini free mode.")
            from .learning import applicable_preferences

            preferences = (applicable_preferences(session, workspace_id)
                           if self._runtime.execution_mode is not ExecutionMode.GEMINI_FREE else [])
        return {"agent_run_id": run.id, "brand_profile": fields, "preferences": preferences}

    def store_artifact(self, workspace_id: str, job_id: str, title: str, content: str) -> dict[str, Any]:
        if not isinstance(title, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,119}", title):
            raise Phase4Error("invalid_artifact_title", "Artifact title is invalid.")
        if not isinstance(content, str) or not content.strip() or len(content) > 20_000:
            raise Phase4Error("invalid_artifact_content", "Artifact content is invalid.")
        run = self._tool_run(workspace_id, job_id, "artifact.write", {"title": title, "content": content})
        payload = content.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        storage_key = f"workspaces/{workspace_id}/agent-runs/{run.id}/{digest}.txt"
        self._storage.put_bytes(storage_key, payload)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            asset = session.scalar(
                select(WorkspaceAsset).where(
                    WorkspaceAsset.workspace_id == workspace_id,
                    WorkspaceAsset.storage_key == storage_key,
                )
            )
            if asset is None:
                asset = WorkspaceAsset(
                    workspace_id=workspace_id,
                    storage_key=storage_key,
                    original_name=f"{title}.txt",
                    mime_type="text/plain",
                    sha256=digest,
                    size=len(payload),
                    asset_type="agent_artifact",
                    source="hermes",
                    metadata_json={"agent_run_id": run.id},
                )
                session.add(asset)
                session.flush()
            self._record_tool_call(session, run, "artifact.write", {"title": title, "content": content}, "completed", storage_key)
            return {"asset_id": asset.id, "storage_key": storage_key, "sha256": digest}

    def _tool_run(self, workspace_id: str, job_id: str, operation: str, arguments: dict[str, Any]) -> AgentRun:
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.job_id == job_id))
            if run is None or run.cancel_requested:
                raise AuthorizationError("The run is outside its active workspace scope")
            count = session.scalar(select(func.count()).select_from(AgentToolCall).where(AgentToolCall.agent_run_id == run.id)) or 0
            if count >= 20:
                raise Phase4Error("tool_limit_exhausted", "The agent run reached its reviewed tool-call limit.")
            self._record_tool_call(session, run, operation, arguments, "started", None)
            session.expunge(run)
            return run

    @staticmethod
    def _record_tool_call(session: Session, run: AgentRun, operation: str, arguments: dict[str, Any], status: str, result_ref: str | None) -> None:
        sequence = (session.scalar(select(func.count()).select_from(AgentToolCall).where(AgentToolCall.agent_run_id == run.id)) or 0) + 1
        digest = hashlib.sha256(repr(sorted(arguments.items())).encode("utf-8")).hexdigest()
        session.add(AgentToolCall(workspace_id=run.workspace_id, agent_run_id=run.id, sequence=sequence, operation=operation, status=status, input_digest=digest, result_ref=result_ref))

    @staticmethod
    def _run_payload(run: AgentRun) -> dict[str, Any]:
        return {"id": run.id, "job_id": run.job_id, "status": run.status, "provider": run.provider, "model": run.model, "hermes_run_id": run.hermes_run_id, "cancel_requested": run.cancel_requested, "classification": run.prompt_classification, "checkpoint": run.checkpoint, "output": run.output, "last_error": run.last_error}
