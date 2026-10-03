"""The production plugin has no shell, filesystem, browser, or network tools."""

from __future__ import annotations

import json
import os
from urllib import error, request


def _call(path: str, payload: dict) -> str:
    base_url = os.environ.get("FALKRONA_APP_URL", "").rstrip("/")
    credential = os.environ.get("FALKRONA_RUN_CREDENTIAL", "")
    workspace_id = os.environ.get("FALKRONA_WORKSPACE_ID", "")
    job_id = os.environ.get("FALKRONA_JOB_ID", "")
    if not base_url or not credential or not workspace_id or not job_id:
        return json.dumps({"error": "Falkrona run scope is not configured."})
    data = json.dumps({"workspace_id": workspace_id, "job_id": job_id, **payload}).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {credential}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        return json.dumps({"error": "Falkrona app tool rejected the request.", "status": exc.code})
    except (OSError, TimeoutError):
        return json.dumps({"error": "Falkrona app tool is unavailable."})


def get_brand_context(args: dict, **_kwargs) -> str:
    if args:
        return json.dumps({"error": "get_brand_context does not accept arguments."})
    return _call("/internal/v1/agent-tools/brand-context", {})


def store_artifact(args: dict, **_kwargs) -> str:
    if not isinstance(args, dict):
        return json.dumps({"error": "Artifact arguments must be an object."})
    title = args.get("title")
    content = args.get("content")
    if not isinstance(title, str) or not isinstance(content, str):
        return json.dumps({"error": "Artifact title and content are required."})
    return _call("/internal/v1/agent-tools/artifacts", {"title": title, "content": content})
