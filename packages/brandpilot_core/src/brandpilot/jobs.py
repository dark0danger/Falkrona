"""Transactional durable job and outbox operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .models import AgentRun, Job, JobStep, OutboxEvent, Workspace
from .database import set_workspace_context


class JobStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JobClaim:
    id: str
    workspace_id: str | None
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    checkpoint: dict[str, Any]
    lease_owner: str
    lease_expires_at: datetime


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


class JobStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        lease_seconds: int = 30,
        workspace_id: str | None = None,
        allowed_kinds: tuple[str, ...] | None = None,
    ) -> None:
        self._sessions = sessions
        self._lease_seconds = lease_seconds
        self._workspace_id = workspace_id
        self._allowed_kinds = allowed_kinds
        self._sqlite_claim_lock = threading.Lock()

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str,
        max_attempts: int = 3,
        available_at: datetime | None = None,
        workspace_id: str | None = None,
        created_by_user_id: str | None = None,
    ) -> str:
        if not kind.strip() or not dedupe_key.strip():
            raise ValueError("Job kind and dedupe key are required")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be greater than zero")
        effective_workspace = workspace_id or self._workspace_id
        with self._sessions() as session:
            if effective_workspace:
                session.begin()
                set_workspace_context(session, effective_workspace)
            job = Job(
                workspace_id=effective_workspace,
                created_by_user_id=created_by_user_id,
                kind=kind,
                payload=payload,
                dedupe_key=dedupe_key,
                max_attempts=max_attempts,
                available_at=_utc(available_at),
            )
            session.add(job)
            try:
                session.commit()
                return job.id
            except IntegrityError:
                session.rollback()
                conditions = [Job.dedupe_key == dedupe_key]
                if effective_workspace:
                    session.begin()
                    set_workspace_context(session, effective_workspace)
                    conditions.append(Job.workspace_id == effective_workspace)
                existing = session.scalar(select(Job).where(*conditions))
                if existing is None:
                    raise
                return existing.id

    def claim_next(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> JobClaim | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        current = _utc(now)
        with self._sqlite_claim_lock:
            with self._sessions() as session, session.begin():
                if self._workspace_id:
                    set_workspace_context(session, self._workspace_id)
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        session.scalar(select(Workspace).where(Workspace.id == self._workspace_id).with_for_update())
                    exhausted = session.scalars(select(Job).where(Job.workspace_id == self._workspace_id,
                        Job.status == "running", Job.lease_expires_at <= current, Job.attempts >= Job.max_attempts)).all()
                    for abandoned in exhausted:
                        abandoned.status = "failed"
                        abandoned.last_error = "lease_expired_review_required"
                        abandoned.lease_owner = None
                        abandoned.lease_expires_at = None
                        run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == self._workspace_id,
                                                                   AgentRun.job_id == abandoned.id))
                        if run and run.status not in {"completed", "cancelled", "failed"}:
                            run.status, run.last_error = "failed", "lease_expired_review_required"
                    session.flush()
                eligible = and_(
                    Job.attempts < Job.max_attempts,
                    Job.available_at <= current,
                    or_(
                        Job.status == "queued",
                        and_(
                            Job.status == "running",
                            Job.lease_expires_at.is_not(None),
                            Job.lease_expires_at <= current,
                        ),
                    ),
                )
                if self._workspace_id:
                    eligible = and_(eligible, Job.workspace_id == self._workspace_id)
                    # Admit one creative model job at a time per workspace. Other work can continue.
                    active_creative = session.scalar(select(Job.id).where(
                        Job.workspace_id == self._workspace_id, Job.kind.in_(["creative.direction", "branding.survey", "planning.week"]),
                        Job.status == "running", Job.lease_expires_at > current).limit(1))
                    if active_creative:
                        eligible = and_(eligible, Job.kind.not_in(["creative.direction", "branding.survey", "planning.week"]))
                if self._allowed_kinds is not None:
                    eligible = and_(eligible, Job.kind.in_(self._allowed_kinds))
                statement = (
                    select(Job)
                    .where(eligible)
                    .order_by(Job.available_at, Job.created_at, Job.id)
                    .limit(1)
                )
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    statement = statement.with_for_update(skip_locked=True)
                job = session.scalar(statement)
                if job is None:
                    return None
                job.status = "running"
                job.lease_owner = worker_id
                job.lease_expires_at = current + timedelta(seconds=self._lease_seconds)
                job.attempts += 1
                job.updated_at = current
                session.flush()
                return JobClaim(
                    id=job.id,
                    workspace_id=job.workspace_id,
                    kind=job.kind,
                    payload=dict(job.payload),
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    checkpoint=dict(job.checkpoint or {}),
                    lease_owner=worker_id,
                    lease_expires_at=job.lease_expires_at,
                )

    def checkpoint(
        self,
        job_id: str,
        worker_id: str,
        values: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        current = _utc(now)
        with self._sessions() as session, session.begin():
            if self._workspace_id:
                set_workspace_context(session, self._workspace_id)
            job = session.get(Job, job_id)
            self._require_owner(job, worker_id)
            job.checkpoint = {**(job.checkpoint or {}), **values}
            job.updated_at = current

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> datetime:
        current = _utc(now)
        with self._sessions() as session, session.begin():
            if self._workspace_id:
                set_workspace_context(session, self._workspace_id)
            job = session.get(Job, job_id)
            self._require_owner(job, worker_id)
            job.lease_expires_at = current + timedelta(seconds=self._lease_seconds)
            job.updated_at = current
            return job.lease_expires_at

    def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        output_ref: str | None = None,
        now: datetime | None = None,
    ) -> None:
        current = _utc(now)
        with self._sessions() as session, session.begin():
            if self._workspace_id:
                set_workspace_context(session, self._workspace_id)
            job = session.get(Job, job_id)
            self._require_owner(job, worker_id)
            job.status = "completed"
            job.completed_at = current
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = current
            if output_ref:
                self._record_step(
                    session, job.workspace_id, job.id, "result", output_ref, current
                )

    def fail(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        retryable: bool,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> None:
        current = _utc(now)
        with self._sessions() as session, session.begin():
            if self._workspace_id:
                set_workspace_context(session, self._workspace_id)
            job = session.get(Job, job_id)
            self._require_owner(job, worker_id)
            can_retry = retryable and job.attempts < job.max_attempts
            job.status = "queued" if can_retry else "failed"
            job.available_at = _utc(retry_at) if retry_at else current
            job.last_error = error[:2000]
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = current

    def add_outbox(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str,
        workspace_id: str | None = None,
    ) -> str:
        effective_workspace = workspace_id or self._workspace_id
        with self._sessions() as session:
            if effective_workspace:
                session.begin()
                set_workspace_context(session, effective_workspace)
            event = OutboxEvent(
                workspace_id=effective_workspace,
                topic=topic,
                payload=payload,
                dedupe_key=dedupe_key,
            )
            session.add(event)
            try:
                session.commit()
                return event.id
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(OutboxEvent).where(OutboxEvent.dedupe_key == dedupe_key)
                )
                if existing is None:
                    raise
                return existing.id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            if self._workspace_id:
                session.begin()
                set_workspace_context(session, self._workspace_id)
            job = session.get(Job, job_id)
            if job is None or (
                self._workspace_id and job.workspace_id != self._workspace_id
            ):
                return None
            return {
                "id": job.id,
                "workspace_id": job.workspace_id,
                "kind": job.kind,
                "status": job.status,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "checkpoint": dict(job.checkpoint or {}),
                "last_error": job.last_error,
            }

    @staticmethod
    def _require_owner(job: Job | None, worker_id: str) -> None:
        if job is None:
            raise JobStateError("Job does not exist")
        if job.status != "running" or job.lease_owner != worker_id:
            raise JobStateError("Worker does not own the active job lease")

    @staticmethod
    def _record_step(
        session: Session,
        workspace_id: str | None,
        job_id: str,
        step_key: str,
        output_ref: str,
        completed_at: datetime,
    ) -> None:
        existing = session.scalar(
            select(JobStep).where(
                JobStep.job_id == job_id,
                JobStep.step_key == step_key,
            )
        )
        if existing is None:
            session.add(
                JobStep(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    step_key=step_key,
                    output_ref=output_ref,
                    completed_at=completed_at,
                )
            )
