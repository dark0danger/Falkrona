"""Deterministic, source-linked social audit. No model or provider calls."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .database import set_workspace_context
from .models import AuditComment, MetricObservation, SocialPost, utc_now


METRICS = frozenset({"reach", "impressions", "reactions", "comments", "shares"})
TRAFFIC = frozenset({"organic", "paid", "total"})
THEMES = {
    "pricing": ("price", "cost", "expensive", "سعر", "بكام"),
    "availability": ("available", "stock", "متوفر", "موجود"),
    "delivery": ("delivery", "shipping", "توصيل", "شحن"),
    "quality": ("quality", "جودة", "خامة"),
}


class AnalyticsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def redact_comment(value: str) -> str:
    text = re.sub(r"https?://\S+|www\.\S+", "[link]", value, flags=re.IGNORECASE)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"(?<!\w)@[\w.]+", "[handle]", text)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[phone]", text)
    return text.strip()


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_audit(
    posts: list[SocialPost], observations: list[MetricObservation], comments: list[AuditComment],
    now: datetime,
) -> dict:
    post_ids = {post.id for post in posts}
    post_by_id = {post.id: post for post in posts}
    account_posts: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_provider: dict[str, list[str]] = defaultdict(list)
    for post in posts:
        by_provider[post.provider].append(post.id)
        account_posts[(post.provider, post.account_id)].add(post.id)
    post_summary = [
        {"provider": provider, "value": len(ids), "evidence_ids": sorted(ids)}
        for provider, ids in sorted(by_provider.items())
    ]

    # Repeated snapshots replace earlier observations for the same post/window/scope.
    latest: dict[tuple, MetricObservation] = {}
    for item in observations:
        if item.invalidated_at or item.post_id not in post_ids:
            continue
        key = (item.post_id, item.metric, item.traffic, item.window_start, item.window_end)
        old = latest.get(key)
        if old is None or (item.observed_at, item.id) > (old.observed_at, old.id):
            latest[key] = item
    grouped: dict[tuple, list[MetricObservation]] = defaultdict(list)
    for item in latest.values():
        post = post_by_id[item.post_id]
        if post.published_at and as_utc(post.published_at) > as_utc(item.window_end):
            continue
        grouped[(post.provider, post.account_id, item.metric, item.traffic,
                 as_utc(item.window_start), as_utc(item.window_end))].append(item)
    metrics = []
    for (provider, account_id, metric, traffic, start, end), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row.post_id)
        observed = [row for row in rows if row.status == "observed"]
        suppressed = [row for row in rows if row.status == "suppressed"]
        relevant_posts = {post_id for post_id in account_posts[(provider, account_id)]
                          if not post_by_id[post_id].published_at or as_utc(post_by_id[post_id].published_at) <= end}
        missing = len(relevant_posts) - len(rows)
        complete = bool(relevant_posts) and missing == 0 and not suppressed
        # Unique reach is not additive across posts, even with complete coverage.
        total = sum(row.value for row in observed) if complete and metric != "reach" else None
        metrics.append({
            "provider": provider, "account_id": account_id, "metric": metric, "traffic": traffic,
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "timezone": "UTC", "value": total,
            "status": "per_post_only" if metric == "reach" else "observed" if complete else "suppressed" if suppressed else "incomplete",
            "observed_posts": len(observed), "suppressed_posts": len(suppressed),
            "missing_posts": missing, "evidence_ids": [row.id for row in rows],
            "per_post": [{"post_id": row.post_id, "value": row.value, "status": row.status, "evidence_id": row.id} for row in rows],
            "freshest_observed_at": max(as_utc(row.observed_at) for row in rows).isoformat(),
        })

    active_comments = [row for row in comments if not row.invalidated_at and row.post_id in post_ids]
    themes = []
    for theme, words in THEMES.items():
        matched = [row for row in active_comments if any(
            re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", row.redacted_text, flags=re.IGNORECASE)
            for word in words
        )]
        if matched:
            themes.append({"theme": theme, "value": len(matched), "evidence_ids": sorted(row.id for row in matched)})
    source_times = [as_utc(post.observed_at) for post in posts] + [as_utc(row.observed_at) for row in latest.values()] + [as_utc(row.observed_at) for row in active_comments]
    freshest = max(source_times) if source_times else None
    return {
        "generated_at": now.isoformat(), "timezone": "UTC",
        "source_freshness": {"last_observed_at": freshest.isoformat() if freshest else None,
                             "status": "no_source" if freshest is None else "stale" if (now - freshest).days >= 7 else "recent"},
        "posts": {"value": len(posts), "evidence_ids": sorted(post_ids), "by_provider": post_summary,
                  "status": "observed" if posts else "no_posts",
                  "items": [{"id": post.id, "provider": post.provider, "account_id": post.account_id,
                             "published_at": as_utc(post.published_at).isoformat() if post.published_at else None,
                             "age_days": max(0, (now - as_utc(post.published_at)).days) if post.published_at and as_utc(post.published_at) <= now else None,
                             "observed_at": as_utc(post.observed_at).isoformat(),
                             "provenance": post.provenance} for post in sorted(posts, key=lambda post: post.id)]},
        "metrics": metrics,
        "comments": {"value": len(active_comments), "evidence_ids": sorted(row.id for row in active_comments),
                     "status": "observed" if active_comments else "unavailable"},
        "themes": themes,
        "limitations": ["No platform metric or comment read is currently verified; observations are owner-supplied.",
                        "Missing metrics are unavailable, not zero."]
        + (["No posts yet. Import or sync Facebook/Instagram posts to start the audit."] if not posts else []),
    }


class AnalyticsService:
    def __init__(self, sessions: sessionmaker[Session], accounts: AccountService) -> None:
        self._sessions = sessions
        self._accounts = accounts

    def _post(self, session: Session, workspace_id: str, post_id: str) -> SocialPost:
        post = session.scalar(select(SocialPost).where(SocialPost.workspace_id == workspace_id, SocialPost.id == post_id))
        if post is None or post.provider not in {"facebook_pages", "instagram"}:
            raise AnalyticsError("post_not_found", "This Facebook or Instagram post is unavailable.")
        return post

    def record_metric(self, principal: Principal, workspace_id: str, *, post_id: str, metric: str,
                      traffic: str, status: str, value: int | None, window_start: datetime,
                      window_end: datetime, source_ref: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        if metric not in METRICS or traffic not in TRAFFIC or status not in {"observed", "suppressed"}:
            raise AnalyticsError("invalid_observation", "Unsupported metric, traffic, or status.")
        if (status == "observed" and (value is None or value < 0)) or (status == "suppressed" and value is not None):
            raise AnalyticsError("invalid_observation", "Observed metrics need a nonnegative value; suppressed metrics need none.")
        if (window_start.utcoffset() is None or window_end.utcoffset() is None
            or window_start >= window_end or window_end > utc_now()):
            raise AnalyticsError("invalid_window", "Use a completed, timezone-aware reporting window.")
        if not source_ref.strip():
            raise AnalyticsError("invalid_source", "A source reference is required.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            post = self._post(session, workspace_id, post_id)
            if post.published_at and as_utc(post.published_at) > as_utc(window_end):
                raise AnalyticsError("invalid_window", "The reporting window ends before the post was published.")
            row = MetricObservation(
                workspace_id=workspace_id, post_id=post_id, metric=metric, traffic=traffic,
                status=status, value=value, window_start=window_start.astimezone(timezone.utc),
                window_end=window_end.astimezone(timezone.utc), source_ref=source_ref.strip(),
            )
            session.add(row)
            session.flush()
            return {"id": row.id, "status": row.status}

    def record_comment(self, principal: Principal, workspace_id: str, *, post_id: str,
                       source_ref: str, text: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        redacted = redact_comment(text)
        if not redacted or not source_ref.strip():
            raise AnalyticsError("invalid_comment", "Comment text and a source reference are required.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._post(session, workspace_id, post_id)
            existing = session.scalar(select(AuditComment).where(
                AuditComment.workspace_id == workspace_id, AuditComment.source_ref == source_ref.strip()))
            if existing:
                return {"id": existing.id, "status": "already_recorded"}
            row = AuditComment(workspace_id=workspace_id, post_id=post_id,
                               redacted_text=redacted, source_ref=source_ref.strip())
            session.add(row)
            session.flush()
            return {"id": row.id, "status": "recorded"}

    def invalidate(self, principal: Principal, workspace_id: str, kind: str, evidence_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        model = {"metric": MetricObservation, "comment": AuditComment}.get(kind)
        if model is None:
            raise AnalyticsError("invalid_evidence", "Unknown evidence kind.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = session.scalar(select(model).where(model.workspace_id == workspace_id, model.id == evidence_id))
            if row is None:
                raise AnalyticsError("evidence_not_found", "Evidence is unavailable.")
            if row.invalidated_at is None:
                row.invalidated_at = utc_now()
            return {"id": row.id, "status": "invalidated"}

    def audit(self, principal: Principal, workspace_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            posts = session.scalars(select(SocialPost).where(
                SocialPost.workspace_id == workspace_id,
                SocialPost.provider.in_(("facebook_pages", "instagram")))).all()
            observations = session.scalars(select(MetricObservation).where(MetricObservation.workspace_id == workspace_id)).all()
            comments = session.scalars(select(AuditComment).where(AuditComment.workspace_id == workspace_id)).all()
            return build_audit(posts, observations, comments, utc_now())

    def evidence(self, principal: Principal, workspace_id: str, evidence_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            for kind, model in (("post", SocialPost), ("metric", MetricObservation), ("comment", AuditComment)):
                row = session.scalar(select(model).where(model.workspace_id == workspace_id, model.id == evidence_id))
                if row is not None:
                    result = {"id": row.id, "kind": kind, "post_id": row.post_id if kind != "post" else row.id,
                              "observed_at": row.observed_at.isoformat()}
                    if kind == "post":
                        result.update(provider=row.provider, source_id=row.source_id, provenance=row.provenance,
                                      published_at=row.published_at.isoformat() if row.published_at else None)
                    elif kind == "metric":
                        result.update(metric=row.metric, traffic=row.traffic, status=row.status, value=row.value,
                                      window_start=row.window_start.isoformat(), window_end=row.window_end.isoformat(),
                                      source_ref=row.source_ref, invalidated=row.invalidated_at is not None)
                    else:
                        result.update(source_ref=row.source_ref, redacted_text=row.redacted_text,
                                      invalidated=row.invalidated_at is not None)
                    return result
        raise AnalyticsError("evidence_not_found", "Evidence is unavailable.")
