import csv
from io import StringIO
from pathlib import Path
from datetime import timedelta
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app import create_app
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine, build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.models import CredentialRecord, Job, OAuthTransaction, SocialConnection, SocialPost, utc_now
from brandpilot.security import CredentialCipher
from brandpilot.settings import AppSettings
from brandpilot.social import MetaConfig, SocialError, SocialSyncHandler
from brandpilot.storage import LocalStorage
from brandpilot.worker import Worker


class FakeMeta:
    def __init__(self):
        self.permissions = {"pages_show_list", "pages_read_engagement"}
        self.pages = [{"id": "1234", "name": "Test Page", "tasks": ["PROFILE_PLUS_ANALYZE"], "access_token": "fixture-page-token"}]
        self.posts_allowed = True
        self.exchanges = 0
        self.fail_on_cursor = None
        self.fail_on_first = None

    def exchange_code(self, code):
        assert code == "fixture-code"
        self.exchanges += 1
        return "fixture-user-token", 3600

    def granted_permissions(self, token):
        assert token == "fixture-user-token"
        return self.permissions

    def managed_pages(self, token):
        assert token == "fixture-user-token"
        return self.pages

    def probe_posts(self, page_id, token):
        assert (page_id, token) == ("1234", "fixture-page-token")
        if not self.posts_allowed:
            raise SocialError("permission_missing", "No post permission")
        return True

    def post_page(self, page_id, token, cursor):
        assert (page_id, token) == ("1234", "fixture-page-token")
        if cursor is None:
            if self.fail_on_first:
                raise SocialError(self.fail_on_first, "Fixture provider error")
            return ([{"id": "1234_1", "message": "First post", "created_time": "2026-09-28T10:00:00Z"}], "next")
        assert cursor == "next"
        if self.fail_on_cursor:
            raise SocialError(self.fail_on_cursor, "Fixture provider error")
        return ([{"id": "1234_2", "message": "Second post", "created_time": "2026-09-28T11:00:00Z"}], None)


class Phase5MetaApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.engine = build_engine(f"sqlite+pysqlite:///{root / 'phase5.db'}")
        Base.metadata.create_all(self.engine)
        self.meta = FakeMeta()
        self.settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:",
            storage_root=root / "storage",
            runtime=RuntimeConfig(execution_mode=ExecutionMode.OFFLINE_TEST, model_provider=ModelProvider.NONE),
            app_secret_key=b"a" * 32,
            credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars",
            meta_app_id="fixture-app",
            meta_app_secret="fixture-secret",
            meta_callback_url="https://testserver/api/v1/social/meta/callback",
            meta_graph_version="v24.0",
        )
        self.app = create_app(self.settings, engine=self.engine, meta_transport=self.meta)
        self.client = TestClient(self.app, base_url="https://testserver")
        setup = self.client.post(
            "/api/v1/setup/owner",
            headers={"X-Setup-Token": self.settings.owner_setup_token},
            json={"email": "owner@example.test", "password": "owner-password-long", "workspace_name": "A"},
        )
        self.assertEqual(setup.status_code, 201, setup.text)
        self.workspace = setup.json()["workspace_id"]
        login = self.client.post("/api/v1/session", json={
            "email": "owner@example.test", "password": "owner-password-long",
        })
        self.assertEqual(login.status_code, 200, login.text)
        self.csrf = login.json()["csrf_token"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def _begin(self):
        response = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/meta/authorize",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=lax", response.headers["set-cookie"])
        query = parse_qs(urlparse(response.json()["authorization_url"]).query)
        self.assertEqual(query["scope"], ["pages_show_list,pages_read_engagement"])
        self.assertEqual(query["redirect_uri"], [self.settings.meta_callback_url])
        return query["state"][0]

    def _callback(self, state):
        return self.client.get(
            "/api/v1/social/meta/callback",
            params={"state": state, "code": "fixture-code"},
            follow_redirects=False,
        )

    def test_callback_is_browser_bound_one_use_and_credential_is_encrypted(self):
        state = self._begin()
        missing_cookie = TestClient(self.app, base_url="https://testserver").get(
            "/api/v1/social/meta/callback",
            params={"state": state, "code": "fixture-code"},
            follow_redirects=False,
        )
        self.assertEqual(missing_cookie.status_code, 422)
        self.assertEqual(missing_cookie.json()["detail"]["code"], "state_mismatch")
        response = self._callback(state)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self.meta.exchanges, 1)
        replay = self._callback(state)
        self.assertEqual(replay.status_code, 422 if replay.json()["detail"]["code"] == "state_mismatch" else 409)
        self.assertEqual(self.meta.exchanges, 1)
        with self.app.state.social._sessions() as session:
            credential = session.scalar(select(CredentialRecord))
            self.assertIsNotNone(credential)
            self.assertNotIn(b"fixture-user-token", credential.ciphertext)

    def test_page_selection_checks_management_and_disconnect_removes_tokens(self):
        self.assertEqual(self._callback(self._begin()).status_code, 303)
        connections = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"]
        pending_id = connections[0]["id"]
        accounts = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections/{pending_id}/accounts")
        self.assertEqual(accounts.json()["accounts"], [{"id": "1234", "name": "Test Page"}])
        wrong = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{pending_id}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "9999"},
        )
        self.assertEqual(wrong.json()["detail"]["code"], "account_not_managed")
        selected = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{pending_id}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["capabilities"]["posts"], True)
        self.assertEqual(selected.json()["capabilities"]["publish"], False)
        self.assertNotIn("fixture-page-token", selected.text)
        disconnected = self.client.delete(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{pending_id}",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(disconnected.status_code, 200, disconnected.text)
        self.assertEqual(disconnected.json()["status"], "disconnected")
        with self.app.state.social._sessions() as session:
            self.assertEqual(session.query(CredentialRecord).count(), 0)
            self.assertEqual(session.query(SocialConnection).count(), 1)

    def test_write_scope_is_explicit_and_facebook_only(self):
        path = f"/api/v1/workspaces/{self.workspace}/social/meta/authorize"
        self.assertEqual(self.client.post(path, json={"publishing": True}).status_code, 403)
        response = self.client.post(path, headers={"X-CSRF-Token": self.csrf}, json={"publishing": True})
        self.assertEqual(response.status_code, 200, response.text)
        query = parse_qs(urlparse(response.json()["authorization_url"]).query)
        self.assertEqual(query["scope"], ["pages_show_list,pages_read_engagement,pages_manage_posts"])
        self.assertEqual(query["auth_type"], ["rerequest"])
        self.assertNotIn("instagram", query["scope"][0])
        with self.app.state.social._sessions() as session:
            transaction = session.scalar(select(OAuthTransaction))
            self.assertEqual(transaction.requested_scopes,
                             ["pages_show_list", "pages_read_engagement", "pages_manage_posts"])
        self.assertEqual(self.client.post(path, headers={"X-CSRF-Token": self.csrf},
                                         json={"publishing": True, "workspace_id": "other"}).status_code, 422)

    def test_existing_write_grant_does_not_enable_an_unimplemented_publisher(self):
        self.meta.permissions.add("pages_manage_posts")
        self.assertEqual(self._callback(self._begin()).status_code, 303)
        path = f"/api/v1/workspaces/{self.workspace}/social/connections"
        pending_id = self.client.get(path).json()["connections"][0]["id"]
        selected = self.client.post(
            f"{path}/{pending_id}/account", headers={"X-CSRF-Token": self.csrf},
            json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertIn("pages_manage_posts", selected.json()["granted_scopes"])
        self.assertTrue(selected.json()["capabilities"]["posts"])
        self.assertFalse(selected.json()["capabilities"]["publish"])
        self.assertFalse(selected.json()["capabilities"]["upload"])

    def test_reconnect_selected_page_rotates_credentials_without_replacing_connection(self):
        self.assertEqual(self._callback(self._begin()).status_code, 303)
        path = f"/api/v1/workspaces/{self.workspace}/social/connections"
        first_id = self.client.get(path).json()["connections"][0]["id"]
        selected = self.client.post(
            f"{path}/{first_id}/account", headers={"X-CSRF-Token": self.csrf},
            json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        with self.app.state.social._sessions() as session:
            first_credentials = {item.id for item in session.scalars(select(CredentialRecord))}
        self.assertEqual(len(first_credentials), 2)

        cancelled_state = self._begin()
        cancelled = self.client.get(
            "/api/v1/social/meta/callback",
            params={"state": cancelled_state, "error": "access_denied"},
            follow_redirects=False,
        )
        self.assertEqual(cancelled.status_code, 303)
        self.assertEqual(self.client.get(path).json()["connections"][0]["id"], first_id)
        with self.app.state.social._sessions() as session:
            self.assertEqual({item.id for item in session.scalars(select(CredentialRecord))}, first_credentials)

        self.assertEqual(self._callback(self._begin()).status_code, 303)
        pending_id = next(item["id"] for item in self.client.get(path).json()["connections"]
                          if item["status"] == "authorizing")
        reconnected = self.client.post(
            f"{path}/{pending_id}/account", headers={"X-CSRF-Token": self.csrf},
            json={"account_id": "1234"},
        )
        self.assertEqual(reconnected.status_code, 200, reconnected.text)
        self.assertEqual(reconnected.json()["id"], first_id)
        self.assertEqual(reconnected.json()["status"], "connected_partial")
        with self.app.state.social._sessions() as session:
            self.assertEqual(session.query(SocialConnection).count(), 1)
            credentials = {item.id for item in session.scalars(select(CredentialRecord))}
            self.assertEqual(len(credentials), 2)
            self.assertTrue(first_credentials.isdisjoint(credentials))

    def test_partial_permission_and_workspace_scope(self):
        self.meta.permissions = {"pages_show_list"}
        self._callback(self._begin())
        connection = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"][0]
        selected = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["status"], "permission_missing")
        self.assertFalse(selected.json()["capabilities"]["posts"])
        other = self.client.post(
            "/api/v1/workspaces", headers={"X-CSRF-Token": self.csrf}, json={"name": "B"},
        )
        other_id = other.json()["workspace_id"]
        forged = self.client.get(f"/api/v1/workspaces/{other_id}/social/connections/{connection['id']}/accounts")
        self.assertEqual(forged.status_code, 404)

    def test_expired_state_is_rejected_before_exchange(self):
        state = self._begin()
        with self.app.state.social._sessions() as session, session.begin():
            transaction = session.scalar(select(OAuthTransaction))
            transaction.expires_at = transaction.created_at
        response = self._callback(state)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "state_expired")
        self.assertEqual(self.meta.exchanges, 0)

    def test_replay_with_original_cookie_and_cancellation(self):
        state = self._begin()
        cookie = self.client.cookies.get("falkrona_meta_oauth")
        self.assertEqual(self._callback(state).status_code, 303)
        replay = self.client.get(
            "/api/v1/social/meta/callback",
            params={"state": state, "code": "fixture-code"},
            headers={"Cookie": f"falkrona_meta_oauth={cookie}"},
            follow_redirects=False,
        )
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json()["detail"]["code"], "state_replayed")
        cancelled_state = self._begin()
        cancelled = self.client.get(
            "/api/v1/social/meta/callback",
            params={"state": cancelled_state, "error": "access_denied"},
            follow_redirects=False,
        )
        self.assertEqual(cancelled.status_code, 303)
        self.assertIn("social=cancelled", cancelled.headers["location"])
        self.assertEqual(self.meta.exchanges, 1)

    def test_page_without_management_task_cannot_be_selected(self):
        self._callback(self._begin())
        connection = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"][0]
        self.meta.pages[0]["tasks"] = []
        response = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "account_not_managed")

    def test_linked_instagram_selection_sync_and_disconnect(self):
        self.meta.permissions.add("instagram_basic")
        self.meta.instagram_accounts = lambda token: [{"id": "5678", "name": "nilecoffee",
            "tasks": ["PROFILE_PLUS_ANALYZE"], "access_token": "fixture-page-token"}]
        def instagram_posts(account_id, token, cursor):
            self.assertEqual((account_id, token, cursor), ("5678", "fixture-page-token", None))
            return [{"id": "56789", "message": "Instagram coffee", "created_time": "2026-09-28T10:00:00Z"}], None
        self.meta.instagram_post_page = instagram_posts
        self.assertEqual(self._callback(self._begin()).status_code, 303)
        path = f"/api/v1/workspaces/{self.workspace}/social/connections"
        pending = self.client.get(path).json()["connections"][0]["id"]
        choices = self.client.get(f"{path}/{pending}/accounts").json()["accounts"]
        self.assertIn({"id": "ig:5678", "name": "Instagram · nilecoffee"}, choices)
        selected = self.client.post(f"{path}/{pending}/account", headers={"X-CSRF-Token": self.csrf}, json={"account_id": "ig:5678"})
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["provider"], "instagram")
        sessions = build_session_factory(self.engine); store = JobStore(sessions, workspace_id=self.workspace)
        queued = self.client.post(f"{path}/{pending}/sync", headers={"X-CSRF-Token": self.csrf}, json={"dedupe_key": "ig-sync"})
        self.assertEqual(queued.status_code, 202, queued.text)
        handler = SocialSyncHandler(sessions, store, CredentialCipher({1: b"b" * 32}, current_version=1),
            MetaConfig("fixture-app", "fixture-secret", "https://testserver/api/v1/social/meta/callback", "v24.0"),
            offline=True, transport=self.meta)
        self.assertTrue(Worker("ig-test", store, self.app.state.storage, social_handler=handler).process_one())
        posts = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts").json()["posts"]
        self.assertEqual(posts[0]["provider"], "instagram")
        self.assertEqual(posts[0]["text"], "Instagram coffee")
        self.assertEqual(self.client.delete(f"{path}/{pending}", headers={"X-CSRF-Token": self.csrf}).status_code, 200)

    def test_arabic_csv_preview_and_reimport_are_idempotent(self):
        csv_data = "معرف المنشور,النص,تاريخ النشر\npost-1,إعلان جديد,2026-09-28T10:00:00Z\n".encode("utf-8")

        def upload(key):
            return self.client.post(
                f"/api/v1/workspaces/{self.workspace}/social/imports",
                headers={"X-CSRF-Token": self.csrf},
                data={"provider": "instagram", "account_id": "owner-export", "dedupe_key": key},
                files={"file": ("posts.csv", csv_data, "text/csv")},
            )

        first = upload("arabic-1")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["rows"][0]["text"], "إعلان جديد")
        wrong_endpoint = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/imports/{first.json()['id']}/confirm",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(wrong_endpoint.status_code, 404)
        confirmed = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/imports/{first.json()['id']}/confirm",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["posts_created"], 1)
        second = upload("arabic-2")
        repeated = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/imports/{second.json()['id']}/confirm",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(repeated.json()["posts_created"], 0)
        posts = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts")
        self.assertEqual(len(posts.json()["posts"]), 1)
        self.assertEqual(posts.json()["posts"][0]["provenance"], "owner_imported")
        exported = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.headers["cache-control"], "no-store")
        rows = list(csv.DictReader(StringIO(exported.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "إعلان جديد")
        self.assertEqual(rows[0]["source_id"], "post-1")
        with self.app.state.social._sessions() as session:
            self.assertEqual(session.query(SocialPost).count(), 1)

    def test_post_export_is_workspace_scoped_and_spreadsheet_safe(self):
        with self.app.state.social._sessions() as session, session.begin():
            session.add(SocialPost(
                workspace_id=self.workspace, provider="facebook_pages", account_id="page",
                source_id="=HYPERLINK(1)", text="  +cmd", provenance="owner_imported",
            ))
        exported = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts/export")
        self.assertEqual(exported.status_code, 200, exported.text)
        rows = list(csv.DictReader(StringIO(exported.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["source_id"], "'=HYPERLINK(1)")
        self.assertEqual(rows[0]["text"], "'  +cmd")
        denied = self.client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/social/posts/export")
        self.assertEqual(denied.status_code, 403)

    def test_queued_meta_sync_checkpoints_and_upserts_two_pages(self):
        self._callback(self._begin())
        connection = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"][0]
        selected = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200)
        sessions = build_session_factory(self.engine)
        store = JobStore(sessions, workspace_id=self.workspace)
        handler = SocialSyncHandler(
            sessions, store, CredentialCipher({1: self.settings.credential_encryption_key}, current_version=1),
            MetaConfig(
                self.settings.meta_app_id, self.settings.meta_app_secret,
                self.settings.meta_callback_url, self.settings.meta_graph_version,
            ),
            offline=True, transport=self.meta,
        )
        worker = Worker("meta-test-worker", store, LocalStorage(self.settings.storage_root), handler)
        for key in ("first", "repeat"):
            queued = self.client.post(
                f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/sync",
                headers={"X-CSRF-Token": self.csrf}, json={"dedupe_key": key},
            )
            self.assertEqual(queued.status_code, 202, queued.text)
            self.assertTrue(worker.process_one())
            job = store.get(queued.json()["job_id"])
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["checkpoint"]["pages_done"], 2)
        posts = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts").json()["posts"]
        self.assertEqual(len(posts), 2)
        self.assertEqual({post["provenance"] for post in posts}, {"meta_api"})

    def test_rate_limit_retries_from_checkpoint_and_revocation_disables_posts(self):
        self._callback(self._begin())
        connection = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"][0]
        self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        sessions = build_session_factory(self.engine)
        store = JobStore(sessions, workspace_id=self.workspace)
        handler = SocialSyncHandler(
            sessions, store, CredentialCipher({1: self.settings.credential_encryption_key}, current_version=1),
            MetaConfig(
                self.settings.meta_app_id, self.settings.meta_app_secret,
                self.settings.meta_callback_url, self.settings.meta_graph_version,
            ),
            offline=True, transport=self.meta,
        )
        worker = Worker("meta-retry-worker", store, LocalStorage(self.settings.storage_root), handler)
        queued = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/sync",
            headers={"X-CSRF-Token": self.csrf}, json={"dedupe_key": "rate-limit"},
        )
        self.meta.fail_on_cursor = "rate_limited"
        self.assertTrue(worker.process_one())
        self.assertEqual(store.get(queued.json()["job_id"])["checkpoint"]["cursor"], "next")
        self.assertEqual(store.get(queued.json()["job_id"])["status"], "queued")
        self.meta.fail_on_cursor = None
        with sessions() as session, session.begin():
            job = session.get(Job, queued.json()["job_id"])
            job.available_at = utc_now() - timedelta(seconds=1)
        self.assertTrue(worker.process_one())
        self.assertEqual(store.get(queued.json()["job_id"])["status"], "completed")
        self.assertEqual(len(self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts").json()["posts"]), 2)
        revoked = self.client.post(
            f"/api/v1/workspaces/{self.workspace}/social/connections/{connection['id']}/sync",
            headers={"X-CSRF-Token": self.csrf}, json={"dedupe_key": "revoked"},
        )
        self.meta.fail_on_first = "needs_reauth"
        self.assertTrue(worker.process_one())
        self.assertEqual(store.get(revoked.json()["job_id"])["status"], "failed")
        updated = self.client.get(f"/api/v1/workspaces/{self.workspace}/social/connections").json()["connections"][0]
        self.assertEqual(updated["status"], "needs_reauth")
        self.assertFalse(updated["capabilities"]["posts"])

    def test_disconnect_before_worker_claim_prevents_post_sync(self):
        self._callback(self._begin())
        path = f"/api/v1/workspaces/{self.workspace}/social/connections"
        connection_id = self.client.get(path).json()["connections"][0]["id"]
        selected = self.client.post(
            f"{path}/{connection_id}/account",
            headers={"X-CSRF-Token": self.csrf}, json={"account_id": "1234"},
        )
        self.assertEqual(selected.status_code, 200)
        queued = self.client.post(
            f"{path}/{connection_id}/sync",
            headers={"X-CSRF-Token": self.csrf}, json={"dedupe_key": "disconnect-before-claim"},
        )
        self.assertEqual(queued.status_code, 202)
        disconnected = self.client.delete(
            f"{path}/{connection_id}", headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(disconnected.status_code, 200)
        sessions = build_session_factory(self.engine)
        store = JobStore(sessions, workspace_id=self.workspace)
        handler = SocialSyncHandler(
            sessions, store, CredentialCipher({1: self.settings.credential_encryption_key}, current_version=1),
            MetaConfig(
                self.settings.meta_app_id, self.settings.meta_app_secret,
                self.settings.meta_callback_url, self.settings.meta_graph_version,
            ),
            offline=True, transport=self.meta,
        )
        worker = Worker("meta-disconnect-worker", store, LocalStorage(self.settings.storage_root), handler)
        self.assertTrue(worker.process_one())
        self.assertEqual(store.get(queued.json()["job_id"])["status"], "failed")
        self.assertEqual(self.client.get(f"/api/v1/workspaces/{self.workspace}/social/posts").json()["posts"], [])


if __name__ == "__main__":
    unittest.main()
