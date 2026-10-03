"""Validated application settings with offline-safe defaults."""

from __future__ import annotations

from dataclasses import dataclass
import base64
from pathlib import Path
import re
from typing import Mapping
import os
from urllib.parse import urlparse

from .config import RuntimeConfig


class ConfigurationError(ValueError):
    """A startup setting is absent or unsafe."""


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_url: str
    storage_root: Path
    runtime: RuntimeConfig
    app_secret_key: bytes = b"test-only-app-secret-key-32-bytes"
    credential_encryption_key: bytes = b"0123456789abcdef0123456789abcdef"
    owner_setup_token: str = "test-only-setup-token"
    session_cookie_secure: bool = True
    session_ttl_seconds: int = 43200
    login_window_seconds: int = 300
    login_max_attempts: int = 5
    worker_workspace_id: str | None = None
    max_upload_bytes: int = 10_000_000
    max_archive_bytes: int = 50_000_000
    max_import_rows: int = 5_000
    job_lease_seconds: int = 30
    worker_poll_seconds: int = 2
    gemini_model: str = ""
    gemini_api_key: str = ""
    hermes_python: str = ""
    openai_model: str = ""
    agent_max_model_calls: int = 12
    agent_max_input_tokens: int = 24_000
    agent_max_output_tokens: int = 12_000
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_callback_url: str = ""
    meta_graph_version: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AppSettings":
        values = os.environ if environ is None else environ
        database_url = values.get("BRANDPILOT_DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigurationError("BRANDPILOT_DATABASE_URL is required")
        storage_value = values.get("BRANDPILOT_STORAGE_ROOT", "").strip()
        if not storage_value:
            raise ConfigurationError("BRANDPILOT_STORAGE_ROOT is required")
        storage_root = Path(storage_value).expanduser().resolve()
        runtime = RuntimeConfig.from_env(values)
        app_secret = values.get("BRANDPILOT_APP_SECRET_KEY", "").encode("utf-8")
        if len(app_secret) < 32:
            raise ConfigurationError(
                "BRANDPILOT_APP_SECRET_KEY must contain at least 32 bytes"
            )
        encryption_value = values.get("BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY", "")
        try:
            encryption_key = base64.urlsafe_b64decode(encryption_value.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ConfigurationError(
                "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(encryption_key) != 32:
            raise ConfigurationError(
                "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        owner_setup_token = values.get("BRANDPILOT_OWNER_SETUP_TOKEN", "").strip()
        if len(owner_setup_token) < 20:
            raise ConfigurationError(
                "BRANDPILOT_OWNER_SETUP_TOKEN must contain at least 20 characters"
            )
        log_level = values.get("BRANDPILOT_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("BRANDPILOT_LOG_LEVEL is invalid")
        meta_app_id = values.get("BRANDPILOT_META_APP_ID", "").strip()
        meta_app_secret = values.get("BRANDPILOT_META_APP_SECRET", "").strip()
        meta_callback_url = values.get("BRANDPILOT_META_CALLBACK_URL", "").strip()
        meta_graph_version = values.get("BRANDPILOT_META_GRAPH_VERSION", "").strip()
        session_cookie_secure = values.get(
            "BRANDPILOT_SESSION_COOKIE_SECURE", "true"
        ).strip().lower() == "true"
        if any((meta_app_id, meta_app_secret, meta_callback_url, meta_graph_version)):
            if not all((meta_app_id, meta_app_secret, meta_callback_url, meta_graph_version)):
                raise ConfigurationError("Meta configuration requires app ID, secret, callback URL and Graph version")
            callback = urlparse(meta_callback_url)
            if (
                callback.scheme not in {"http", "https"}
                or not callback.hostname
                or (callback.scheme == "http" and callback.hostname not in {"127.0.0.1", "localhost"})
                or callback.path != "/api/v1/social/meta/callback"
                or callback.username or callback.password or callback.query or callback.fragment
                or not re.fullmatch(r"v[0-9]+\.0", meta_graph_version)
            ):
                raise ConfigurationError("Meta callback URL or Graph version is invalid")
            if callback.scheme == "https" and not session_cookie_secure:
                raise ConfigurationError(
                    "HTTPS Meta callback requires BRANDPILOT_SESSION_COOKIE_SECURE=true"
                )
        return cls(
            database_url=database_url,
            storage_root=storage_root,
            runtime=runtime,
            app_secret_key=app_secret,
            credential_encryption_key=encryption_key,
            owner_setup_token=owner_setup_token,
            session_cookie_secure=session_cookie_secure,
            session_ttl_seconds=_positive_int(
                values, "BRANDPILOT_SESSION_TTL_SECONDS", 43200
            ),
            login_window_seconds=_positive_int(
                values, "BRANDPILOT_LOGIN_WINDOW_SECONDS", 300
            ),
            login_max_attempts=_positive_int(
                values, "BRANDPILOT_LOGIN_MAX_ATTEMPTS", 5
            ),
            worker_workspace_id=values.get("BRANDPILOT_WORKSPACE_ID", "").strip()
            or None,
            max_upload_bytes=_positive_int(values, "BRANDPILOT_MAX_UPLOAD_BYTES", 10_000_000),
            max_archive_bytes=_positive_int(values, "BRANDPILOT_MAX_ARCHIVE_BYTES", 50_000_000),
            max_import_rows=_positive_int(values, "BRANDPILOT_MAX_IMPORT_ROWS", 5_000),
            job_lease_seconds=_positive_int(
                values, "BRANDPILOT_JOB_LEASE_SECONDS", 30
            ),
            worker_poll_seconds=_positive_int(
                values, "BRANDPILOT_WORKER_POLL_SECONDS", 2
            ),
            gemini_model=values.get("BRANDPILOT_GEMINI_MODEL", "").strip(),
            gemini_api_key=values.get("GEMINI_API_KEY", "").strip() or values.get("GOOGLE_API_KEY", "").strip(),
            hermes_python=values.get("BRANDPILOT_HERMES_PYTHON", "").strip(),
            openai_model=values.get("BRANDPILOT_OPENAI_MODEL", "").strip(),
            agent_max_model_calls=_positive_int(values, "BRANDPILOT_AGENT_MAX_MODEL_CALLS", 12),
            agent_max_input_tokens=_positive_int(values, "BRANDPILOT_AGENT_MAX_INPUT_TOKENS", 24_000),
            agent_max_output_tokens=_positive_int(values, "BRANDPILOT_AGENT_MAX_OUTPUT_TOKENS", 12_000),
            meta_app_id=meta_app_id,
            meta_app_secret=meta_app_secret,
            meta_callback_url=meta_callback_url,
            meta_graph_version=meta_graph_version,
            log_level=log_level,
        )
