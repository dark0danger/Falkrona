"""Dated per-post cumulative counts. Missing permissions never become zeroes."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select

from .analytics import as_utc
from .database import set_workspace_context
from .models import CredentialRecord, EngagementSnapshot, Job, SocialConnection, SocialPost, utc_now
from .social import SocialError

COUNTS = ("reactions", "comments", "shares", "saves")


def save_snapshot(session, workspace_id, post_id, counts, source, status="observed", now=None):
    now = as_utc(now or utc_now())
    if any(key not in COUNTS or (value is not None and (type(value) is not int or value < 0)) for key, value in counts.items()):
        raise SocialError("invalid_engagement", "Engagement counts must be whole numbers, or unavailable.")
    day = now.astimezone(ZoneInfo("Africa/Cairo")).date()
    row = session.scalar(select(EngagementSnapshot).where(EngagementSnapshot.workspace_id == workspace_id,
        EngagementSnapshot.post_id == post_id, EngagementSnapshot.day == day, EngagementSnapshot.source == source))
    if not row:
        row = EngagementSnapshot(workspace_id=workspace_id, post_id=post_id, day=day, source=source)
        session.add(row)
    row.counts, row.status, row.observed_at = {key: counts.get(key) for key in COUNTS}, status, now


def post_engagement(session, workspace_id, posts, now):
    snapshots = session.scalars(select(EngagementSnapshot).where(EngagementSnapshot.workspace_id == workspace_id,
        EngagementSnapshot.post_id.in_([p.id for p in posts]), EngagementSnapshot.observed_at <= now)
        .order_by(EngagementSnapshot.observed_at.desc(), EngagementSnapshot.id)).all()
    result = []
    for post in posts:
        rows = [row for row in snapshots if row.post_id == post.id]
        latest = rows[0] if rows else None
        counts, sources = {}, {}
        for key in COUNTS:
            observed = next((row for row in rows if row.counts.get(key) is not None), None)
            counts[key] = observed.counts[key] if observed else None
            sources[key] = {"source": observed.source, "observed_at": as_utc(observed.observed_at).isoformat()} if observed else None
        result.append({"post_id": post.id, "text": post.text[:200], "provider": post.provider,
            "published_at": as_utc(post.published_at).isoformat() if post.published_at else None,
            "counts": counts, "sources": sources,
            "status": latest.status if latest else "unavailable",
            "basis": "Cumulative engagement since publication, as of each measurement date; not engagement earned only during this week."})
    return result


class EngagementHandler:
    def __init__(self, sessions, store, cipher, transport, *, offline=False, injected=False):
        self.sessions, self.store, self.cipher, self.transport = sessions, store, cipher, transport
        self.offline, self.injected = offline, injected

    def run(self, claim):
        workspace = claim.workspace_id
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            pending = session.scalar(select(Job.id).where(Job.workspace_id == workspace,
                Job.id.in_(claim.payload.get("wait_for", [])), Job.status.in_(["queued", "running"])))
        if pending:
            self.store.fail(claim.id, claim.lease_owner, "awaiting_post_sync", retryable=True,
                retry_at=utc_now() + timedelta(minutes=5))
            return
        after = claim.checkpoint.get("after", claim.payload.get("after", ""))
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            posts = [(p.id, p.provider, p.account_id, p.source_id) for p in session.scalars(select(SocialPost).where(
                SocialPost.workspace_id == workspace, SocialPost.provider.in_(["facebook_pages", "instagram"]),
                SocialPost.published_at.is_not(None), SocialPost.published_at <= utc_now(), SocialPost.id > after)
                .order_by(SocialPost.id).limit(201))]
        for post_id, provider, account, source_id in posts[:200]:
            self.store.heartbeat(claim.id, claim.lease_owner)
            counts, status = {}, "unavailable"
            try:
                with self.sessions() as session, session.begin():
                    set_workspace_context(session, workspace)
                    connection = session.scalar(select(SocialConnection).where(SocialConnection.workspace_id == workspace,
                        SocialConnection.provider.in_(["meta", "facebook_pages"] if provider == "facebook_pages" else ["instagram"]), SocialConnection.account_id == account,
                        SocialConnection.status == "connected_partial"))
                    if self.offline and not self.injected:
                        raise SocialError("offline", "Live measurements are unavailable in offline mode.")
                    if not connection or not connection.capabilities.get("posts") or not connection.account_credential_id:
                        raise SocialError("not_connected", "Connect this account to read engagement.")
                    if connection.token_expires_at and as_utc(connection.token_expires_at) <= utc_now():
                        raise SocialError("needs_reauth", "Reconnect this account.")
                    credential_id = connection.account_credential_id
                    credential = session.scalar(select(CredentialRecord).where(CredentialRecord.workspace_id == workspace,
                        CredentialRecord.id == credential_id))
                    if not credential or credential.provider != "meta_page":
                        raise SocialError("needs_reauth", "Reconnect this account.")
                    token = self.cipher.decrypt(workspace, credential.provider, credential.ciphertext, credential.key_version)
                counts = self.transport.post_engagement(provider, source_id, token)
                status = "observed" if all(counts.get(k) is not None for k in COUNTS[:2]) else "partial"
                # Recheck access after transport; disconnecting during a call revokes writes too.
                with self.sessions() as session, session.begin():
                    set_workspace_context(session, workspace)
                    current = session.scalar(select(SocialConnection).where(SocialConnection.workspace_id == workspace,
                        SocialConnection.provider.in_(["meta", "facebook_pages"] if provider == "facebook_pages" else ["instagram"]), SocialConnection.account_id == account,
                        SocialConnection.account_credential_id == credential_id, SocialConnection.status == "connected_partial").with_for_update())
                    if not current or not current.capabilities.get("posts"):
                        raise SocialError("not_connected", "Account was disconnected.")
                    save_snapshot(session, workspace, post_id, counts, "meta_api", status)
                    current.capabilities = {**current.capabilities, "post_metrics": any(v is not None for v in counts.values())}
            except SocialError as exc:
                status = exc.code
                # Store availability separately, preserving earlier valid counts and dates.
                with self.sessions() as session, session.begin():
                    set_workspace_context(session, workspace)
                    save_snapshot(session, workspace, post_id, {}, "collection_status", status)
                if status in {"rate_limited", "provider_unavailable"}:
                    self.store.fail(claim.id, claim.lease_owner, status, retryable=True,
                        retry_at=utc_now() + timedelta(minutes=5))
                    return
            self.store.checkpoint(claim.id, claim.lease_owner, {"after": post_id})
        if len(posts) > 200:
            self.store.enqueue("social.engagement", {"after": posts[199][0]},
                dedupe_key=f"engagement:{workspace}:{utc_now().date()}:{posts[199][0]}", workspace_id=workspace)
        self.store.complete(claim.id, claim.lease_owner)
