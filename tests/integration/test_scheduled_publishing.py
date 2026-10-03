"""No remote writes: exercise the real approval API, durable queue and worker with a fake Meta transport."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
from unittest.mock import patch

from PIL import Image
import pytest
from sqlalchemy import select

from brandpilot.database import build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.models import (CredentialRecord, DesignVersion, Job, PublicationApproval,
    PublicationAttempt, SocialConnection, SocialPost, User, WeeklyPlan, WorkspaceAsset, WorkspaceMembership)
from brandpilot.scheduled_publishing import FacebookPublicationHandler
from brandpilot.social import SocialError
from tests.integration import test_phase10_publication_api as fixture_module


class FakePublisher:
    def __init__(self):
        self.scopes = {"pages_manage_posts", "pages_show_list", "pages_read_engagement"}
        self.uploads, self.publishes = [], []
        self.fail_upload = self.fail_publish = False
        self.remote_created = False
        self.extended_lifetime = 60*86400

    def extend_user_token(self, token):
        assert token == "fixture-user"
        return "fixture-user", self.extended_lifetime

    def granted_permissions(self, token):
        assert token == "fixture-user"
        return self.scopes

    def managed_pages(self, token):
        assert token == "fixture-user"
        return [{"id": "12345", "tasks": ["CREATE_CONTENT"], "access_token": "fixture-page"}]

    def upload_photo(self, page, token, content):
        assert (page, token) == ("12345", "fixture-page")
        self.uploads.append(content)
        if self.fail_upload:
            raise SocialError("provider_unavailable", "Lost response")
        return "900"

    def publish_photo(self, page, token, photo, caption):
        assert (page, token, photo) == ("12345", "fixture-page", "900")
        self.publishes.append(caption)
        if self.fail_publish:
            raise SocialError("provider_unavailable", "Lost response")
        self.remote_created = True
        return "12345_901"

    def published_photo_story(self, page, token, photo, caption):
        assert (page, token, photo) == ("12345", "fixture-page", "900")
        return "12345_901" if self.remote_created else None


@pytest.fixture
def case():
    fixture = fixture_module.PublicationApiTests("test_exact_version_manual_package_dedupe_and_cancel")
    fixture.setUp()
    try:
        fixture.sessions = build_session_factory(fixture.engine)
        fixture.publisher = FakePublisher()
        fixture.app.state.social._transport = fixture.publisher
        fixture.app.state.publishing.enabled = True
        data = BytesIO()
        Image.new("RGB", (1080, 1350), "#173f36").save(data, "PNG")
        content = data.getvalue()
        key = f"workspaces/{fixture.workspace}/generated-test.png"
        fixture.app.state.storage.put_bytes(key, content)
        with fixture.sessions() as session, session.begin():
            owner = session.scalar(select(User).where(User.email == "owner@example.test"))
            cipher = fixture.app.state.social._cipher
            credentials = []
            for provider, value in (("meta_user", "fixture-user"), ("meta_page", "fixture-page")):
                ciphertext, key_version = cipher.encrypt(fixture.workspace, provider, value)
                record = CredentialRecord(workspace_id=fixture.workspace, provider=provider,
                    ciphertext=ciphertext, key_version=key_version)
                session.add(record)
                session.flush()
                credentials.append(record.id)
            connection = SocialConnection(workspace_id=fixture.workspace, provider="meta", account_id="12345",
                account_name="Test Page", authorized_by_user_id=owner.id, status="connected_partial",
                granted_scopes=sorted(fixture.publisher.scopes), capabilities={"posts": True},
                user_credential_id=credentials[0], account_credential_id=credentials[1],
                token_expires_at=datetime.now(timezone.utc)+timedelta(days=365))
            session.add(connection)
            asset = WorkspaceAsset(workspace_id=fixture.workspace, storage_key=key, original_name="Generated ad.png",
                source="external_generation", asset_type="image", mime_type="image/png", size=len(content),
                sha256=hashlib.sha256(content).hexdigest(), width=1080, height=1350)
            session.add(asset)
            session.flush()
            fixture.connection_id, fixture.asset_id = connection.id, asset.id
            design = session.get(DesignVersion, fixture.design["id"])
            design.creative_direction = {"generated_asset_id": asset.id, "renderer": "browser_image_app"}
            scene = design.scene.copy()
            scene["slides"] = [{"id": scene["slides"][0]["id"], "layers": [{"type": "image", "asset_id": asset.id}]}]
            design.scene = scene
        fixture.schedule_path = f"{fixture.base}/plans/{fixture.plan['id']}/approve-and-schedule"
        fixture.body = {"connection_id": fixture.connection_id, "design_ids": [fixture.design["id"]], "facts_reviewed": True}
        fixture.store = JobStore(fixture.sessions, workspace_id=fixture.workspace)
        fixture.handler = FacebookPublicationHandler(fixture.app.state.publishing, fixture.store)
        yield fixture
    finally:
        fixture.tearDown()


def approve(case):
    result = case.client.post(case.schedule_path, headers=case.csrf, json=case.body)
    assert result.status_code == 200, result.text
    with case.sessions() as session:
        approval = session.scalar(select(PublicationApproval))
        return approval.scheduled_at_utc.replace(tzinfo=timezone.utc)


def deliver(case, now):
    claim = case.store.claim_next("publisher-test", now=now)
    assert claim is not None
    with patch("brandpilot.scheduled_publishing.utc_now", return_value=now), patch("brandpilot.publication.utc_now", return_value=now):
        case.handler.run(claim)


def test_whole_plan_is_atomic_idempotent_and_does_not_publish_early(case):
    due = approve(case)
    assert case.client.post(case.schedule_path, headers=case.csrf, json=case.body).status_code == 200
    assert case.store.claim_next("early", now=due-timedelta(seconds=1)) is None
    with case.sessions() as session:
        assert len(session.scalars(select(Job).where(Job.kind == "publication.facebook")).all()) == 1
        assert session.get(WeeklyPlan, case.plan["id"]).status == "approved"
    assert not case.publisher.uploads and not case.publisher.publishes


def test_due_job_publishes_exact_image_and_caption_and_records_post(case):
    due = approve(case)
    deliver(case, due+timedelta(seconds=1))
    with case.sessions() as session:
        attempt = session.scalar(select(PublicationAttempt))
        assert (attempt.status, attempt.remote_upload_id, attempt.remote_publish_id) == ("published", "900", "12345_901")
        post = session.scalar(select(SocialPost).where(SocialPost.source_id == "12345_901"))
        assert post and post.text == case.design["caption"]
        assert session.scalar(select(Job).where(Job.kind == "publication.facebook")).status == "completed"
    assert len(case.publisher.uploads) == len(case.publisher.publishes) == 1
    assert case.publisher.uploads[0] == case.app.state.storage.read_bytes(f"workspaces/{case.workspace}/generated-test.png")
    assert case.store.claim_next("again", now=due+timedelta(minutes=2)) is None


@pytest.mark.parametrize("fault", ["missing_image", "wrong_revision", "past_slot", "instagram"])
def test_failed_approval_rolls_back_plan_renders_and_jobs(case, fault):
    with case.sessions() as session, session.begin():
        if fault == "missing_image":
            session.get(DesignVersion, case.design["id"]).creative_direction = {}
        elif fault == "past_slot":
            plan = session.get(WeeklyPlan, case.plan["id"])
            plan.items = [{**item, "scheduled_at": (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()} for item in plan.items]
        elif fault == "instagram":
            plan = session.get(WeeklyPlan, case.plan["id"])
            plan.items = [{**item, "platform": "instagram"} for item in plan.items]
        else:
            case.body["design_ids"] = ["wrong-or-foreign-design-id"]
    result = case.client.post(case.schedule_path, headers=case.csrf, json=case.body)
    assert result.status_code == 409, result.text
    with case.sessions() as session:
        assert session.get(WeeklyPlan, case.plan["id"]).status == "draft"
        assert not session.scalar(select(PublicationApproval.id))
        assert not session.scalar(select(Job.id).where(Job.kind == "publication.facebook"))


def test_csrf_owner_permission_and_explicit_review_required(case):
    assert case.client.post(case.schedule_path, json=case.body).status_code == 403
    assert case.client.post(case.schedule_path, headers=case.csrf, json={**case.body, "facts_reviewed": False}).status_code == 409
    with case.sessions() as session, session.begin():
        session.scalar(select(WorkspaceMembership)).role = "editor"
    assert case.client.post(case.schedule_path, headers=case.csrf, json=case.body).status_code == 403


@pytest.mark.parametrize("change", ["caption", "disconnect", "owner", "grant", "missed_time"])
def test_recheck_before_writes_stops_changed_or_unauthorized_posts(case, change):
    due = approve(case)
    with case.sessions() as session, session.begin():
        if change == "caption":
            session.get(DesignVersion, case.design["id"]).caption = "Changed after approval"
        elif change == "disconnect":
            session.get(SocialConnection, case.connection_id).status = "disconnected"
        elif change == "owner":
            session.scalar(select(WorkspaceMembership)).revoked_at = datetime.now(timezone.utc)
        elif change == "grant":
            case.publisher.scopes.remove("pages_manage_posts")
    deliver(case, due+timedelta(minutes=16 if change == "missed_time" else 0, seconds=1))
    assert not case.publisher.uploads and not case.publisher.publishes
    with case.sessions() as session:
        assert session.scalar(select(PublicationAttempt)).status == "needs_attention"


def test_cancel_stops_the_durable_job(case):
    due = approve(case)
    result = case.client.post(f"{case.base}/plans/{case.plan['id']}/cancel-schedule", headers=case.csrf)
    assert result.status_code == 200
    assert case.store.claim_next("cancelled", now=due+timedelta(seconds=1)) is None
    with case.sessions() as session:
        assert session.scalar(select(PublicationAttempt)).status == "cancelled"


def test_upload_lost_response_never_reuploads(case):
    due = approve(case)
    case.publisher.fail_upload = True
    deliver(case, due+timedelta(seconds=1))
    with case.sessions() as session:
        assert session.scalar(select(PublicationAttempt)).status == "upload_unknown"
    assert len(case.publisher.uploads) == 1 and not case.publisher.publishes
    assert case.store.claim_next("again", now=due+timedelta(minutes=2)) is None


@pytest.mark.parametrize("found", [True, False])
def test_publish_lost_response_only_reconciles_never_resends(case, found):
    due = approve(case)
    case.publisher.fail_publish = True
    case.publisher.remote_created = found
    deliver(case, due+timedelta(seconds=1))
    deliver(case, due+timedelta(seconds=62))
    assert len(case.publisher.uploads) == len(case.publisher.publishes) == 1
    with case.sessions() as session:
        assert session.scalar(select(PublicationAttempt)).status == ("published" if found else "publish_unknown")


def test_restart_after_post_checkpoint_does_not_publish_again(case):
    due = approve(case)
    class SimulatedCrash(BaseException):
        pass
    with patch.object(case.store, "complete", side_effect=SimulatedCrash), pytest.raises(SimulatedCrash):
        deliver(case, due+timedelta(seconds=1))
    deliver(case, due+timedelta(seconds=62))
    assert len(case.publisher.uploads) == len(case.publisher.publishes) == 1


@pytest.mark.parametrize("status", ["uploaded", "uploading", "publishing"])
def test_restart_respects_before_and_after_write_checkpoints(case, status):
    due = approve(case)
    with case.sessions() as session, session.begin():
        attempt = session.scalar(select(PublicationAttempt))
        attempt.status = status
        if status != "uploading":
            attempt.remote_upload_id = "900"
        case.publisher.remote_created = status == "publishing"
    deliver(case, due+timedelta(seconds=1))
    assert not case.publisher.uploads
    assert len(case.publisher.publishes) == (1 if status == "uploaded" else 0)
    with case.sessions() as session:
        assert session.scalar(select(PublicationAttempt)).status == ("upload_unknown" if status == "uploading" else "published")


def test_publishing_only_worker_does_not_claim_model_jobs(case):
    due = approve(case)
    case.store.enqueue("planning.week", {}, dedupe_key="older-model-work", available_at=due-timedelta(days=1))
    store = JobStore(case.sessions, workspace_id=case.workspace, allowed_kinds=("publication.facebook",))
    assert store.claim_next("publisher", now=due).kind == "publication.facebook"


def test_foreign_workspace_and_connection_are_rejected(case):
    assert case.client.post(case.schedule_path.replace(case.workspace, "foreign-workspace"), headers=case.csrf, json=case.body).status_code == 403
    result = case.client.post(case.schedule_path, headers=case.csrf, json={**case.body,"connection_id":"0"*36})
    assert result.status_code == 409
    assert not case.publisher.uploads and not case.publisher.publishes


@pytest.mark.parametrize("sufficient", [True, False])
def test_token_lifetime_is_renewed_or_atomic_approval_is_rejected(case, sufficient):
    with case.sessions() as session, session.begin():
        session.get(SocialConnection, case.connection_id).token_expires_at = datetime.now(timezone.utc)+timedelta(hours=2)
    if not sufficient:
        case.publisher.extended_lifetime = 86400
    result = case.client.post(case.schedule_path, headers=case.csrf, json=case.body)
    assert result.status_code == (200 if sufficient else 409), result.text
    with case.sessions() as session:
        if sufficient:
            assert session.get(SocialConnection, case.connection_id).token_expires_at > datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(days=50)
        else:
            assert not session.scalar(select(PublicationApproval.id))
            assert session.get(WeeklyPlan, case.plan["id"]).status == "draft"
