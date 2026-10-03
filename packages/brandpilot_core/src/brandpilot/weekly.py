"""Durable daily measurement and Monday reporting, driven by the app worker."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select

from .accounts import AuthorizationError, Principal
from .analytics import as_utc
from .branding import require_branding
from .database import set_workspace_context
from .models import BrandingSetup, Job, SocialConnection, WorkspaceMembership, WeeklyReport, utc_now
from .phase3 import Phase3Error
from .planning import PlanningError


def owner_principal(session, workspace_id):
    member = session.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.role == "owner", WorkspaceMembership.revoked_at.is_(None)).order_by(WorkspaceMembership.id))
    return Principal(member.user_id, "", "worker") if member else None


class WeeklyScheduler:
    def __init__(self, sessions, store, workspace_id):
        self.sessions, self.store, self.workspace_id = sessions, store, workspace_id

    def tick(self, now=None):
        now = as_utc(now or utc_now())
        zone = ZoneInfo("Africa/Cairo")
        today = now.astimezone(zone).date()
        workspace = self.workspace_id
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            try:
                branding = require_branding(session, workspace)
            except Phase3Error:
                return
            owner = owner_principal(session, workspace)
            if not owner:
                return
            # Daily sync is read-only. No logo, profile or reference is collected from social media.
            connections = [c.id for c in session.scalars(select(SocialConnection).where(SocialConnection.workspace_id == workspace,
                SocialConnection.provider.in_(["meta", "facebook_pages", "instagram"]), SocialConnection.status == "connected_partial"))
                if c.capabilities.get("posts")]
            enrolled = as_utc(branding.completed_at).astimezone(zone).date()
            first_week = enrolled - timedelta(days=enrolled.weekday())
            reports = set(session.scalars(select(WeeklyReport.week_start).where(WeeklyReport.workspace_id == workspace)))
        sync_ids = [self.store.enqueue("social.meta.sync", {"connection_id": connection},
            dedupe_key=f"daily-posts:{workspace}:{connection}:{today}", available_at=now,
            workspace_id=workspace, created_by_user_id=owner.user_id) for connection in connections]
        self.store.enqueue("social.engagement", {"wait_for": sync_ids}, dedupe_key=f"daily-engagement:{workspace}:{today}",
            available_at=now, workspace_id=workspace, created_by_user_id=owner.user_id, max_attempts=48)
        week = first_week
        # Catch up after a restart; one immutable period key per completed week.
        while datetime.combine(week + timedelta(days=7), time(0, 5), zone).astimezone(timezone.utc) <= now:
            if week not in reports:
                self.store.enqueue("results.weekly", {"week_start": week.isoformat()},
                    dedupe_key=f"weekly-results:{workspace}:{week}", available_at=now,
                    workspace_id=workspace, created_by_user_id=owner.user_id, max_attempts=48)
            week += timedelta(days=7)


class WeeklyReportHandler:
    def __init__(self, sessions, store, results):
        self.sessions, self.store, self.results = sessions, store, results

    def run(self, claim):
        try:
            with self.sessions() as session, session.begin():
                set_workspace_context(session, claim.workspace_id)
                require_branding(session, claim.workspace_id)
                owner = owner_principal(session, claim.workspace_id)
                if not owner:
                    raise AuthorizationError("Workspace has no active owner.")
                pending = session.scalar(select(Job.id).where(Job.workspace_id == claim.workspace_id,
                    Job.kind.in_(["social.meta.sync", "social.engagement"]), Job.status.in_(["queued", "running", "retry_wait"])))
                if pending:
                    self.store.fail(claim.id, claim.lease_owner, "awaiting_measurements", retryable=True,
                        retry_at=utc_now() + timedelta(minutes=5))
                    return
            self.store.heartbeat(claim.id, claim.lease_owner)
            self.results.cycle(owner, claim.workspace_id, date.fromisoformat(claim.payload["week_start"]))
            self.store.complete(claim.id, claim.lease_owner)
        except (AuthorizationError, Phase3Error, PlanningError, ValueError, KeyError) as exc:
            self.store.fail(claim.id, claim.lease_owner, getattr(exc, "code", "weekly_report_unavailable"), retryable=False)
