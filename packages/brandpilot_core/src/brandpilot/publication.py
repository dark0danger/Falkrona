"""Exact-version owner approval and export-only publication records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import re
from zoneinfo import ZoneInfo
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .creative import CreativeService, PRESETS
from .database import set_workspace_context
from .models import (
    BrandProfileVersion, DesignVersion, OnboardingInterview, Product,
    PublicationApproval, PublicationAttempt, RenderArtifact, SocialConnection,
    WeeklyPlan, Workspace, utc_now,
)
from .planning import AVAILABLE, _offer, _text
from .storage import LocalStorage, StorageError


class PublicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


REMOTE_TRANSITIONS = {
    ("queued", "start_upload"): "uploading",
    ("uploading", "uploaded"): "uploaded",
    ("uploading", "timeout"): "upload_unknown",
    ("upload_unknown", "reconciled_uploaded"): "uploaded",
    ("upload_unknown", "reconciled_absent"): "needs_manual_review",
    ("uploaded", "start_publish"): "publishing",
    ("publishing", "published"): "published",
    ("publishing", "timeout"): "publish_unknown",
    ("publish_unknown", "reconciled_published"): "published",
    ("publish_unknown", "reconciled_absent"): "needs_manual_review",
}


def remote_transition(status: str, event: str, *, upload_id: str | None = None,
                      publish_id: str | None = None) -> str:
    next_status = REMOTE_TRANSITIONS.get((status, event))
    if next_status is None:
        raise PublicationError("invalid_attempt_transition", "Reconcile an unknown outcome; do not retry the write.")
    if event in {"uploaded", "reconciled_uploaded", "start_publish"} and not upload_id:
        raise PublicationError("upload_id_required", "Persist the remote upload ID before publishing.")
    if event in {"published", "reconciled_published"} and not publish_id:
        raise PublicationError("publish_id_required", "A verified remote post ID is required.")
    return next_status


def recover_remote_attempt(status: str) -> str:
    if status == "uploading":
        return "upload_unknown"
    if status == "publishing":
        return "publish_unknown"
    return status


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def cairo_instant(local_text: str, fold: int | None, *, now: datetime | None = None) -> tuple[datetime, int]:
    try:
        local = datetime.fromisoformat(local_text)
    except ValueError as exc:
        raise PublicationError("invalid_schedule", "Enter a Cairo date and time.") from exc
    if local.tzinfo is not None or local.second or local.microsecond:
        raise PublicationError("invalid_schedule", "Use a Cairo local time to the minute, without an offset.")
    zone = ZoneInfo("Africa/Cairo")
    valid = [candidate for candidate in (0, 1) if
             local.replace(tzinfo=zone, fold=candidate).astimezone(timezone.utc)
             .astimezone(zone).replace(tzinfo=None) == local]
    if not valid:
        raise PublicationError("nonexistent_schedule", "This Cairo time does not exist. Choose another time.")
    ambiguous = (len(valid) == 2 and
                 local.replace(tzinfo=zone, fold=0).utcoffset()
                 != local.replace(tzinfo=zone, fold=1).utcoffset())
    if ambiguous and fold is None:
        raise PublicationError("ambiguous_schedule", "Choose the first or second occurrence of this Cairo time.")
    if fold not in (None, 0, 1) or (not ambiguous and fold == 1):
        raise PublicationError("invalid_fold", "The daylight-saving choice is invalid for this time.")
    chosen = fold or 0
    instant = local.replace(tzinfo=zone, fold=chosen).astimezone(timezone.utc)
    if instant <= _utc(now or utc_now()):
        raise PublicationError("missed_schedule", "Choose a future time. Past slots are not auto-published.")
    return instant, chosen


class PublicationService:
    def __init__(self, sessions: sessionmaker[Session], accounts: AccountService,
                 creative: CreativeService, storage: LocalStorage):
        self._sessions = sessions
        self._accounts = accounts
        self._creative = creative
        self._storage = storage

    @staticmethod
    def _lock_workspace(session: Session, workspace_id: str) -> Workspace:
        query = select(Workspace).where(Workspace.id == workspace_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise PublicationError("workspace_not_found", "Workspace is unavailable.")
        return row

    @staticmethod
    def _approval(session: Session, workspace_id: str, approval_id: str) -> PublicationApproval:
        row = session.scalar(select(PublicationApproval).where(
            PublicationApproval.workspace_id == workspace_id, PublicationApproval.id == approval_id))
        if row is None:
            raise PublicationError("approval_not_found", "Publication approval is unavailable.")
        return row

    @staticmethod
    def _payload(row: PublicationApproval, attempt: PublicationAttempt | None = None) -> dict:
        return {"id": row.id, "design_version_id": row.design_version_id,
                "destination_platform": row.destination_platform,
                "destination_account_id": row.destination_account_id,
                "connection_id": row.connection_id,
                "scheduled_at_utc": _utc(row.scheduled_at_utc).isoformat(),
                "schedule_local": row.schedule_local, "schedule_fold": row.schedule_fold,
                "timezone_name": row.timezone_name, "content_hash": row.content_hash,
                "delivery_mode": row.delivery_mode, "status": row.status,
                "approved_by_user_id": row.approved_by_user_id,
                "approved_at": row.approved_at.isoformat(),
                "attempt": {"id": attempt.id, "status": attempt.status,
                            "exported_at": attempt.exported_at.isoformat() if attempt.exported_at else None,
                            "remote_upload_id": attempt.remote_upload_id,
                            "remote_publish_id": attempt.remote_publish_id,
                            "last_error": attempt.last_error} if attempt else None}

    def _content_snapshot(self, session: Session, workspace_id: str, design_id: str,
                          platform: str, account_id: str, connection_id: str | None,
                          scheduled_at: datetime) -> tuple[str, dict]:
        design = session.scalar(select(DesignVersion).where(
            DesignVersion.workspace_id == workspace_id, DesignVersion.id == design_id))
        if design is None:
            raise PublicationError("design_not_found", "Design revision is unavailable.")
        plan = session.scalar(select(WeeklyPlan).where(
            WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == design.plan_id))
        if plan is None or plan.status != "approved":
            raise PublicationError("plan_unapproved", "Approve the source calendar before this design.")
        newer_approved = session.scalar(select(WeeklyPlan).where(
            WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.week_start == plan.week_start,
            WeeklyPlan.revision > plan.revision, WeeklyPlan.status == "approved"))
        if newer_approved:
            raise PublicationError("plan_stale", "A newer calendar was approved. Create a design from it.")
        item = next((entry for entry in plan.items if entry.get("id") == design.item_id), None)
        if not item or item.get("status") != "approved" or item.get("conflicts"):
            raise PublicationError("brief_unapproved", "The source brief is not approved.")
        if platform != item.get("platform"):
            raise PublicationError("destination_mismatch", "Destination must match the approved brief.")
        latest = session.scalar(select(DesignVersion).where(
            DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == design.plan_id,
            DesignVersion.item_id == design.item_id).order_by(DesignVersion.revision.desc()))
        if latest.id != design.id:
            raise PublicationError("design_stale", "A newer design revision needs its own approval.")
        if design.factual_refs != item.get("factual_refs"):
            raise PublicationError("facts_stale", "Design references no longer match the approved brief.")
        workspace = session.get(Workspace, workspace_id)
        if workspace is None or workspace.timezone != "Africa/Cairo":
            raise PublicationError("timezone_changed", "Confirm the workspace Cairo timezone before approving.")
        profile = session.scalar(select(BrandProfileVersion).where(
            BrandProfileVersion.workspace_id == workspace_id,
            BrandProfileVersion.status == "confirmed").order_by(BrandProfileVersion.version.desc()))
        if profile is None or profile.version != plan.profile_version:
            raise PublicationError("facts_stale", "The confirmed profile changed. Replan and review the design.")
        interview = session.scalar(select(OnboardingInterview).where(
            OnboardingInterview.workspace_id == workspace_id).order_by(OnboardingInterview.created_at.desc()))
        answers = interview.confirmed_answers or {} if interview else {}
        products = {row.id: row for row in session.scalars(select(Product).where(Product.workspace_id == workspace_id))}
        local_date = _utc(scheduled_at).astimezone(ZoneInfo("Africa/Cairo")).date()
        if not plan.week_start <= local_date < plan.week_start + timedelta(days=7):
            raise PublicationError("outside_plan_week", "Choose a time within the approved calendar week.")
        if item.get("purpose") == "offer" and not _offer(profile, answers, local_date):
            raise PublicationError("offer_expired", "The approved offer is no longer valid on the scheduled date.")
        for ref in design.factual_refs:
            kind, field, value = ref.get("kind"), ref.get("field"), ref.get("value")
            if field == "offer" and not _offer(profile, answers, local_date):
                raise PublicationError("offer_expired", "The offer is no longer confirmed or valid.")
            if kind == "profile" and (ref.get("id") != profile.id or
                                      _text(profile.fields.get(field)) != value):
                raise PublicationError("facts_stale", "A confirmed profile fact changed.")
            if kind == "onboarding" and (not interview or ref.get("id") != interview.id or
                                         _text(answers.get(field)) != value):
                raise PublicationError("facts_stale", "An onboarding fact changed.")
            if kind == "product" and (ref.get("id") not in products or
                                      products[ref["id"]].name != value or
                                      _text(products[ref["id"]].availability).lower() not in AVAILABLE):
                raise PublicationError("product_unavailable", "A referenced product changed or is unavailable.")
            if kind not in {"profile", "onboarding", "product"}:
                raise PublicationError("facts_stale", "A fact reference is invalid.")
        if connection_id:
            if platform != "facebook_pages":
                raise PublicationError("destination_mismatch", "This connection is for a Facebook Page.")
            connection = session.scalar(select(SocialConnection).where(
                SocialConnection.workspace_id == workspace_id, SocialConnection.id == connection_id))
            if (connection is None or connection.status not in {"connected", "connected_partial"}
                or not connection.account_id or connection.account_id != account_id
                or connection.provider != "meta"
                or (connection.token_expires_at and _utc(connection.token_expires_at) <= utc_now())):
                raise PublicationError("connection_reauth_required", "Reconnect and reapprove this destination.")
        artifacts = session.scalars(select(RenderArtifact).where(
            RenderArtifact.workspace_id == workspace_id,
            RenderArtifact.design_version_id == design.id)).all()
        slides = design.scene.get("slides", [])
        if len(artifacts) != len(slides) or len({row.slide_id for row in artifacts}) != len(slides):
            raise PublicationError("render_incomplete", "Render every slide of this exact revision first.")
        expected_size = PRESETS.get(design.scene.get("preset"))
        if not expected_size or {row.slide_id for row in artifacts} != {slide.get("id") for slide in slides}:
            raise PublicationError("render_incomplete", "The saved renders do not match this revision.")
        render_digests = []
        for artifact in sorted(artifacts, key=lambda row: row.slide_id):
            if (artifact.width, artifact.height) != expected_size or artifact.preset != design.scene["preset"]:
                raise PublicationError("render_stale", "A render uses the wrong dimensions or format.")
            try:
                content = self._storage.read_bytes(artifact.storage_key)
            except StorageError as exc:
                raise PublicationError("render_missing", "A saved render is unavailable.") from exc
            if hashlib.sha256(content).hexdigest() != artifact.sha256:
                raise PublicationError("render_corrupt", "A saved render changed after approval.")
            render_digests.append({"slide_id": artifact.slide_id, "sha256": artifact.sha256})
        product_snapshot = {ref["id"]: {"name": products[ref["id"]].name,
                                        "price": products[ref["id"]].price,
                                        "currency": products[ref["id"]].currency,
                                        "availability": products[ref["id"]].availability}
                            for ref in design.factual_refs if ref.get("kind") == "product"}
        snapshot = {"design_version_id": design.id, "scene": design.scene,
                    "caption": design.caption, "factual_refs": design.factual_refs,
                    "plan_id": plan.id, "plan_revision": plan.revision, "item": item,
                    "profile_id": profile.id, "profile_version": profile.version,
                    "profile_fields": profile.fields, "interview_id": interview.id if interview else None,
                    "confirmed_answers": answers, "products": product_snapshot,
                    "renders": render_digests, "destination_platform": platform,
                    "destination_account_id": account_id, "connection_id": connection_id,
                    "scheduled_at_utc": _utc(scheduled_at).isoformat(),
                    "timezone_name": workspace.timezone}
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode("utf-8")).hexdigest()
        return digest, snapshot

    def _check_approval(self, session: Session, row: PublicationApproval) -> None:
        if row.status != "approved":
            raise PublicationError("approval_inactive", "This approval was cancelled.")
        digest, _ = self._content_snapshot(session, row.workspace_id, row.design_version_id,
                                            row.destination_platform, row.destination_account_id,
                                            row.connection_id, row.scheduled_at_utc)
        if digest != row.content_hash:
            raise PublicationError("approval_stale", "Content, facts, destination, or schedule changed. Reapprove.")

    def approve(self, principal: Principal, workspace_id: str, design_id: str,
                *, platform: str, account_id: str, connection_id: str | None,
                schedule_local: str, fold: int | None, idempotency_key: str,
                facts_reviewed: bool) -> dict:
        self._accounts.require_permission(principal, workspace_id, "members")
        account_id = account_id.strip()
        if (not facts_reviewed or not re.fullmatch(r"[\w. @-]{1,160}", account_id, re.UNICODE)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,160}", idempotency_key)):
            raise PublicationError("approval_incomplete", "Confirm facts, destination, and a request key.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            existing = session.scalar(select(PublicationApproval).where(
                PublicationApproval.workspace_id == workspace_id,
                PublicationApproval.idempotency_key == idempotency_key))
            if existing:
                if (existing.design_version_id != design_id or existing.destination_platform != platform
                    or existing.destination_account_id != account_id or existing.connection_id != connection_id
                    or existing.schedule_local != schedule_local
                    or (fold is not None and existing.schedule_fold != fold)):
                    raise PublicationError("request_conflict", "This request key belongs to a different approval.")
                self._check_approval(session, existing)
                attempt = session.scalar(select(PublicationAttempt).where(
                    PublicationAttempt.workspace_id == workspace_id,
                    PublicationAttempt.approval_id == existing.id))
                return self._payload(existing, attempt)
            scheduled_at, chosen_fold = cairo_instant(schedule_local, fold)
            digest, snapshot = self._content_snapshot(session, workspace_id, design_id,
                                                      platform, account_id, connection_id, scheduled_at)
            same_target = session.scalar(select(PublicationApproval).where(
                PublicationApproval.workspace_id == workspace_id,
                PublicationApproval.design_version_id == design_id,
                PublicationApproval.destination_platform == platform,
                PublicationApproval.destination_account_id == account_id,
                PublicationApproval.scheduled_at_utc == scheduled_at))
            if same_target:
                if same_target.connection_id != connection_id:
                    raise PublicationError("destination_conflict", "This slot targets a different connection.")
                self._check_approval(session, same_target)
                attempt = session.scalar(select(PublicationAttempt).where(
                    PublicationAttempt.workspace_id == workspace_id,
                    PublicationAttempt.approval_id == same_target.id))
                return self._payload(same_target, attempt)
            row = PublicationApproval(workspace_id=workspace_id, design_version_id=design_id,
                                      connection_id=connection_id, destination_platform=platform,
                                      destination_account_id=account_id, scheduled_at_utc=scheduled_at,
                                      schedule_local=schedule_local, schedule_fold=chosen_fold,
                                      timezone_name="Africa/Cairo", content_hash=digest,
                                      source_snapshot=snapshot, idempotency_key=idempotency_key,
                                      delivery_mode="manual", status="approved",
                                      approved_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            attempt = PublicationAttempt(workspace_id=workspace_id, approval_id=row.id,
                                         status="manual_ready")
            session.add(attempt)
            session.flush()
            return self._payload(row, attempt)

    def list_for_design(self, principal: Principal, workspace_id: str, design_id: str) -> list[dict]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            rows = session.scalars(select(PublicationApproval).where(
                PublicationApproval.workspace_id == workspace_id,
                PublicationApproval.design_version_id == design_id).order_by(
                    PublicationApproval.approved_at.desc())).all()
            attempts = {row.approval_id: row for row in session.scalars(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace_id,
                PublicationAttempt.approval_id.in_([entry.id for entry in rows]))).all()} if rows else {}
            return [self._payload(row, attempts.get(row.id)) for row in rows]

    def cancel(self, principal: Principal, workspace_id: str, approval_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            row = self._approval(session, workspace_id, approval_id)
            attempt = session.scalar(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace_id,
                PublicationAttempt.approval_id == row.id))
            if row.delivery_mode == "live" and attempt and attempt.status in {"publishing", "publish_unknown", "published"}:
                raise PublicationError("cannot_cancel_sent_post", "This post was sent or may already be published. Check its outcome first.")
            if row.status == "approved":
                row.status = "cancelled"
                row.cancelled_at = utc_now()
                if attempt:
                    attempt.status = "cancelled"
            return self._payload(row, attempt)

    def manual_package(self, principal: Principal, workspace_id: str, approval_id: str) -> bytes:
        self._accounts.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            row = self._approval(session, workspace_id, approval_id)
            if row.delivery_mode == "live":
                raise PublicationError("live_export_conflict", "Download the design copy without changing its scheduled delivery.")
            self._check_approval(session, row)
            package = self._creative.package(principal, workspace_id, row.design_version_id)
            # A second check keeps a concurrent edit or revocation from promoting a stale export.
            self._check_approval(session, row)
            attempt = session.scalar(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace_id,
                PublicationAttempt.approval_id == row.id))
            if attempt is None:
                raise PublicationError("attempt_missing", "The publication record is unavailable.")
            output = BytesIO(package)
            receipt = {"approval_id": row.id, "design_version_id": row.design_version_id,
                       "content_hash": row.content_hash, "destination_platform": row.destination_platform,
                       "destination_account_id": row.destination_account_id,
                       "scheduled_at_utc": _utc(row.scheduled_at_utc).isoformat(),
                       "schedule_local": row.schedule_local, "timezone_name": row.timezone_name,
                       "schedule_fold": row.schedule_fold, "delivery_mode": "manual",
                       "published": False}
            with ZipFile(output, "a") as archive:
                archive.writestr("publication-approval.json", json.dumps(receipt, ensure_ascii=False, indent=2))
            attempt.status = "manual_exported"
            attempt.exported_at = utc_now()
            return output.getvalue()

    def checkpoint_remote(self, workspace_id: str, approval_id: str, event: str,
                          *, remote_id: str | None = None) -> str:
        """Internal contract for a future verified connector; no HTTP route calls this."""
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            approval = self._approval(session, workspace_id, approval_id)
            if approval.delivery_mode != "live":
                raise PublicationError("live_publish_disabled", "This approval is export-only.")
            attempt = session.scalar(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace_id,
                PublicationAttempt.approval_id == approval.id))
            if attempt is None:
                raise PublicationError("attempt_missing", "Publication attempt is unavailable.")
            if event in {"start_upload", "start_publish"}:
                self._check_approval(session, approval)
                connection = session.scalar(select(SocialConnection).where(
                    SocialConnection.workspace_id == workspace_id,
                    SocialConnection.id == approval.connection_id)) if approval.connection_id else None
                if connection is None or not connection.capabilities.get("publish"):
                    raise PublicationError("unsupported_capability", "The destination cannot publish from this app.")
            upload_id = remote_id if event in {"uploaded", "reconciled_uploaded"} else attempt.remote_upload_id
            publish_id = remote_id if event in {"published", "reconciled_published"} else attempt.remote_publish_id
            next_status = remote_transition(attempt.status, event,
                                            upload_id=upload_id, publish_id=publish_id)
            if remote_id and (len(remote_id) > 160 or not re.fullmatch(r"[A-Za-z0-9_:-]+", remote_id)):
                raise PublicationError("invalid_remote_id", "The remote ID is malformed.")
            attempt.status = next_status
            if event in {"uploaded", "reconciled_uploaded"}:
                attempt.remote_upload_id = remote_id
            if event in {"published", "reconciled_published"}:
                attempt.remote_publish_id = remote_id
            return next_status

    def recover_remote(self, workspace_id: str, approval_id: str) -> str:
        """Lease recovery only changes local state; it never performs a remote retry."""
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            self._lock_workspace(session, workspace_id)
            approval = self._approval(session, workspace_id, approval_id)
            if approval.delivery_mode != "live":
                raise PublicationError("live_publish_disabled", "This approval is export-only.")
            attempt = session.scalar(select(PublicationAttempt).where(
                PublicationAttempt.workspace_id == workspace_id,
                PublicationAttempt.approval_id == approval.id))
            if attempt is None:
                raise PublicationError("attempt_missing", "Publication attempt is unavailable.")
            attempt.status = recover_remote_attempt(attempt.status)
            return attempt.status
