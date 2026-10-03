BRAND_CONTEXT_SCHEMA = {
    "name": "falkrona_get_brand_context",
    "description": "Read the confirmed brand profile for this run's workspace.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}

STORE_ARTIFACT_SCHEMA = {
    "name": "falkrona_store_artifact",
    "description": "Store a short, plain-text run artifact in the current workspace.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 120},
            "content": {"type": "string", "maxLength": 20000},
        },
        "required": ["title", "content"],
        "additionalProperties": False,
    },
}
