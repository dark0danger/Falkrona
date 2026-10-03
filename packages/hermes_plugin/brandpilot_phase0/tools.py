"""Deterministic tool handler for the real Hermes integration spike."""

from __future__ import annotations

import json


def probe(args: dict, **_kwargs) -> str:
    try:
        message = args.get("message", "")
        if not isinstance(message, str) or not message.strip():
            return json.dumps({"error": "message is required"})
        if len(message) > 128:
            return json.dumps({"error": "message is too long"})
        return json.dumps(
            {
                "schema_version": 1,
                "plugin": "brandpilot-phase0",
                "echo": message,
                "status": "ok",
            },
            sort_keys=True,
        )
    except Exception as exc:  # Hermes handlers return typed JSON errors.
        return json.dumps({"error": f"probe failed: {exc}"})
