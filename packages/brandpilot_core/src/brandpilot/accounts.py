"""Server-side identity, session, membership, and workspace data services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from .database import set_workspace_context
from .models import (
    AppSession,
    AuditEvent,
    AuthAttempt,
    CredentialRecord,
    Job,
    User,
    Workspace,
    WorkspaceAsset,
    WorkspaceMembership,
)
from .security import CredentialCipher, PasswordManager, token_hash


ROLES = {"owner", "editor", "analyst"}
ROLE_PERMISSIONS = {
    "owner": frozenset({"read", "write", "approve", "publish", "members"}),
    "editor": frozenset({"read", "write", "approve"}),
    "analyst": frozenset({"read"}),
}


class AuthenticationError(ValueError):
    pass


class RateLimitError(AuthenticationError):
    pass


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    email: str
    session_id: str


@dataclass(frozen=True, slots=True)
class SessionGrant:
    principal: Principal
    token: str
    csrf_token: str
    expires_at: datetime


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current if current.tzinfo else current.replace(tzinfo=timezone.utc)


def normalize_email(email: str) -> str:
    value = email.strip().casefold()
    if "@" not in value or len(value) > 320:
        raise ValueError("A valid email address is required")
    return value


class AccountService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        app_secret_key: bytes,
        credential_cipher: CredentialCipher,
        session_ttl_seconds: int = 43200,
        login_window_seconds: int = 300,
        login_max_attempts: int = 5,
    ) -> None:
        self._sessions = sessions
        self._passwords = PasswordManager()
        self._app_secret = app_secret_key
        self._cipher = credential_cipher
        self._session_ttl = session_ttl_seconds
        self._login_window = login_window_seconds
        self._login_max = login_max_attempts

    def setup_owner(
        self,
        email: str,
        password: str,
        workspace_name: str,
        *,
        supplied_token: str,
        expected_token: str,
    ) -> tuple[str, str]:
        if not hmac.compare_digest(supplied_token, expected_token):
            raise AuthorizationError("Owner setup token is invalid")
        normalized = normalize_email(email)
        if not workspace_name.strip():
            raise ValueError("Workspace name is required")
        with self._sessions() as session, session.begin():
            if session.scalar(select(func.count()).select_from(User)):
                raise AuthorizationError("Owner setup has already completed")
            user = User(email=normalized, password_hash=self._passwords.hash(password))
            workspace = Workspace(name=workspace_name.strip())
            session.add_all([user, workspace])
            session.flush()
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id, user_id=user.id, role="owner"
                )
            )
            return user.id, workspace.id

    def create_user(self, email: str, password: str) -> str:
        user = User(
            email=normalize_email(email), password_hash=self._passwords.hash(password)
        )
        with self._sessions() as session, session.begin():
            session.add(user)
            session.flush()
            return user.id

    def login(
        self,
        email: str,
        password: str,
        client_id: str,
        *,
        now: datetime | None = None,
    ) -> SessionGrant:
        current = _utc(now)
        normalized = normalize_email(email)
        bucket = hmac.new(
            self._app_secret,
            f"{normalized}|{client_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        cutoff = current - timedelta(seconds=self._login_window)
        with self._sessions() as session:
            failures = session.scalar(
                select(func.count())
                .select_from(AuthAttempt)
                .where(AuthAttempt.bucket == bucket, AuthAttempt.created_at >= cutoff)
            )
            if failures >= self._login_max:
                raise RateLimitError("Too many login attempts")
            user = session.scalar(select(User).where(User.email == normalized))
            if not self._passwords.verify(user.password_hash if user else None, password):
                session.add(AuthAttempt(bucket=bucket, created_at=current))
                session.commit()
                raise AuthenticationError("Email or password is incorrect")
            session.execute(delete(AuthAttempt).where(AuthAttempt.bucket == bucket))
            raw_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            expires_at = current + timedelta(seconds=self._session_ttl)
            record = AppSession(
                user_id=user.id,
                token_hash=token_hash(raw_token),
                csrf_hash=token_hash(csrf_token),
                expires_at=expires_at,
            )
            session.add(record)
            session.flush()
            grant = SessionGrant(
                Principal(user.id, user.email, record.id),
                raw_token,
                csrf_token,
                expires_at,
            )
            session.commit()
            return grant

    def authenticate(
        self, raw_token: str | None, *, now: datetime | None = None
    ) -> Principal:
        if not raw_token:
            raise AuthenticationError("Authentication is required")
        current = _utc(now)
        with self._sessions() as session:
            row = session.execute(
                select(AppSession, User)
                .join(User, User.id == AppSession.user_id)
                .where(AppSession.token_hash == token_hash(raw_token))
            ).one_or_none()
            if row is None:
                raise AuthenticationError("Session is invalid")
            record, user = row
            expires_at = _utc(record.expires_at)
            if record.revoked_at is not None or expires_at <= current:
                raise AuthenticationError("Session has expired or was revoked")
            return Principal(user.id, user.email, record.id)

    def require_csrf(self, principal: Principal, supplied_token: str | None) -> None:
        if not supplied_token:
            raise AuthorizationError("CSRF token is required")
        with self._sessions() as session:
            record = session.get(AppSession, principal.session_id)
            if record is None or not hmac.compare_digest(
                record.csrf_hash, token_hash(supplied_token)
            ):
                raise AuthorizationError("CSRF token is invalid")

    def rotate_csrf(self, principal: Principal) -> str:
        csrf_token = secrets.token_urlsafe(32)
        with self._sessions() as session, session.begin():
            record = session.get(AppSession, principal.session_id)
            if record is None or record.revoked_at is not None:
                raise AuthenticationError("Session is invalid")
            record.csrf_hash = token_hash(csrf_token)
        return csrf_token

    def revoke_session(self, principal: Principal) -> None:
        with self._sessions() as session, session.begin():
            record = session.get(AppSession, principal.session_id)
            if record is not None:
                record.revoked_at = _utc()

    def memberships(self, principal: Principal) -> list[dict[str, str]]:
        with self._sessions() as session:
            rows = session.execute(
                select(WorkspaceMembership, Workspace)
                .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
                .where(
                    WorkspaceMembership.user_id == principal.user_id,
                    WorkspaceMembership.revoked_at.is_(None),
                )
                .order_by(Workspace.name, Workspace.id)
            ).all()
            return [
                {"workspace_id": member.workspace_id, "name": workspace.name, "role": member.role}
                for member, workspace in rows
            ]

    def create_workspace(self, principal: Principal, name: str) -> str:
        if not name.strip():
            raise ValueError("Workspace name is required")
        with self._sessions() as session, session.begin():
            workspace = Workspace(name=name.strip())
            session.add(workspace)
            session.flush()
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=principal.user_id,
                    role="owner",
                )
            )
            return workspace.id

    def require_permission(
        self, principal: Principal, workspace_id: str, permission: str
    ) -> str:
        with self._sessions() as session:
            member = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == principal.user_id,
                    WorkspaceMembership.revoked_at.is_(None),
                )
            )
            if member is None or permission not in ROLE_PERMISSIONS.get(member.role, ()):
                raise AuthorizationError("Workspace access is denied")
            return member.role

    def add_member(
        self,
        principal: Principal,
        workspace_id: str,
        email: str,
        role: str,
    ) -> str:
        self.require_permission(principal, workspace_id, "members")
        if role not in ROLES:
            raise ValueError("Role must be owner, editor, or analyst")
        with self._sessions() as session, session.begin():
            user = session.scalar(select(User).where(User.email == normalize_email(email)))
            if user is None:
                raise ValueError("User must exist before membership is granted")
            member = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == user.id,
                )
            )
            if member is None:
                member = WorkspaceMembership(
                    workspace_id=workspace_id, user_id=user.id, role=role
                )
                session.add(member)
            else:
                member.role = role
                member.revoked_at = None
            session.flush()
            self._audit(session, workspace_id, principal.user_id, "member.grant", "membership", member.id)
            return member.id

    def revoke_member(
        self, principal: Principal, workspace_id: str, membership_id: str
    ) -> None:
        self.require_permission(principal, workspace_id, "members")
        with self._sessions() as session, session.begin():
            member = session.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.id == membership_id,
                    WorkspaceMembership.workspace_id == workspace_id,
                )
            )
            if member is None:
                raise ValueError("Membership was not found")
            member.revoked_at = _utc()
            self._audit(session, workspace_id, principal.user_id, "member.revoke", "membership", member.id)

    def store_credential(
        self, principal: Principal, workspace_id: str, provider: str, secret: str
    ) -> str:
        self.require_permission(principal, workspace_id, "write")
        ciphertext, version = self._cipher.encrypt(workspace_id, provider, secret)
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            record = CredentialRecord(
                workspace_id=workspace_id,
                provider=provider,
                ciphertext=ciphertext,
                key_version=version,
            )
            session.add(record)
            session.flush()
            self._audit(session, workspace_id, principal.user_id, "credential.store", "credential", record.id)
            return record.id

    def decrypt_credential(self, workspace_id: str, credential_id: str) -> str:
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            record = session.scalar(
                select(CredentialRecord).where(CredentialRecord.id == credential_id)
            )
            if record is None:
                raise AuthorizationError("Credential is outside the workspace scope")
            return self._cipher.decrypt(
                workspace_id, record.provider, record.ciphertext, record.key_version
            )

    def get_asset(
        self, principal: Principal, workspace_id: str, asset_id: str
    ) -> WorkspaceAsset:
        self.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            asset = session.scalar(
                select(WorkspaceAsset).where(
                    WorkspaceAsset.id == asset_id,
                    WorkspaceAsset.workspace_id == workspace_id,
                )
            )
            if asset is None:
                raise AuthorizationError("Asset is outside the workspace scope")
            session.expunge(asset)
            return asset

    def register_asset(
        self,
        workspace_id: str,
        storage_key: str,
        original_name: str,
        mime_type: str,
        sha256: str,
        size: int,
    ) -> str:
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            asset = WorkspaceAsset(
                workspace_id=workspace_id,
                storage_key=storage_key,
                original_name=original_name,
                mime_type=mime_type,
                sha256=sha256,
                size=size,
            )
            session.add(asset)
            session.flush()
            return asset.id

    def validate_tool_job(self, workspace_id: str, job_id: str) -> None:
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            job = session.scalar(
                select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id)
            )
            if job is None:
                raise AuthorizationError("Job is outside the workspace scope")

    @staticmethod
    def _audit(
        session: Session,
        workspace_id: str,
        actor_user_id: str,
        action: str,
        target_type: str,
        target_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        set_workspace_context(session, workspace_id)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
            )
        )
