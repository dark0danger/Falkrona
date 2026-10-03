"""Repeatable weekly owner cycles with dated evidence and editable next plans."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .analytics import as_utc, build_audit
from .database import set_workspace_context
from .engagement import post_engagement
from .learning import applicable_preferences
from .models import (AuditComment, MetricObservation, PublicationApproval, PublicationAttempt, SocialPost,
                     WeeklyPlan, WeeklyReport, Workspace, utc_now)
from .planning import PlanningError
from .publication import PublicationError


class ResultsService:
    def __init__(self, sessions, accounts, planning, publication):
        self.sessions, self.accounts = sessions, accounts
        self.planning, self.publication = planning, publication

    @staticmethod
    def payload(row):
        return {"id": row.id, "week_start": row.week_start.isoformat(), "revision": row.revision,
                "report": row.report, "next_plan_id": row.next_plan_id,
                "updated_at": row.updated_at.isoformat()}

    def list(self, principal, workspace_id):
        self.accounts.require_permission(principal, workspace_id, "read")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            return [self.payload(row) for row in session.scalars(select(WeeklyReport).where(
                WeeklyReport.workspace_id == workspace_id).order_by(WeeklyReport.week_start.desc()))]

    def cycle(self, principal, workspace_id, week_start: date, *, refresh=False, now=None):
        self.accounts.require_permission(principal, workspace_id, "write")
        now = as_utc(now or utc_now())
        zone = ZoneInfo("Africa/Cairo")
        end_date = week_start + timedelta(days=7)
        if week_start.weekday() != 0 or end_date > now.astimezone(zone).date():
            raise PlanningError("invalid_week", "Choose a completed week starting on Monday in Cairo.")
        start = datetime.combine(week_start, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(end_date, time.min, zone).astimezone(timezone.utc)
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            query = select(Workspace).where(Workspace.id == workspace_id)
            if session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            if session.scalar(query) is None:
                raise PlanningError("workspace_not_found", "Workspace is unavailable.")
            row = session.scalar(select(WeeklyReport).where(WeeklyReport.workspace_id == workspace_id,
                                                           WeeklyReport.week_start == week_start))
            if row is None or refresh:
                # Only dated, actually imported/synced posts count. Designs/exports never count as results.
                posts = session.scalars(select(SocialPost).where(SocialPost.workspace_id == workspace_id,
                    SocialPost.provider.in_(["facebook_pages", "instagram"]), SocialPost.published_at >= start,
                    SocialPost.published_at < end, SocialPost.observed_at <= now)).all()
                ids = [post.id for post in posts]
                metrics = session.scalars(select(MetricObservation).where(
                    MetricObservation.workspace_id == workspace_id, MetricObservation.post_id.in_(ids),
                    MetricObservation.window_start == start, MetricObservation.window_end == end,
                    MetricObservation.observed_at <= now, MetricObservation.invalidated_at.is_(None))).all()
                comments = session.scalars(select(AuditComment).where(AuditComment.workspace_id == workspace_id,
                    AuditComment.post_id.in_(ids), AuditComment.observed_at <= now,
                    AuditComment.invalidated_at.is_(None))).all()
                audit = build_audit(posts, metrics, comments, now)
                uncertainties = ["Results describe supplied evidence, not proven sales or causal uplift.",
                                 "Exported and unpublished drafts are excluded."]
                if len(posts) < 3 or not metrics or any(metric["status"] != "observed" for metric in audit["metrics"]):
                    uncertainties.append("Sparse or incomplete metrics: delay performance conclusions and add dated observations.")
                if any(as_utc(metric.observed_at) > end for metric in metrics):
                    uncertainties.append("Some measurements arrived after the reporting week; their observation dates are preserved.")
                reminders = []
                approvals = session.scalars(select(PublicationApproval).where(
                    PublicationApproval.workspace_id == workspace_id, PublicationApproval.status == "approved")).all()
                for approval in approvals:
                    if approval.delivery_mode == "live":
                        attempt = session.scalar(select(PublicationAttempt).where(PublicationAttempt.workspace_id == workspace_id,
                            PublicationAttempt.approval_id == approval.id))
                        if attempt and attempt.status == "published":
                            continue
                        if attempt and attempt.status in {"needs_attention", "upload_unknown", "publish_unknown"}:
                            reminders.append({"approval_id": approval.id, "status": "needs_attention",
                                "reason": attempt.last_error, "message": "Check this scheduled post. Uncertain posts are not resent."})
                        continue
                    if as_utc(approval.scheduled_at_utc) <= now:
                        reminders.append({"approval_id": approval.id, "status": "due_for_owner_review",
                            "message": "Review this past publication slot. Export is not proof of publication."})
                    else:
                        try:
                            self.publication._check_approval(session, approval)
                        except PublicationError as exc:
                            reminders.append({"approval_id": approval.id, "status": "stale", "reason": exc.code,
                                              "message": "Facts or content changed. Review and approve a current revision."})
                report = {"timezone": "Africa/Cairo", "window_start": start.isoformat(), "window_end": end.isoformat(),
                          "generated_at": now.isoformat(), "audit": audit, "uncertainties": uncertainties,
                          "engagement": post_engagement(session, workspace_id, posts, now),
                          "learning": applicable_preferences(session, workspace_id), "reminders": reminders,
                          "experiment": {"hypothesis": "A single clear question may encourage relevant replies.",
                                         "measure": "Compare owner-recorded qualified replies on similar published posts.",
                                         "status": "suggested", "automatic_conclusion": False}}
                if row is None:
                    row = WeeklyReport(workspace_id=workspace_id, week_start=week_start, revision=1,
                                       report=report, created_by_user_id=principal.user_id)
                    session.add(row)
                else:
                    row.report, row.revision, row.updated_at = report, row.revision + 1, utc_now()
                session.flush()
            row_id, next_plan_id = row.id, row.next_plan_id
            source_plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id,
                WeeklyPlan.week_start <= week_start).order_by(WeeklyPlan.week_start.desc(), WeeklyPlan.revision.desc()))
            strategy = source_plan.strategy if source_plan else {"goal": "awareness", "platforms": ["facebook_pages", "instagram"], "cadence": 2}
        if not next_plan_id:
            # Workspace lock in planning makes duplicate weekly ticks reuse the same draft/approved plan.
            plan = self.planning.generate(principal, workspace_id, week_start=end_date,
                goal=strategy.get("goal", "awareness"), platforms=strategy.get("platforms", ["instagram"]),
                cadence=strategy.get("cadence", 2), reuse_existing=True)
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                row = session.scalar(select(WeeklyReport).where(WeeklyReport.workspace_id == workspace_id,
                                                               WeeklyReport.id == row_id))
                row.next_plan_id = plan["id"]
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            return self.payload(session.scalar(select(WeeklyReport).where(
                WeeklyReport.workspace_id == workspace_id, WeeklyReport.id == row_id)))
