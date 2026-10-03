"""Workspace-scoped Meta read authorization and capability checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import hmac
from io import StringIO
import json
from pathlib import Path
import secrets
import re
from typing import Any, Iterator, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .database import set_workspace_context
from .jobs import JobClaim, JobStore
from .models import (
    AppSession, AuditEvent, CredentialRecord, ImportJob, Job, OAuthTransaction,
    SocialConnection, SocialPost, WorkspaceMembership, utc_now,
)
from .security import CredentialCipher
from .storage import LocalStorage


# Live onboarding is Facebook-only while Instagram app setup/testing is deferred.
READ_SCOPES = ("pages_show_list", "pages_read_engagement")
MANAGED_PAGE_TASKS = frozenset({
    "ANALYZE", "MANAGE", "PROFILE_PLUS_ANALYZE", "PROFILE_PLUS_MANAGE",
    "PROFILE_PLUS_FULL_CONTROL",
})
CAPABILITIES = (
    "identity", "account_list", "posts", "comments", "account_metrics",
    "post_metrics", "upload", "publish", "webhooks",
)
MANUAL_PROVIDERS = frozenset({
    "facebook_pages", "instagram",
})
POST_COLUMNS = {
    "source_id": {"id", "post id", "post_id", "معرف المنشور", "رقم المنشور"},
    "text": {"caption", "message", "text", "content", "النص", "المحتوى", "الوصف"},
    "published_at": {"date", "published at", "published_at", "تاريخ النشر"},
    "source_url": {"url", "permalink", "link", "الرابط"},
}
UNKNOWN_META_TOKEN_LIFETIME_SECONDS = 24 * 60 * 60
MAX_META_TOKEN_LIFETIME_SECONDS = 60 * 24 * 60 * 60


class SocialError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MetaConfig:
    app_id: str = ""
    app_secret: str = ""
    callback_url: str = ""
    graph_version: str = ""

    @property
    def configured(self) -> bool:
        return all((self.app_id, self.app_secret, self.callback_url, self.graph_version))


class MetaTransport(Protocol):
    def exchange_code(self, code: str) -> tuple[str, int]: ...
    def extend_user_token(self, token: str) -> tuple[str, int]: ...
    def granted_permissions(self, token: str) -> set[str]: ...
    def managed_pages(self, token: str) -> list[dict[str, Any]]: ...
    def probe_posts(self, page_id: str, token: str) -> bool: ...
    def post_page(self, page_id: str, token: str, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]: ...
    def upload_photo(self, page_id: str, token: str, content: bytes) -> str: ...
    def publish_photo(self, page_id: str, token: str, photo_id: str, caption: str) -> str: ...
    def published_photo_story(self, page_id: str, token: str, photo_id: str, caption: str) -> str | None: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class MetaGraphTransport:
    """Fixed-host, bounded Graph API calls; tokens never enter URL parameters."""

    def __init__(self, config: MetaConfig) -> None:
        self._config = config
        self._opener = build_opener(_NoRedirect)

    def _request(
        self, path: str, *, token: str | None = None, data: dict[str, str] | None = None,
        params: dict[str, str] | None = None, file: bytes | None = None,
    ) -> dict[str, Any]:
        base = f"https://graph.facebook.com/{self._config.graph_version}/{path}"
        url = f"{base}?{urlencode(params)}" if params else base
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = urlencode(data).encode("ascii") if data else None
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if file is not None:
            boundary = "falkrona" + uuid.uuid4().hex
            parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
                     for key, value in (data or {}).items()]
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="post.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + file + b"\r\n")
            body = b"".join(parts) + f"--{boundary}--\r\n".encode()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
        try:
            with self._opener.open(request, timeout=10) as response:
                content = response.read(1_000_001)
        except HTTPError as exc:
            try:
                body = json.loads(exc.read(8192))
                provider_code = body.get("error", {}).get("code")
            except (ValueError, AttributeError, TypeError):
                provider_code = None
            code = (
                "rate_limited" if exc.code == 429 or provider_code in {4, 17, 32, 613}
                else "needs_reauth" if exc.code == 401 or provider_code == 190
                else "permission_missing" if exc.code == 403 or provider_code in {10, 200}
                else "provider_error"
            )
            raise SocialError(code, "Meta rejected the request.") from exc
        except (URLError, TimeoutError) as exc:
            raise SocialError("provider_unavailable", "Meta could not be reached.") from exc
        if len(content) > 1_000_000:
            raise SocialError("provider_response_too_large", "Meta returned too much data.")
        try:
            result = json.loads(content)
        except (UnicodeDecodeError, ValueError) as exc:
            raise SocialError("provider_malformed", "Meta returned an invalid response.") from exc
        if not isinstance(result, dict) or "error" in result:
            raise SocialError("provider_error", "Meta rejected the request.")
        return result

    def exchange_code(self, code: str) -> tuple[str, int]:
        result = self._request(
            "oauth/access_token",
            data={
                "client_id": self._config.app_id,
                "client_secret": self._config.app_secret,
                "redirect_uri": self._config.callback_url,
                "code": code,
            },
        )
        token = result.get("access_token")
        expiry = result.get("expires_in")
        if not isinstance(token, str) or not token.strip():
            raise SocialError("provider_malformed", "Meta did not return an access token.")
        if isinstance(expiry, str) and len(expiry) <= 10 and expiry.isascii() and expiry.isdecimal():
            expiry = int(expiry)
        if expiry is None or expiry == 0:
            # An omitted/zero provider lifetime is never treated as permanent.
            expiry = UNKNOWN_META_TOKEN_LIFETIME_SECONDS
        if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry < 0:
            raise SocialError("provider_malformed", "Meta returned an invalid token lifetime.")
        return token, min(expiry, MAX_META_TOKEN_LIFETIME_SECONDS)

    @staticmethod
    def _write_id(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:_[0-9]+)?", value):
            raise SocialError("provider_malformed", "Meta did not return a valid post or photo ID.")
        return value

    def extend_user_token(self, token: str) -> tuple[str, int]:
        result = self._request("oauth/access_token", data={"grant_type": "fb_exchange_token",
            "client_id": self._config.app_id, "client_secret": self._config.app_secret,
            "fb_exchange_token": token})
        extended, expiry = result.get("access_token"), result.get("expires_in")
        if isinstance(expiry, str) and len(expiry) <= 10 and expiry.isascii() and expiry.isdecimal():
            expiry = int(expiry)
        if not isinstance(extended, str) or not extended.strip():
            raise SocialError("provider_malformed", "Meta did not return a refreshed authorization.")
        if isinstance(expiry, bool):
            raise SocialError("provider_malformed", "Meta returned an invalid refreshed lifetime.")
        # Unknown/zero lifetime remains bounded, never assumed permanent.
        if expiry in (None, 0):
            expiry = UNKNOWN_META_TOKEN_LIFETIME_SECONDS
        if not isinstance(expiry, int) or expiry < 0:
            raise SocialError("provider_malformed", "Meta returned an invalid refreshed lifetime.")
        return extended, min(expiry, MAX_META_TOKEN_LIFETIME_SECONDS)

    def upload_photo(self, page_id: str, token: str, content: bytes) -> str:
        self._write_id(page_id)
        if not content or len(content) > 20_000_000:
            raise SocialError("invalid_image", "The saved image is too large to publish.")
        result = self._request(f"{page_id}/photos", token=token, data={"published": "false"}, file=content)
        return self._write_id(result.get("id"))

    def publish_photo(self, page_id: str, token: str, photo_id: str, caption: str) -> str:
        self._write_id(page_id)
        self._write_id(photo_id)
        result = self._request(f"{page_id}/feed", token=token,
            data={"message": caption, "attached_media[0]": json.dumps({"media_fbid": photo_id})})
        post_id = self._write_id(result.get("id"))
        if not post_id.startswith(page_id + "_"):
            raise SocialError("provider_malformed", "Meta returned a post for a different Page.")
        return post_id

    def published_photo_story(self, page_id: str, token: str, photo_id: str, caption: str) -> str | None:
        self._write_id(photo_id)
        result = self._request(photo_id, token=token, params={"fields": "page_story_id"})
        if not result.get("page_story_id"):
            return None
        story = self._write_id(result["page_story_id"])
        if not story.startswith(page_id + "_"):
            raise SocialError("provider_malformed", "Meta returned a story for a different Page.")
        post = self._request(story, token=token, params={"fields": "id,message"})
        if post.get("id") != story or post.get("message", "") != caption:
            raise SocialError("provider_malformed", "The remote post does not match the approved caption.")
        return story

    def granted_permissions(self, token: str) -> set[str]:
        result = self._request("me/permissions", token=token)
        rows = result.get("data")
        if not isinstance(rows, list):
            raise SocialError("provider_malformed", "Meta permissions are unavailable.")
        return {
            row["permission"] for row in rows
            if isinstance(row, dict) and row.get("status") == "granted"
            and isinstance(row.get("permission"), str)
        }

    def managed_pages(self, token: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(10):
            params = {"fields": "id,name,tasks,access_token", "limit": "100"}
            if cursor:
                params["after"] = cursor
            result = self._request("me/accounts", token=token, params=params)
            rows = result.get("data")
            if not isinstance(rows, list):
                raise SocialError("provider_malformed", "Meta Page list is invalid.")
            pages.extend(row for row in rows if isinstance(row, dict))
            paging = result.get("paging") or {}
            if not isinstance(paging, dict):
                raise SocialError("provider_malformed", "Meta Page pagination is invalid.")
            if not isinstance(paging.get("next"), str):
                return pages
            cursors = paging.get("cursors") or {}
            next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
                raise SocialError("provider_malformed", "Meta Page cursor is invalid.")
            seen.add(next_cursor)
            cursor = next_cursor
        raise SocialError("pagination_limit", "Meta Page list exceeded the safe page limit.")

    def probe_posts(self, page_id: str, token: str) -> bool:
        result = self._request(f"{page_id}/posts", token=token, params={"fields": "id", "limit": "1"})
        if not isinstance(result.get("data"), list):
            raise SocialError("provider_malformed", "Meta post response is invalid.")
        return True

    def post_engagement(self, provider: str, post_id: str, token: str) -> dict:
        if not post_id or any(c not in "0123456789_" for c in post_id):
            raise SocialError("invalid_post_id", "A platform post ID is required for live measurements.")
        if provider == "facebook_pages":
            result = self._request(post_id, token=token,
                params={"fields": "reactions.limit(0).summary(true),comments.limit(0).summary(true),shares"})
            for key in ("reactions", "comments", "shares"):
                if key in result and not isinstance(result[key], dict):
                    raise SocialError("provider_malformed", "The platform returned invalid engagement counts.")
                if key != "shares" and key in result and "summary" in result[key] and not isinstance(result[key]["summary"], dict):
                    raise SocialError("provider_malformed", "The platform returned invalid engagement counts.")
            try:
                values = {"reactions": (result.get("reactions") or {}).get("summary", {}).get("total_count"),
                          "comments": (result.get("comments") or {}).get("summary", {}).get("total_count"),
                          "shares": (result.get("shares") or {}).get("count")}
            except AttributeError:
                raise SocialError("provider_malformed", "The platform returned invalid engagement counts.") from None
        elif provider == "instagram":
            result = self._request(post_id, token=token, params={"fields": "like_count,comments_count"})
            values = {"reactions": result.get("like_count"), "comments": result.get("comments_count")}
        else:
            raise SocialError("unsupported_platform", "Choose Facebook or Instagram.")
        if any(value is not None and (type(value) is not int or value < 0) for value in values.values()):
            raise SocialError("provider_malformed", "The platform returned invalid engagement counts.")
        return values

    def instagram_accounts(self, token: str) -> list[dict]:
        accounts = []
        for page in self.managed_pages(token):
            if not isinstance(page.get("tasks"), list) or not MANAGED_PAGE_TASKS.intersection(page["tasks"]):
                continue
            try:
                result = self._request(str(page["id"]), token=token, params={"fields": "instagram_business_account{id,username}"})
            except SocialError as exc:
                if exc.code == "permission_missing":
                    continue
                raise
            account = result.get("instagram_business_account")
            if isinstance(account, dict) and isinstance(account.get("id"), str) and page.get("access_token"):
                accounts.append({"id": account["id"], "name": account.get("username") or "Instagram",
                    "tasks": page["tasks"], "access_token": page["access_token"]})
        return accounts

    def instagram_post_page(self, account_id, token, cursor):
        params = {"fields": "id,caption,timestamp,permalink", "limit": "100"}
        if cursor:
            params["after"] = cursor
        result = self._request(f"{account_id}/media", token=token, params=params)
        rows = result.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SocialError("provider_malformed", "Instagram returned invalid posts.")
        paging = result.get("paging") or {}
        if not isinstance(paging, dict) or not isinstance(paging.get("cursors", {}), dict):
            raise SocialError("provider_malformed", "Instagram pagination is invalid.")
        after = paging.get("cursors", {}).get("after") if paging.get("next") else None
        if paging.get("next") and (not isinstance(after, str) or not after or len(after) > 2000):
            raise SocialError("provider_malformed", "Instagram cursor is invalid.")
        return [{"id": row.get("id"), "message": row.get("caption"), "created_time": row.get("timestamp"),
                 "permalink_url": row.get("permalink")} for row in rows], after

    def post_page(self, page_id: str, token: str, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        params = {"fields": "id,message,created_time,permalink_url", "limit": "100"}
        if cursor:
            params["after"] = cursor
        result = self._request(f"{page_id}/posts", token=token, params=params)
        rows = result.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SocialError("provider_malformed", "Meta post page is invalid.")
        paging = result.get("paging") or {}
        if not isinstance(paging, dict):
            raise SocialError("provider_malformed", "Meta post pagination is invalid.")
        cursors = paging.get("cursors") or {}
        next_cursor = cursors.get("after") if isinstance(cursors, dict) and isinstance(paging.get("next"), str) else None
        if isinstance(paging.get("next"), str) and (
            not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 2000
        ):
            raise SocialError("provider_malformed", "Meta post cursor is invalid.")
        return rows, next_cursor


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _spreadsheet_cell(value: str) -> str:
    return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value


def parse_social_posts(content: bytes, max_rows: int) -> tuple[list[str], list[dict[str, str | None]]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SocialError("invalid_encoding", "Social CSV must use UTF-8.") from exc
    reader = csv.DictReader(StringIO(decoded))
    if not reader.fieldnames:
        raise SocialError("missing_headers", "Social CSV requires a header row.")
    headers = [header.strip() for header in reader.fieldnames if header]
    mapping = {
        key: next((header for header in headers if header.casefold() in aliases), None)
        for key, aliases in POST_COLUMNS.items()
    }
    if not mapping["source_id"]:
        raise SocialError("missing_post_id", "Social CSV needs a post ID column.")
    rows: list[dict[str, str | None]] = []
    for index, raw in enumerate(reader):
        if index >= max_rows:
            raise SocialError("too_many_rows", "Social CSV exceeds the row limit.")
        if None in raw:
            raise SocialError("malformed_row", "A social CSV row has extra columns.")
        source_id = (raw.get(mapping["source_id"]) or "").strip()
        if not source_id or len(source_id) > 200:
            raise SocialError("invalid_post_id", "Every post needs a source ID under 200 characters.")
        post_text = (raw.get(mapping["text"]) or "").strip() if mapping["text"] else ""
        source_url = (raw.get(mapping["source_url"]) or "").strip() if mapping["source_url"] else ""
        date_value = (raw.get(mapping["published_at"]) or "").strip() if mapping["published_at"] else ""
        if len(post_text) > 20_000 or len(source_url) > 2048:
            raise SocialError("row_too_large", "A social post field exceeds its limit.")
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise SocialError("invalid_source_url", "Post URLs must be public HTTPS links.")
        if date_value:
            try:
                datetime.fromisoformat(date_value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SocialError("invalid_date", "Post dates must use ISO 8601.") from exc
        counts = {}
        for key in ("reactions", "comments", "shares", "saves"):
            column = next((h for h in headers if h.casefold() in ({"likes", "reactions"} if key == "reactions" else {key})), None)
            value = (raw.get(column) or "").strip() if column else ""
            if value:
                if not value.isascii() or not value.isdecimal() or len(value) > 12:
                    raise SocialError("invalid_engagement", "Engagement columns need non-negative whole numbers. Leave unknown counts blank.")
                counts[key] = int(value)
        rows.append({
            "source_id": source_id, "text": post_text,
            "published_at": date_value or None, "source_url": source_url or None, "engagement": counts,
        })
    if not rows:
        raise SocialError("empty_import", "Social CSV has no post rows.")
    return headers, rows


class SocialService:
    def __init__(
        self, sessions: sessionmaker[Session], accounts: AccountService,
        cipher: CredentialCipher, config: MetaConfig, storage: LocalStorage, *,
        offline: bool, max_upload_bytes: int = 10_000_000, max_rows: int = 5_000,
        transport: MetaTransport | None = None,
        live_publish_enabled: bool = False,
    ) -> None:
        self._sessions = sessions
        self._accounts = accounts
        self._cipher = cipher
        self._config = config
        self._storage = storage
        self._max_upload_bytes = max_upload_bytes
        self._max_rows = max_rows
        self._offline = offline
        self._transport = transport or MetaGraphTransport(config)
        self._injected_transport = transport is not None
        self._live_publish_enabled = live_publish_enabled and not offline

    @property
    def meta_read_available(self) -> bool:
        return self._config.configured and (not self._offline or self._injected_transport)

    def _available(self) -> None:
        if not self._config.configured:
            raise SocialError("not_configured", "Meta application credentials are not configured.")
        if self._offline and not self._injected_transport:
            raise SocialError("external_disabled", "Social authorization is disabled in offline mode.")

    @staticmethod
    def _audit(session: Session, workspace_id: str, actor: str, action: str, target: str) -> None:
        session.add(AuditEvent(
            workspace_id=workspace_id, actor_user_id=actor, action=action,
            target_type="social_import" if action.startswith("social.import") else "social_connection",
            target_id=target, detail={},
        ))

    def begin(self, principal: Principal, workspace_id: str, *, publishing: bool = False) -> dict[str, str]:
        self._accounts.require_permission(principal, workspace_id, "members")
        self._available()
        scopes = READ_SCOPES + (("pages_manage_posts",) if publishing else ())
        state = f"{workspace_id}.{secrets.token_urlsafe(32)}"
        browser = secrets.token_urlsafe(32)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            session.add(OAuthTransaction(
                workspace_id=workspace_id, user_id=principal.user_id,
                session_id=principal.session_id, provider="meta",
                state_hash=_hash(state), browser_hash=_hash(browser),
                requested_scopes=list(scopes),
                expires_at=utc_now() + timedelta(minutes=10),
            ))
        url = f"https://www.facebook.com/{self._config.graph_version}/dialog/oauth?{urlencode({
            'client_id': self._config.app_id,
            'redirect_uri': self._config.callback_url,
            'response_type': 'code',
            'scope': ','.join(scopes),
            'state': state,
            **({'auth_type': 'rerequest'} if publishing else {}),
        })}"
        return {"authorization_url": url, "browser_cookie": browser}

    def callback(self, state: str, browser: str | None, code: str | None, error: str | None) -> str:
        self._available()
        if len(state) > 200 or (browser is not None and len(browser) > 200):
            raise SocialError("state_mismatch", "OAuth state is invalid.")
        try:
            workspace_id = str(uuid.UUID(state.split(".", 1)[0]))
        except (ValueError, IndexError, AttributeError) as exc:
            raise SocialError("state_mismatch", "OAuth state is invalid.") from exc
        now = utc_now()
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            transaction = session.scalar(select(OAuthTransaction).where(
                OAuthTransaction.workspace_id == workspace_id,
                OAuthTransaction.state_hash == _hash(state),
            ))
            if transaction is None or not browser or not hmac.compare_digest(transaction.browser_hash, _hash(browser)):
                raise SocialError("state_mismatch", "OAuth state does not match this browser.")
            if transaction.consumed_at is not None:
                raise SocialError("state_replayed", "OAuth state has already been used.")
            if transaction.expires_at.replace(tzinfo=timezone.utc) <= now:
                raise SocialError("state_expired", "OAuth authorization has expired.")
            app_session = session.get(AppSession, transaction.session_id)
            membership = session.scalar(select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == transaction.user_id,
                WorkspaceMembership.revoked_at.is_(None),
                WorkspaceMembership.role == "owner",
            ))
            if (app_session is None or app_session.revoked_at is not None
                or app_session.expires_at.replace(tzinfo=timezone.utc) <= now
                or app_session.user_id != transaction.user_id or membership is None):
                raise SocialError("session_expired", "The initiating session no longer has owner access.")
            claimed = session.execute(update(OAuthTransaction).where(
                OAuthTransaction.id == transaction.id,
                OAuthTransaction.consumed_at.is_(None),
            ).values(consumed_at=now))
            if claimed.rowcount != 1:
                raise SocialError("state_replayed", "OAuth state has already been used.")
            user_id = transaction.user_id
        if error:
            return "cancelled"
        if not code or len(code) > 4096:
            raise SocialError("code_missing", "Meta did not return an authorization code.")
        token, lifetime = self._transport.exchange_code(code)
        scopes = self._transport.granted_permissions(token)
        ciphertext, version = self._cipher.encrypt(workspace_id, "meta_user", token)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            credential = CredentialRecord(
                workspace_id=workspace_id, provider="meta_user",
                ciphertext=ciphertext, key_version=version,
            )
            session.add(credential)
            session.flush()
            connection = SocialConnection(
                workspace_id=workspace_id, provider="meta",
                authorized_by_user_id=user_id, status="authorizing" if "pages_show_list" in scopes else "permission_missing",
                granted_scopes=sorted(scopes),
                capabilities={key: False for key in CAPABILITIES},
                user_credential_id=credential.id,
                token_expires_at=now + timedelta(seconds=lifetime),
            )
            session.add(connection)
            session.flush()
            self._audit(session, workspace_id, user_id, "social.authorize", connection.id)
        return "account_selection"

    def list_connections(self, principal: Principal, workspace_id: str) -> list[dict[str, Any]]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            rows = session.scalars(select(SocialConnection).where(
                SocialConnection.workspace_id == workspace_id,
            ).order_by(SocialConnection.created_at.desc())).all()
            for row in rows:
                if (row.status in {"authorizing", "connected", "connected_partial", "permission_missing", "rate_limited"}
                    and row.token_expires_at is not None
                    and row.token_expires_at.replace(tzinfo=timezone.utc) <= utc_now()):
                    row.status = "needs_reauth"
                    row.capabilities = {key: False for key in CAPABILITIES}
                elif row.provider == "meta" and row.status in {"connected", "connected_partial"}:
                    can_publish = self._live_publish_enabled and "pages_manage_posts" in row.granted_scopes and bool(row.account_credential_id)
                    row.capabilities = {**row.capabilities, "upload": can_publish, "publish": can_publish}
            return [self._payload(row) for row in rows]

    @staticmethod
    def _payload(row: SocialConnection) -> dict[str, Any]:
        return {
            "id": row.id, "provider": row.provider, "account_id": row.account_id,
            "account_name": row.account_name, "status": row.status,
            "granted_scopes": row.granted_scopes, "capabilities": row.capabilities,
            "token_expires_at": row.token_expires_at.isoformat() if row.token_expires_at else None,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
        }

    def _pending(self, session: Session, workspace_id: str, connection_id: str) -> SocialConnection:
        row = session.scalar(select(SocialConnection).where(
            SocialConnection.workspace_id == workspace_id,
            SocialConnection.id == connection_id,
        ))
        if row is None:
            raise SocialError("connection_not_found", "Connection was not found.")
        return row

    def _user_token(self, session: Session, row: SocialConnection) -> str:
        if row.user_credential_id is None or row.token_expires_at is None or row.token_expires_at.replace(tzinfo=timezone.utc) <= utc_now():
            raise SocialError("needs_reauth", "Meta authorization has expired. Reconnect this account.")
        credential = session.scalar(select(CredentialRecord).where(
            CredentialRecord.workspace_id == row.workspace_id,
            CredentialRecord.id == row.user_credential_id,
            CredentialRecord.provider == "meta_user",
        ))
        if credential is None:
            raise SocialError("needs_reauth", "Meta credentials are unavailable.")
        return self._cipher.decrypt(row.workspace_id, "meta_user", credential.ciphertext, credential.key_version)

    def managed_accounts(self, principal: Principal, workspace_id: str, connection_id: str) -> list[dict[str, str]]:
        self._accounts.require_permission(principal, workspace_id, "members")
        self._available()
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._pending(session, workspace_id, connection_id)
            if row.status != "authorizing" or row.authorized_by_user_id != principal.user_id:
                raise SocialError("selection_unavailable", "This authorization cannot select an account.")
            token = self._user_token(session, row)
        pages = self._transport.managed_pages(token)
        accounts = [
            {"id": str(page["id"]), "name": str(page.get("name") or page["id"])}
            for page in pages
            if isinstance(page.get("id"), str)
            and isinstance(page.get("tasks"), list)
            and MANAGED_PAGE_TASKS.intersection(page["tasks"])
        ]
        if "instagram_basic" in row.granted_scopes:
            accounts += [{"id": "ig:" + account["id"], "name": "Instagram · " + str(account["name"])}
                         for account in self._transport.instagram_accounts(token)]
        return accounts

    def select_account(
        self, principal: Principal, workspace_id: str, connection_id: str, account_id: str,
    ) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "members")
        self._available()
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._pending(session, workspace_id, connection_id)
            if row.status != "authorizing" or row.authorized_by_user_id != principal.user_id:
                raise SocialError("selection_unavailable", "This authorization cannot select an account.")
            token = self._user_token(session, row)
        instagram = account_id.startswith("ig:")
        provider = "instagram" if instagram else "meta"
        if instagram and "instagram_basic" not in row.granted_scopes:
            raise SocialError("permission_missing", "Authorize Instagram access to select this account.")
        account_id = account_id[3:] if instagram else account_id
        choices = self._transport.instagram_accounts(token) if instagram else self._transport.managed_pages(token)
        matching = [page for page in choices if str(page.get("id")) == account_id]
        if len(matching) != 1:
            raise SocialError("account_not_managed", "The account is not managed by this authorization.")
        page = matching[0]
        if not isinstance(page.get("tasks"), list) or not MANAGED_PAGE_TASKS.intersection(page["tasks"]):
            raise SocialError("account_not_managed", "The account lacks management privileges.")
        page_token = page.get("access_token")
        if not isinstance(page_token, str) or not page_token:
            raise SocialError("permission_missing", "Meta did not grant an account token.")
        post_access = False
        if "pages_read_engagement" in row.granted_scopes:
            try:
                if instagram:
                    self._transport.instagram_post_page(account_id, page_token, None)
                    post_access = True
                else:
                    post_access = self._transport.probe_posts(account_id, page_token)
            except SocialError as exc:
                if exc.code not in {"permission_missing", "needs_reauth"}:
                    raise
        ciphertext, version = self._cipher.encrypt(workspace_id, "meta_page", page_token)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._pending(session, workspace_id, connection_id)
            if row.status != "authorizing" or row.authorized_by_user_id != principal.user_id:
                raise SocialError("selection_unavailable", "This authorization cannot select an account.")
            existing = session.scalar(select(SocialConnection).where(
                SocialConnection.workspace_id == workspace_id,
                SocialConnection.provider == provider,
                SocialConnection.account_id == account_id,
            ))
            credential = CredentialRecord(
                workspace_id=workspace_id, provider="meta_page",
                ciphertext=ciphertext, key_version=version,
            )
            session.add(credential)
            session.flush()
            old_ids: list[str] = []
            if existing is not None:
                old_ids = [value for value in (existing.user_credential_id, existing.account_credential_id) if value]
                existing.user_credential_id = row.user_credential_id
                existing.authorized_by_user_id = principal.user_id
                existing.granted_scopes = row.granted_scopes
                existing.token_expires_at = row.token_expires_at
                session.delete(row)
                row = existing
            row.account_id = account_id
            row.provider = provider
            row.account_name = str(page.get("name") or account_id)[:255]
            row.account_credential_id = credential.id
            row.capabilities = {
                **{key: False for key in CAPABILITIES},
                "identity": True, "account_list": True, "posts": post_access,
                "upload": self._live_publish_enabled and not instagram and "pages_manage_posts" in row.granted_scopes,
                "publish": self._live_publish_enabled and not instagram and "pages_manage_posts" in row.granted_scopes,
            }
            row.status = "connected_partial" if post_access else "permission_missing"
            session.flush()
            if old_ids:
                session.execute(delete(CredentialRecord).where(
                    CredentialRecord.workspace_id == workspace_id,
                    CredentialRecord.id.in_(old_ids),
                ))
            self._audit(session, workspace_id, principal.user_id, "social.select_account", row.id)
            return self._payload(row)

    def disconnect(self, principal: Principal, workspace_id: str, connection_id: str) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._pending(session, workspace_id, connection_id)
            ids = [value for value in (row.user_credential_id, row.account_credential_id) if value]
            row.user_credential_id = None
            row.account_credential_id = None
            row.status = "disconnected"
            row.capabilities = {key: False for key in CAPABILITIES}
            session.flush()
            if ids:
                session.execute(delete(CredentialRecord).where(
                    CredentialRecord.workspace_id == workspace_id,
                    CredentialRecord.id.in_(ids),
                ))
            self._audit(session, workspace_id, principal.user_id, "social.disconnect", row.id)
            return self._payload(row)

    def create_manual_import(
        self, principal: Principal, workspace_id: str, provider: str,
        account_id: str, filename: str, content: bytes, dedupe_key: str,
    ) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "write")
        if provider not in MANUAL_PROVIDERS or not account_id.strip() or len(account_id) > 160:
            raise SocialError("invalid_source", "Choose a supported platform and account label.")
        if not dedupe_key.strip() or len(dedupe_key) > 200:
            raise SocialError("invalid_dedupe_key", "The import retry key is invalid.")
        if Path(filename).suffix.casefold() != ".csv" or len(content) > self._max_upload_bytes:
            raise SocialError("invalid_file", "Upload a CSV within the configured size limit.")
        headers, rows = parse_social_posts(content, self._max_rows)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            existing = session.scalar(select(ImportJob).where(
                ImportJob.workspace_id == workspace_id, ImportJob.dedupe_key == dedupe_key,
            ))
            if existing is not None:
                if existing.kind != "social_posts":
                    raise SocialError("dedupe_conflict", "The retry key belongs to another import.")
                return self._import_payload(existing)
            job = ImportJob(
                workspace_id=workspace_id, created_by_user_id=principal.user_id,
                kind="social_posts", status="preview_ready",
                source_name=Path(filename).name[:255], dedupe_key=dedupe_key,
                preview={"provider": provider, "account_id": account_id.strip(),
                    "columns": headers, "rows": rows},
                checkpoint={"source_sha256": hashlib.sha256(content).hexdigest()},
            )
            session.add(job)
            session.flush()
            storage_key = f"workspaces/{workspace_id}/social-imports/{job.id}/source.csv"
            self._storage.put_bytes(storage_key, content)
            job.checkpoint = {**job.checkpoint, "storage_key": storage_key}
            self._audit(session, workspace_id, principal.user_id, "social.import_preview", job.id)
            return self._import_payload(job)

    @staticmethod
    def _import_payload(job: ImportJob) -> dict[str, Any]:
        return {
            "id": job.id, "status": job.status, "provider": job.preview["provider"],
            "account_id": job.preview["account_id"], "columns": job.preview["columns"],
            "rows": job.preview["rows"], "post_count": len(job.preview["rows"]),
        }

    def confirm_manual_import(
        self, principal: Principal, workspace_id: str, import_id: str,
    ) -> dict[str, Any]:
        self._accounts.require_permission(principal, workspace_id, "write")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            statement = select(ImportJob).where(
                ImportJob.workspace_id == workspace_id, ImportJob.id == import_id,
                ImportJob.kind == "social_posts",
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                statement = statement.with_for_update()
            job = session.scalar(statement)
            if job is None:
                raise SocialError("import_not_found", "Social import was not found.")
            if job.status == "confirmed":
                return {"id": job.id, "status": job.status, "posts_created": job.checkpoint["posts_created"]}
            created = 0
            for item in job.preview["rows"]:
                post = session.scalar(select(SocialPost).where(
                    SocialPost.workspace_id == workspace_id,
                    SocialPost.provider == job.preview["provider"],
                    SocialPost.account_id == job.preview["account_id"],
                    SocialPost.source_id == item["source_id"],
                ))
                if post is None:
                    post = SocialPost(
                        workspace_id=workspace_id,
                        provider=job.preview["provider"],
                        account_id=job.preview["account_id"],
                        source_id=item["source_id"],
                        provenance="owner_imported",
                    )
                    session.add(post)
                    created += 1
                post.text = item["text"] or ""
                post.source_url = item["source_url"]
                published = (
                    datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
                    if item["published_at"] else None
                )
                post.published_at = (
                    published.replace(tzinfo=timezone.utc)
                    if published is not None and published.tzinfo is None
                    else published
                )
                post.observed_at = utc_now()
                if item.get("engagement"):
                    from .engagement import save_snapshot
                    session.flush()
                    save_snapshot(session, workspace_id, post.id, item["engagement"], f"owner_import:{job.id}", "owner_supplied")
            job.status = "confirmed"
            job.completed_at = utc_now()
            job.checkpoint = {**job.checkpoint, "posts_created": created}
            self._audit(session, workspace_id, principal.user_id, "social.import_confirm", job.id)
            return {"id": job.id, "status": job.status, "posts_created": created}

    def list_posts(self, principal: Principal, workspace_id: str) -> list[dict[str, Any]]:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            posts = session.scalars(select(SocialPost).where(
                SocialPost.workspace_id == workspace_id,
            ).order_by(SocialPost.published_at.desc(), SocialPost.id).limit(200)).all()
            return [
                {"id": post.id, "provider": post.provider, "account_id": post.account_id,
                    "source_id": post.source_id, "text": post.text,
                    "published_at": post.published_at.isoformat() if post.published_at else None,
                    "provenance": post.provenance}
                for post in posts
            ]

    def export_posts_csv(self, principal: Principal, workspace_id: str) -> Iterator[bytes]:
        self._accounts.require_permission(principal, workspace_id, "read")

        def chunks() -> Iterator[bytes]:
            output = StringIO()
            writer = csv.writer(output, lineterminator="\r\n")
            writer.writerow(("provider", "account_id", "source_id", "text", "published_at", "source_url", "provenance"))
            yield b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
            output.seek(0)
            output.truncate(0)
            with self._sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                posts = session.scalars(select(SocialPost).where(
                    SocialPost.workspace_id == workspace_id,
                ).order_by(SocialPost.published_at, SocialPost.id).execution_options(yield_per=200))
                for post in posts:
                    writer.writerow((
                        _spreadsheet_cell(post.provider), _spreadsheet_cell(post.account_id),
                        _spreadsheet_cell(post.source_id), _spreadsheet_cell(post.text),
                        post.published_at.isoformat() if post.published_at else "",
                        post.source_url or "", _spreadsheet_cell(post.provenance),
                    ))
                    yield output.getvalue().encode("utf-8")
                    output.seek(0)
                    output.truncate(0)

        return chunks()

    def queue_sync(
        self, principal: Principal, workspace_id: str, connection_id: str, dedupe_key: str,
    ) -> dict[str, str]:
        self._accounts.require_permission(principal, workspace_id, "members")
        self._available()
        if not dedupe_key.strip() or len(dedupe_key) > 160:
            raise SocialError("invalid_dedupe_key", "The sync retry key is invalid.")
        unique_key = f"social:{workspace_id}:{_hash(connection_id + ':' + dedupe_key)}"
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._pending(session, workspace_id, connection_id)
            if row.status != "connected_partial" or not row.capabilities.get("posts"):
                raise SocialError("permission_missing", "This Page has no verified post-read capability.")
            existing = session.scalar(select(Job).where(
                Job.workspace_id == workspace_id, Job.dedupe_key == unique_key,
            ))
            if existing is not None:
                return {"job_id": existing.id, "status": existing.status}
            job = Job(
                workspace_id=workspace_id, created_by_user_id=principal.user_id,
                kind="social.meta.sync", payload={"connection_id": connection_id},
                dedupe_key=unique_key, max_attempts=3,
            )
            session.add(job)
            session.flush()
            self._audit(session, workspace_id, principal.user_id, "social.sync_queue", row.id)
            return {"job_id": job.id, "status": job.status}


class SocialSyncHandler:
    def __init__(
        self, sessions: sessionmaker[Session], store: JobStore, cipher: CredentialCipher,
        config: MetaConfig, *, offline: bool, transport: MetaTransport | None = None,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._cipher = cipher
        self._config = config
        self._offline = offline
        self._transport = transport or MetaGraphTransport(config)
        self._injected_transport = transport is not None

    def run(self, claim: JobClaim) -> None:
        if (claim.kind != "social.meta.sync" or not claim.workspace_id
            or not self._config.configured or (self._offline and not self._injected_transport)):
            raise SocialError("sync_unavailable", "Meta sync is unavailable.")
        workspace_id = claim.workspace_id
        connection_id = claim.payload.get("connection_id")
        if not isinstance(connection_id, str):
            raise SocialError("invalid_job", "Meta sync job is invalid.")
        cursor = claim.checkpoint.get("cursor")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 2000):
            raise SocialError("invalid_job", "Meta sync checkpoint is invalid.")
        pages_done = int(claim.checkpoint.get("pages_done", 0))
        for _ in range(30):
            with self._sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                connection = session.scalar(select(SocialConnection).where(
                    SocialConnection.workspace_id == workspace_id,
                    SocialConnection.id == connection_id,
                ))
                if (connection is None or connection.status not in {"connected_partial", "rate_limited"}
                    or not connection.capabilities.get("posts") or not connection.account_id
                    or not connection.account_credential_id):
                    raise SocialError("connection_unavailable", "The Page is no longer connected for post reads.")
                if connection.token_expires_at and connection.token_expires_at.replace(tzinfo=timezone.utc) <= utc_now():
                    connection.status = "needs_reauth"
                    raise SocialError("needs_reauth", "Meta authorization has expired.")
                credential = session.scalar(select(CredentialRecord).where(
                    CredentialRecord.workspace_id == workspace_id,
                    CredentialRecord.id == connection.account_credential_id,
                    CredentialRecord.provider == "meta_page",
                ))
                if credential is None:
                    raise SocialError("needs_reauth", "Meta credentials are unavailable.")
                token = self._cipher.decrypt(workspace_id, "meta_page", credential.ciphertext, credential.key_version)
                account_id = connection.account_id
                provider = "instagram" if connection.provider == "instagram" else "facebook_pages"
            rows, next_cursor = (self._transport.instagram_post_page(account_id, token, cursor)
                                 if provider == "instagram" else self._transport.post_page(account_id, token, cursor))
            with self._sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                statement = select(SocialConnection).where(
                    SocialConnection.workspace_id == workspace_id,
                    SocialConnection.id == connection_id,
                )
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    statement = statement.with_for_update()
                connection = session.scalar(statement)
                if connection is None or connection.status not in {"connected_partial", "rate_limited"} or connection.account_credential_id is None:
                    raise SocialError("connection_unavailable", "The Page was disconnected during sync.")
                for item in rows:
                    source_id = item.get("id")
                    if not isinstance(source_id, str) or not source_id or len(source_id) > 200:
                        raise SocialError("provider_malformed", "Meta returned an invalid post ID.")
                    message = item.get("message") or ""
                    if not isinstance(message, str) or len(message) > 20_000:
                        raise SocialError("provider_malformed", "Meta returned an invalid post message.")
                    raw_date = item.get("created_time")
                    try:
                        published = datetime.fromisoformat(raw_date.replace("Z", "+00:00")) if raw_date else None
                    except (ValueError, AttributeError) as exc:
                        raise SocialError("provider_malformed", "Meta returned an invalid post date.") from exc
                    if published is not None and published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    url = item.get("permalink_url")
                    if url is not None and (not isinstance(url, str) or len(url) > 2048 or urlparse(url).scheme != "https"):
                        raise SocialError("provider_malformed", "Meta returned an invalid post URL.")
                    post = session.scalar(select(SocialPost).where(
                        SocialPost.workspace_id == workspace_id,
                        SocialPost.provider == provider,
                        SocialPost.account_id == account_id,
                        SocialPost.source_id == source_id,
                    ))
                    if post is None:
                        post = SocialPost(
                            workspace_id=workspace_id, provider=provider,
                            account_id=account_id, source_id=source_id,
                        )
                        session.add(post)
                    post.text = message
                    post.published_at = published
                    post.source_url = url
                    post.provenance = "meta_api"
                    post.observed_at = utc_now()
                if not next_cursor:
                    connection.last_synced_at = utc_now()
                    connection.status = "connected_partial"
            pages_done += 1
            self._store.checkpoint(
                claim.id, claim.lease_owner,
                {"cursor": next_cursor, "pages_done": pages_done},
            )
            if not next_cursor:
                self._store.complete(claim.id, claim.lease_owner)
                return
            if next_cursor == cursor:
                raise SocialError("pagination_loop", "Meta repeated a post cursor.")
            cursor = next_cursor
            self._store.heartbeat(claim.id, claim.lease_owner)
        raise SocialError("pagination_limit", "Meta post sync exceeded the page limit.")

    def record_error(self, claim: JobClaim, code: str) -> None:
        if code not in {"needs_reauth", "permission_missing", "rate_limited"} or not claim.workspace_id:
            return
        with self._sessions() as session, session.begin():
            set_workspace_context(session, claim.workspace_id)
            connection = session.scalar(select(SocialConnection).where(
                SocialConnection.workspace_id == claim.workspace_id,
                SocialConnection.id == claim.payload.get("connection_id"),
            ))
            if connection is None or connection.status == "disconnected":
                return
            connection.status = code
            if code in {"needs_reauth", "permission_missing"}:
                connection.capabilities = {**connection.capabilities, "posts": False}
