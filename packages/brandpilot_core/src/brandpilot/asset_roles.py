"""Upload purposes, including evidence from uploads made before purpose was saved."""
from sqlalchemy import select

from .models import AgentRun, BrandingSetup, WorkspaceAsset


def upload_roles(session, workspace):
    roles = {}
    for checkpoint in session.scalars(select(AgentRun.checkpoint).where(AgentRun.workspace_id == workspace)):
        for visual in checkpoint.get("visual_assets", []):
            if visual.get("role") in {"logo", "reference"}:
                roles[visual["id"]] = visual["role"]
    brand = session.scalar(select(BrandingSetup).where(BrandingSetup.workspace_id == workspace))
    if brand:
        roles[brand.logo_asset_id] = "logo"
        roles[brand.reference_asset_id] = "reference"
    for asset in session.scalars(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace)):
        if asset.metadata_json.get("purpose"):
            roles[asset.id] = asset.metadata_json["purpose"]
        if asset.metadata_json.get("verified_transparent_logo"):
            roles[asset.id] = "logo"
    if brand:
        roles[brand.logo_asset_id] = "logo"
        roles[brand.reference_asset_id] = "reference"
    return roles


def asset_purpose(asset, roles=None):
    if asset.source != "upload":
        return "design" if asset.source in {"external_generation", "local_composition", "gemini_image"} else "other"
    return (roles or {}).get(asset.id) or asset.metadata_json.get("purpose") or (
        "logo" if asset.metadata_json.get("verified_transparent_logo") else
        "product" if asset.mime_type.startswith("image/") else "document")
