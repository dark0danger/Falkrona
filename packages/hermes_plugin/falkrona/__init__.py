"""Register Falkrona's reviewed production Hermes tools."""

from .schemas import BRAND_CONTEXT_SCHEMA, STORE_ARTIFACT_SCHEMA
from .tools import get_brand_context, store_artifact


def register(ctx):
    ctx.register_tool(
        name="falkrona_get_brand_context",
        toolset="falkrona",
        schema=BRAND_CONTEXT_SCHEMA,
        handler=get_brand_context,
    )
    ctx.register_tool(
        name="falkrona_store_artifact",
        toolset="falkrona",
        schema=STORE_ARTIFACT_SCHEMA,
        handler=store_artifact,
    )
