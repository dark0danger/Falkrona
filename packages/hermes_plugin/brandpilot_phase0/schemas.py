"""Model-facing schemas for the Phase 0 probe."""

PROBE_SCHEMA = {
    "name": "brandpilot_phase0_probe",
    "description": "Return a deterministic structured BrandPilot integration probe.",
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "A short marker to echo in the structured result.",
                "maxLength": 128,
            }
        },
        "required": ["message"],
        "additionalProperties": False,
    },
}
