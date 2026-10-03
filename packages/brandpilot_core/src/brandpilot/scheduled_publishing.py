"""Atomic whole-plan approval and restartable Facebook photo publishing."""
from datetime import datetime, timedelta
import hashlib
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .accounts import AuthorizationError, Principal
from .database import set_workspace_context
from .models import (CredentialRecord, DesignVersion, Job, PublicationApproval, PublicationAttempt,
                     RenderArtifact, SocialConnection, SocialPost, WeeklyPlan, WorkspaceAsset, utc_now)
from .publication import PublicationError, _utc, cairo_instant
from .social import SocialError

CONTENT_TASKS = {"CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT",
                 "PROFILE_PLUS_MANAGE", "PROFILE_PLUS_FULL_CONTROL"}


class ScheduledPublishing:
    def __init__(self, sessions, accounts, planning, publication, social, *, enabled=False):
        self.sessions, self.accounts, self.planning = sessions, accounts, planning
        self.publication, self.social, self.enabled = publication, social, enabled

    def connection(self, session, workspace, connection_id, *, verify=False):
        if not self.enabled:
            raise PublicationError("live_publish_disabled", "Facebook publishing is unavailable in this environment.")
        connection = session.scalar(select(SocialConnection).where(
            SocialConnection.workspace_id == workspace, SocialConnection.id == connection_id))
        if (not connection or connection.provider != "meta" or not connection.account_id
            or connection.status not in {"connected", "connected_partial"}
            or "pages_manage_posts" not in connection.granted_scopes):
            raise PublicationError("publishing_permission_required", "Connect Facebook and allow publishing access first.")
        user_token = self.social._user_token(session, connection)
        if verify:
            if "pages_manage_posts" not in self.social._transport.granted_permissions(user_token):
                raise PublicationError("publishing_permission_required", "Facebook publishing access was removed. Reconnect your Page.")
            page = next((page for page in self.social._transport.managed_pages(user_token)
                         if page.get("id") == connection.account_id), None)
            if not page or not CONTENT_TASKS.intersection(page.get("tasks", [])):
                raise PublicationError("page_access_removed", "This Facebook account cannot publish to the selected Page.")
        credential = session.scalar(select(CredentialRecord).where(
            CredentialRecord.workspace_id == workspace, CredentialRecord.id == connection.account_credential_id,
            CredentialRecord.provider == "meta_page"))
        if not credential:
            raise PublicationError("connection_reauth_required", "Reconnect this Facebook Page.")
        token = self.social._cipher.decrypt(workspace, "meta_page", credential.ciphertext, credential.key_version)
        return connection, token

    def list(self, principal, workspace, plan_id):
        self.accounts.require_permission(principal, workspace, "read")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            plan = self.planning._plan(session, workspace, plan_id)
            designs = select(DesignVersion.id).where(DesignVersion.workspace_id == workspace, DesignVersion.plan_id == plan.id)
            approvals = session.scalars(select(PublicationApproval).where(
                PublicationApproval.workspace_id == workspace, PublicationApproval.delivery_mode == "live",
                PublicationApproval.design_version_id.in_(designs)).order_by(PublicationApproval.scheduled_at_utc)).all()
            attempts = {row.approval_id: row for row in session.scalars(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace,
                PublicationAttempt.approval_id.in_([row.id for row in approvals])))}
            return {"enabled": self.enabled, "posts": [self.publication._payload(row, attempts.get(row.id)) for row in approvals]}

    def ensure_lifetime(self, session, connection, through):
        if connection.token_expires_at and _utc(connection.token_expires_at) > through + timedelta(hours=1):
            return
        token = self.social._user_token(session, connection)
        extended, lifetime = self.social._transport.extend_user_token(token)
        expiry = utc_now() + timedelta(seconds=lifetime)
        if expiry <= through + timedelta(hours=1):
            raise PublicationError("authorization_too_short", "Facebook did not authorize the full schedule. Reconnect the Page or choose earlier posting times.")
        scopes = self.social._transport.granted_permissions(extended)
        page = next((page for page in self.social._transport.managed_pages(extended)
                     if page.get("id") == connection.account_id), None)
        if ("pages_manage_posts" not in scopes or not page or not page.get("access_token")
            or not CONTENT_TASKS.intersection(page.get("tasks", []))):
            raise PublicationError("publishing_permission_required", "Facebook publishing access must be renewed for this Page.")
        for record_id, provider, value in ((connection.user_credential_id, "meta_user", extended),
                                          (connection.account_credential_id, "meta_page", page["access_token"])):
            record = session.scalar(select(CredentialRecord).where(CredentialRecord.workspace_id == connection.workspace_id,
                CredentialRecord.id == record_id, CredentialRecord.provider == provider))
            if not record:
                raise PublicationError("connection_reauth_required", "Reconnect the Page to renew publishing access.")
            record.ciphertext, record.key_version = self.social._cipher.encrypt(connection.workspace_id, provider, value)
        connection.token_expires_at, connection.granted_scopes = expiry, sorted(scopes)

    def approve(self, principal, workspace, plan_id, connection_id, design_ids, facts_reviewed):
        self.accounts.require_permission(principal, workspace, "publish")
        if not facts_reviewed or not design_ids or len(design_ids) != len(set(design_ids)):
            raise PublicationError("approval_incomplete", "Review all designs, captions and posting times before approving the plan.")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            self.publication._lock_workspace(session, workspace)
            plan = self.planning._plan(session, workspace, plan_id, lock=True)
            if plan.status not in {"draft", "approved"} or not plan.items:
                raise PublicationError("plan_unapproved", "Draft and finish a plan before scheduling it.")
            latest = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace,
                WeeklyPlan.week_start == plan.week_start).order_by(WeeklyPlan.revision.desc()))
            if latest.id != plan.id:
                raise PublicationError("plan_stale", "Review the latest weekly plan before scheduling.")
            existing = session.scalars(select(PublicationApproval).where(
                PublicationApproval.workspace_id == workspace, PublicationApproval.delivery_mode == "live",
                PublicationApproval.design_version_id.in_(select(DesignVersion.id).where(
                    DesignVersion.workspace_id == workspace, DesignVersion.plan_id == plan_id)))).all()
            if existing:
                if (set(row.design_version_id for row in existing) != set(design_ids)
                    or any(row.connection_id != connection_id or row.status != "approved" for row in existing)):
                    raise PublicationError("approval_conflict", "This plan already has a different or cancelled schedule. Draft a new plan.")
                return {"scheduled": len(existing), "plan_id": plan_id}
            connection, _ = self.connection(session, workspace, connection_id, verify=True)
            if any(item["platform"] != "facebook_pages" for item in plan.items):
                raise PublicationError("unsupported_platform", "Automatic publishing is available for Facebook only. Draft a Facebook plan.")
            last_slot = max(_utc(datetime.fromisoformat(item["scheduled_at"])) for item in plan.items)
            self.ensure_lifetime(session, connection, last_slot)
            # A replacement must not silently create a second campaign for the same week.
            other = session.scalar(select(PublicationApproval.id).join(DesignVersion,
                (DesignVersion.workspace_id == PublicationApproval.workspace_id) &
                (DesignVersion.id == PublicationApproval.design_version_id)).join(WeeklyPlan,
                (WeeklyPlan.workspace_id == DesignVersion.workspace_id) & (WeeklyPlan.id == DesignVersion.plan_id)).where(
                PublicationApproval.workspace_id == workspace, PublicationApproval.status == "approved",
                PublicationApproval.delivery_mode == "live", WeeklyPlan.week_start == plan.week_start,
                WeeklyPlan.id != plan_id))
            if other:
                raise PublicationError("week_already_scheduled", "Cancel the previous week's schedule before approving its replacement.")
            designs = []
            for item in plan.items:
                design = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace,
                    DesignVersion.plan_id == plan_id, DesignVersion.item_id == item["id"]).order_by(DesignVersion.revision.desc()))
                if not design or design.id not in design_ids:
                    raise PublicationError("design_stale", "A post changed or is unfinished. Refresh and review the plan again.")
                asset_id = design.creative_direction.get("generated_asset_id")
                asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace,
                    WorkspaceAsset.id == asset_id, WorkspaceAsset.source == "external_generation", WorkspaceAsset.status == "ready"))
                slides = design.scene.get("slides", [])
                if (not asset or len(slides) != 1 or (asset.width, asset.height) != (1080, 1350)
                    or design.scene.get("preset") != "portrait" or len(design.caption) > 4000):
                    raise PublicationError("images_pending", "Finish every generated design before approving the plan.")
                layers = slides[0].get("layers", [])
                if not any(layer.get("asset_id") == asset.id for layer in layers):
                    raise PublicationError("image_changed", "The saved artwork does not match the reviewed image.")
                content = self.publication._storage.read_bytes(asset.storage_key)
                if hashlib.sha256(content).hexdigest() != asset.sha256:
                    raise PublicationError("render_corrupt", "A saved image changed. Generate it again before approval.")
                render = session.scalar(select(RenderArtifact).where(RenderArtifact.workspace_id == workspace,
                    RenderArtifact.design_version_id == design.id, RenderArtifact.slide_id == slides[0]["id"]))
                if not render:
                    session.add(RenderArtifact(workspace_id=workspace, design_version_id=design.id,
                        slide_id=slides[0]["id"], preset="portrait", storage_key=asset.storage_key,
                        sha256=asset.sha256, width=asset.width, height=asset.height))
                designs.append((item, design))
            if set(design_ids) != {design.id for _, design in designs}:
                raise PublicationError("design_mismatch", "Approve only the designs displayed in this plan.")
            if plan.status == "draft":
                self.planning.approve(principal, workspace, plan_id, _session=session)
            elif plan.status != "approved":
                raise PublicationError("plan_unapproved", "This plan cannot be scheduled.")
            session.flush()
            for item, design in designs:
                moment = _utc(datetime.fromisoformat(item["scheduled_at"]))
                local = moment.astimezone(ZoneInfo("Africa/Cairo"))
                scheduled_at, fold = cairo_instant(local.strftime("%Y-%m-%dT%H:%M"), local.fold)
                digest, snapshot = self.publication._content_snapshot(session, workspace, design.id,
                    "facebook_pages", connection.account_id, connection.id, scheduled_at)
                approval = PublicationApproval(workspace_id=workspace, design_version_id=design.id,
                    connection_id=connection.id, destination_platform="facebook_pages", destination_account_id=connection.account_id,
                    scheduled_at_utc=scheduled_at, schedule_local=local.strftime("%Y-%m-%dT%H:%M"), schedule_fold=fold,
                    timezone_name="Africa/Cairo", content_hash=digest, source_snapshot=snapshot,
                    idempotency_key=f"plan-{plan_id}-{item['id']}", delivery_mode="live", approved_by_user_id=principal.user_id)
                session.add(approval)
                session.flush()
                session.add(PublicationAttempt(workspace_id=workspace, approval_id=approval.id, status="queued"))
                session.add(Job(workspace_id=workspace, created_by_user_id=principal.user_id, kind="publication.facebook",
                    payload={"approval_id": approval.id}, dedupe_key=f"publish:{workspace}:{approval.id}",
                    available_at=scheduled_at, max_attempts=48))
            return {"scheduled": len(designs), "plan_id": plan_id}

    def cancel(self, principal, workspace, plan_id):
        self.accounts.require_permission(principal, workspace, "publish")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            self.publication._lock_workspace(session, workspace)
            self.planning._plan(session, workspace, plan_id)
            approvals = session.scalars(select(PublicationApproval).where(PublicationApproval.workspace_id == workspace,
                PublicationApproval.delivery_mode == "live", PublicationApproval.design_version_id.in_(select(DesignVersion.id).where(
                    DesignVersion.workspace_id == workspace, DesignVersion.plan_id == plan_id)))).all()
            for approval in approvals:
                attempt = session.scalar(select(PublicationAttempt).where(PublicationAttempt.workspace_id == workspace,
                    PublicationAttempt.approval_id == approval.id))
                if attempt.status in {"published", "publishing", "publish_unknown"}:
                    continue  # An in-flight or completed remote post is never represented as cancelled.
                approval.status, approval.cancelled_at = "cancelled", utc_now()
                attempt.status = "cancelled"
                job = session.scalar(select(Job).where(Job.workspace_id == workspace,
                    Job.dedupe_key == f"publish:{workspace}:{approval.id}"))
                if job and job.status != "completed":
                    job.status = "cancelled"
            return {"cancelled": True}


class FacebookPublicationHandler:
    def __init__(self, publishing, store):
        self.publishing, self.store = publishing, store

    def _rows(self, session, claim, *, validate=False):
        workspace = claim.workspace_id
        set_workspace_context(session, workspace)
        self.publishing.publication._lock_workspace(session, workspace)
        job = session.scalar(select(Job).where(Job.workspace_id == workspace, Job.id == claim.id))
        if not job or job.status != "running" or job.lease_owner != claim.lease_owner or _utc(job.lease_expires_at) <= utc_now():
            raise PublicationError("lease_lost", "The publishing job is no longer owned by this worker.")
        approval = self.publishing.publication._approval(session, workspace, claim.payload["approval_id"])
        attempt = session.scalar(select(PublicationAttempt).where(PublicationAttempt.workspace_id == workspace,
            PublicationAttempt.approval_id == approval.id))
        if not attempt or approval.delivery_mode != "live":
            raise PublicationError("live_publish_disabled", "This job has no live publication approval.")
        if validate:
            self.publishing.accounts.require_permission(Principal(approval.approved_by_user_id, "", "worker"), workspace, "publish")
            self.publishing.publication._check_approval(session, approval)
            if _utc(approval.scheduled_at_utc) > utc_now():
                raise PublicationError("not_due", "Wait until the approved posting time.")
            if utc_now() - _utc(approval.scheduled_at_utc) > timedelta(minutes=15):
                raise PublicationError("missed_schedule", "This posting time was missed. Review a new schedule.")
        job.lease_expires_at = utc_now() + timedelta(seconds=60)
        return approval, attempt

    @staticmethod
    def _record(session, approval, attempt, post_id):
        attempt.status, attempt.remote_publish_id, attempt.last_error = "published", post_id, None
        if not session.scalar(select(SocialPost.id).where(SocialPost.workspace_id == approval.workspace_id,
            SocialPost.provider == "facebook_pages", SocialPost.account_id == approval.destination_account_id,
            SocialPost.source_id == post_id)):
            session.add(SocialPost(workspace_id=approval.workspace_id, provider="facebook_pages",
                account_id=approval.destination_account_id, source_id=post_id, text=approval.source_snapshot["caption"],
                published_at=utc_now(), source_url=f"https://www.facebook.com/{post_id}", provenance="meta_api"))

    def run(self, claim):
        publishing, workspace = self.publishing, claim.workspace_id
        try:
            with publishing.sessions() as session, session.begin():
                approval, attempt = self._rows(session, claim)
                status = attempt.status
                if status in {"uploading", "publishing"}:
                    attempt.status = status = "upload_unknown" if status == "uploading" else "publish_unknown"
                if status == "published":
                    pass
                elif status == "upload_unknown":
                    raise PublicationError("upload_unknown", "The photo upload needs review; it will not be resent.")
                elif status == "publish_unknown":
                    _, token = publishing.connection(session, workspace, approval.connection_id)
                    post_id = publishing.social._transport.published_photo_story(approval.destination_account_id, token,
                        attempt.remote_upload_id, approval.source_snapshot["caption"])
                    if not post_id:
                        raise PublicationError("publish_unknown", "Facebook has not confirmed this post; it will not be resent.")
                    self._record(session, approval, attempt, post_id)
                    status = "published"
                elif status not in {"queued", "uploaded"}:
                    raise PublicationError("attempt_inactive", "This publication is stopped.")
            if status == "published":
                self.store.complete(claim.id, claim.lease_owner)
                return
            # Each write has a committed before-request state and a separate result checkpoint.
            if status == "queued":
                with publishing.sessions() as session, session.begin():
                    approval, attempt = self._rows(session, claim, validate=True)
                    publishing.connection(session, workspace, approval.connection_id, verify=True)
                    attempt.status = "uploading"
                with publishing.sessions() as session, session.begin():
                    approval, attempt = self._rows(session, claim, validate=True)
                    if attempt.status != "uploading":
                        raise PublicationError("attempt_inactive", "Upload was stopped.")
                    _, token = publishing.connection(session, workspace, approval.connection_id)
                    render = session.scalar(select(RenderArtifact).where(RenderArtifact.workspace_id == workspace,
                        RenderArtifact.design_version_id == approval.design_version_id))
                    content = publishing.publication._storage.read_bytes(render.storage_key)
                    attempt.remote_upload_id = publishing.social._transport.upload_photo(approval.destination_account_id, token, content)
                    attempt.status = "uploaded"
            with publishing.sessions() as session, session.begin():
                approval, attempt = self._rows(session, claim, validate=True)
                publishing.connection(session, workspace, approval.connection_id, verify=True)
                if attempt.status != "uploaded" or not attempt.remote_upload_id:
                    raise PublicationError("attempt_inactive", "This photo cannot be published.")
                attempt.status = "publishing"
            with publishing.sessions() as session, session.begin():
                approval, attempt = self._rows(session, claim, validate=True)
                if attempt.status != "publishing":
                    raise PublicationError("attempt_inactive", "Publishing was stopped.")
                _, token = publishing.connection(session, workspace, approval.connection_id)
                post_id = publishing.social._transport.publish_photo(approval.destination_account_id, token,
                    attempt.remote_upload_id, approval.source_snapshot["caption"])
                self._record(session, approval, attempt, post_id)
            self.store.complete(claim.id, claim.lease_owner)
        except (PublicationError, SocialError, AuthorizationError) as exc:
            self._failed(claim, getattr(exc, "code", "owner_access_removed"))
        except Exception:
            # Never put exception text (potentially containing credentials) in persisted/public errors.
            self._failed(claim, "publishing_interrupted")

    def _failed(self, claim, code):
        retryable = False
        with self.publishing.sessions() as session, session.begin():
            set_workspace_context(session, claim.workspace_id)
            self.publishing.publication._lock_workspace(session, claim.workspace_id)
            job = session.scalar(select(Job).where(Job.workspace_id == claim.workspace_id, Job.id == claim.id))
            if not job or job.status != "running" or job.lease_owner != claim.lease_owner:
                return
            attempt = session.scalar(select(PublicationAttempt).where(PublicationAttempt.workspace_id == claim.workspace_id,
                PublicationAttempt.approval_id == claim.payload["approval_id"]))
            if attempt:
                if attempt.status in {"uploading", "publishing"}:
                    attempt.status = "upload_unknown" if attempt.status == "uploading" else "publish_unknown"
                retryable = attempt.status == "publish_unknown" or (
                    attempt.status in {"queued", "uploaded"} and code in {"provider_unavailable", "rate_limited"})
                if not retryable and attempt.status not in {"upload_unknown", "cancelled", "published"}:
                    attempt.status = "needs_attention"
                attempt.last_error = code
        self.store.fail(claim.id, claim.lease_owner, code, retryable=retryable,
                        retry_at=utc_now() + timedelta(seconds=60))
