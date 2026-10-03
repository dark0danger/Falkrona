"""Read-only check of one workspace's existing Facebook grants and Page access.

Uses server-side encrypted credentials. Prints only permission names, Page tasks
and capability outcomes, never credentials. Does not request new scopes or publish.
"""
from __future__ import annotations

import argparse
from datetime import timezone
import json
import os
from pathlib import Path
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from brandpilot.database import build_engine, set_workspace_context
from brandpilot.models import CredentialRecord, SocialConnection, SocialPost, utc_now
from brandpilot.security import CredentialCipher
from brandpilot.settings import AppSettings
from brandpilot.social import MetaConfig, MetaGraphTransport, SocialError


def check(workspace_id: str, settings: AppSettings) -> dict:
    config = MetaConfig(settings.meta_app_id, settings.meta_app_secret,
                        settings.meta_callback_url, settings.meta_graph_version)
    if not config.configured or settings.runtime.execution_mode.value == "offline_test":
        return {"status": "external_disabled", "published": False}
    cipher = CredentialCipher({1: settings.credential_encryption_key}, current_version=1)
    transport = MetaGraphTransport(config)
    engine = build_engine(settings.database_url, role="brandpilot_app")
    results = []
    try:
        with Session(engine) as session, session.begin():
            if engine.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
            set_workspace_context(session, workspace_id)
            connections = session.scalars(select(SocialConnection).where(
                SocialConnection.workspace_id == workspace_id,
                SocialConnection.provider.in_(["meta", "facebook_pages"]),
                SocialConnection.account_id.is_not(None),
                SocialConnection.status.in_(["connected", "connected_partial"]),
            )).all()
            for connection in connections:
                result = {"account_name": connection.account_name,
                          "stored_scopes": connection.granted_scopes,
                          "app_publish_enabled": bool(connection.capabilities.get("publish")),
                          "live_publisher_implemented": True, "published": False}
                results.append(result)
                if (not connection.token_expires_at or
                        connection.token_expires_at.replace(tzinfo=timezone.utc) <= utc_now()):
                    result["status"] = "needs_reauth"
                    continue
                def credential(record_id: str | None, provider: str) -> str:
                    record = session.scalar(select(CredentialRecord).where(
                        CredentialRecord.workspace_id == workspace_id,
                        CredentialRecord.id == record_id,
                        CredentialRecord.provider == provider))
                    if record is None:
                        raise SocialError("needs_reauth", "Credential unavailable.")
                    return cipher.decrypt(workspace_id, provider, record.ciphertext, record.key_version)
                try:
                    user_token = credential(connection.user_credential_id, "meta_user")
                    page_token = credential(connection.account_credential_id, "meta_page")
                    scopes = transport.granted_permissions(user_token)
                    result["current_scopes"] = sorted(scopes)
                    result["publish_scope_granted"] = "pages_manage_posts" in scopes
                    pages = transport.managed_pages(user_token)
                    selected = next((page for page in pages if page.get("id") == connection.account_id), None)
                    tasks = selected.get("tasks", []) if selected else []
                    result["selected_page_managed"] = selected is not None
                    result["page_tasks"] = tasks
                    result["content_task_available"] = bool(set(tasks).intersection({
                        "CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT",
                        "PROFILE_PLUS_MANAGE", "PROFILE_PLUS_FULL_CONTROL"}))
                    result["post_read_verified"] = transport.probe_posts(connection.account_id, page_token)
                    post = session.scalar(select(SocialPost).where(
                        SocialPost.workspace_id == workspace_id,
                        SocialPost.provider == "facebook_pages",
                        SocialPost.account_id == connection.account_id,
                        SocialPost.provenance == "meta_api",
                    ).order_by(SocialPost.published_at.desc()).limit(1))
                    if post:
                        try:
                            counts = transport.post_engagement("facebook_pages", post.source_id, page_token)
                            result["engagement_status"] = "verified" if any(v is not None for v in counts.values()) else "unavailable"
                            result["measured_fields"] = sorted(k for k, v in counts.items() if v is not None)
                        except SocialError as exc:
                            result["engagement_status"] = exc.code
                    else:
                        result["engagement_status"] = "no_imported_post"
                    result["status"] = "checked"
                except SocialError as exc:
                    result["status"] = exc.code
        return {"checked_at": utc_now().isoformat(), "graph_version": config.graph_version,
                "connections": results, "published": False}
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True, type=lambda value: str(uuid.UUID(value)))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    values = dict(os.environ)
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    try:
        result = check(args.workspace_id, AppSettings.from_env(values))
    except Exception:
        # Exceptions from transports/configuration must never expose secret values.
        print(json.dumps({"status": "check_failed", "published": False}))
        return 1
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
