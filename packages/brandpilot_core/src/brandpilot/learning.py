"""Owner-reviewed, scoped preferences derived from immutable design feedback."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .database import set_workspace_context
from .models import DesignFeedback, DesignVersion, LearnedPreference, WeeklyPlan, Workspace


SCOPES = {"post", "campaign", "platform", "future"}
CATEGORIES = {"imagery", "copy", "layout", "color", "typography", "tone", "other"}
KINDS = {"preference", "fact", "hypothesis"}


class LearningError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def applicable_preferences(session: Session, workspace_id: str, *, platform: str | None = None,
                           campaign_key: str | None = None, post_key: str | None = None) -> list[dict]:
    rows = session.scalars(select(LearnedPreference).where(
        LearnedPreference.workspace_id == workspace_id,
        LearnedPreference.status == "active",
    )).all()
    match = {"future": "*", "platform": platform, "campaign": campaign_key, "post": post_key}
    selected: dict[str, dict] = {}
    for row in rows:
        if match[row.scope] != row.scope_key:
            continue
        rank = {"future": 0, "platform": 1, "campaign": 2, "post": 3}[row.scope]
        current = selected.get(row.category)
        if current is None or rank > current["rank"]:
            selected[row.category] = {"id": row.id, "scope": row.scope, "category": row.category,
                                      "instruction": row.instruction, "rank": rank}
    return [{key: value for key, value in row.items() if key != "rank"}
            for row in sorted(selected.values(), key=lambda item: item["category"])]


class LearningService:
    def __init__(self, sessions: sessionmaker[Session], accounts: AccountService):
        self._sessions = sessions
        self._accounts = accounts

    @staticmethod
    def _feedback(row: DesignFeedback) -> dict:
        return {"id": row.id, "design_version_id": row.design_version_id,
                "original_text": row.original_text, "interpretation": row.interpretation,
                "category": row.category, "kind": row.kind, "scope": row.scope,
                "scope_key": row.scope_key, "status": row.status,
                "created_at": row.created_at.isoformat()}

    @staticmethod
    def _preference(row: LearnedPreference) -> dict:
        return {"id": row.id, "feedback_id": row.feedback_id, "scope": row.scope,
                "scope_key": row.scope_key, "category": row.category,
                "instruction": row.instruction, "version": row.version,
                "status": row.status, "supersedes_id": row.supersedes_id,
                "created_at": row.created_at.isoformat()}

    @staticmethod
    def _lock_workspace(session: Session, workspace_id: str) -> None:
        query = select(Workspace).where(Workspace.id == workspace_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        if session.scalar(query) is None:
            raise LearningError("workspace_not_found", "Workspace is unavailable.")

    def submit(self, principal: Principal, workspace_id: str, design_version_id: str,
               *, original_text: str, interpretation: str, category: str, kind: str, scope: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        original_text, interpretation = original_text.strip(), interpretation.strip()
        if (not original_text or len(original_text) > 4000 or not interpretation or len(interpretation) > 1000
                or category not in CATEGORIES or kind not in KINDS or scope not in SCOPES):
            raise LearningError("invalid_feedback", "Feedback and its interpretation, type, and scope are required.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            design = session.scalar(select(DesignVersion).where(
                DesignVersion.workspace_id == workspace_id, DesignVersion.id == design_version_id))
            if design is None:
                raise LearningError("design_not_found", "Design revision is unavailable.")
            plan = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == design.plan_id))
            if plan is None:
                raise LearningError("plan_not_found", "Source plan is unavailable.")
            item = next((item for item in plan.items if item["id"] == design.item_id), None)
            if item is None:
                raise LearningError("item_not_found", "Source brief is unavailable.")
            key = {"post": design.item_id, "campaign": plan.week_start.isoformat(),
                   "platform": item["platform"], "future": "*"}[scope]
            row = DesignFeedback(workspace_id=workspace_id, design_version_id=design.id,
                                 original_text=original_text, interpretation=interpretation,
                                 category=category, kind=kind, scope=scope, scope_key=key,
                                 status="local_only" if scope == "post" else "pending",
                                 created_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            return self._feedback(row)

    def list_feedback(self, principal: Principal, workspace_id: str, design_version_id: str) -> list[dict]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            return [self._feedback(row) for row in session.scalars(select(DesignFeedback).where(
                DesignFeedback.workspace_id == workspace_id,
                DesignFeedback.design_version_id == design_version_id,
            ).order_by(DesignFeedback.created_at, DesignFeedback.id)).all()]

    def decide(self, principal: Principal, workspace_id: str, feedback_id: str,
               *, approve: bool, supersedes_id: str | None = None) -> dict:
        self._accounts.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            row = session.scalar(select(DesignFeedback).where(
                DesignFeedback.workspace_id == workspace_id, DesignFeedback.id == feedback_id))
            if row is None:
                raise LearningError("feedback_not_found", "Feedback is unavailable.")
            if row.status != "pending":
                raise LearningError("feedback_decided", "This feedback has already been handled.")
            if not approve:
                row.status = "rejected"
                return self._feedback(row)
            if row.kind != "preference":
                raise LearningError("needs_fact_or_evidence_review",
                                    "Facts belong in the confirmed profile; performance hypotheses need a sourced review.")
            versions = session.scalars(select(LearnedPreference).where(
                LearnedPreference.workspace_id == workspace_id,
                LearnedPreference.scope == row.scope,
                LearnedPreference.scope_key == row.scope_key,
                LearnedPreference.category == row.category,
            )).all()
            active = next((entry for entry in versions if entry.status == "active"), None)
            if active and supersedes_id != active.id:
                raise LearningError("preference_conflict", "Confirm the active rule being replaced.")
            if not active and supersedes_id:
                raise LearningError("stale_replacement", "The replacement target is no longer active.")
            if active:
                active.status = "superseded"
            preference = LearnedPreference(workspace_id=workspace_id, feedback_id=row.id,
                                            scope=row.scope, scope_key=row.scope_key,
                                            category=row.category, instruction=row.interpretation,
                                            version=max((entry.version for entry in versions), default=0) + 1,
                                            status="active", supersedes_id=active.id if active else None,
                                            approved_by_user_id=principal.user_id)
            session.add(preference)
            row.status = "approved"
            session.flush()
            return self._preference(preference)

    def list_preferences(self, principal: Principal, workspace_id: str) -> list[dict]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            return [self._preference(row) for row in session.scalars(select(LearnedPreference).where(
                LearnedPreference.workspace_id == workspace_id,
            ).order_by(LearnedPreference.created_at, LearnedPreference.id)).all()]

    def revert(self, principal: Principal, workspace_id: str, preference_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            row = session.scalar(select(LearnedPreference).where(
                LearnedPreference.workspace_id == workspace_id, LearnedPreference.id == preference_id))
            if row is None:
                raise LearningError("preference_not_found", "Preference is unavailable.")
            if row.status != "active":
                raise LearningError("preference_inactive", "Only an active preference can be reverted.")
            row.status = "reverted"
            return self._preference(row)
