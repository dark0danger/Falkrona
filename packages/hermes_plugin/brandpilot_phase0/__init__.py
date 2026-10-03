"""Hermes registration for the Phase 0 BrandPilot probe."""

from .schemas import PROBE_SCHEMA
from .tools import probe


def register(ctx):
    ctx.register_tool(
        name="brandpilot_phase0_probe",
        toolset="brandpilot",
        schema=PROBE_SCHEMA,
        handler=probe,
    )
