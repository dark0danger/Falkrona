"""Consent-bound image-app handoff and atomic draft import. No account credentials."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from .creative import CreativeError, _layer, validate_scene
from .database import set_workspace_context
from .design_direction import DesignDirection, context_snapshot
from .models import AgentRun, DesignVersion, WorkspaceAsset

PROVIDERS = {"gemini": "https://gemini.google.com/app", "chatgpt": "https://chatgpt.com/"}


class BrowserImageService:
    def __init__(self, sessions, accounts, storage, creative):
        self.sessions, self.accounts, self.storage, self.creative = sessions, accounts, storage, creative

    def _run(self, session, workspace, run_id):
        row = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace,
            AgentRun.id == run_id).with_for_update())
        if not row or row.status != "completed" or row.cancel_requested or row.checkpoint.get("pipeline_version") not in {4, 5}:
            raise CreativeError("direction_unavailable", "Prepare this design's Gemini direction first.")
        return row

    def _current(self, session, workspace, row):
        _, digest = context_snapshot(session, workspace, row.checkpoint["design_id"], row.checkpoint["inputs"], self.storage)
        if digest != row.checkpoint.get("context_digest"):
            raise CreativeError("direction_stale", "Your brand, brief or images changed. Prepare a new direction.")

    def packet(self, principal, workspace, run_id, provider, consent):
        self.accounts.require_permission(principal, workspace, "write")
        if provider not in PROVIDERS or not consent:
            raise CreativeError("image_app_consent_required", "Allow the selected image app to receive your brand details and images.")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            row = self._run(session, workspace, run_id)
            self._current(session, workspace, row)
            if row.output.get("imported_design_id"):
                raise CreativeError("image_already_imported", "This request already has a saved image. Create a new version to generate again.")
            direction = DesignDirection.model_validate(row.output["direction"])
            handoff = row.checkpoint.get("browser_handoff")
            now = datetime.now(timezone.utc)
            if handoff and datetime.fromisoformat(handoff["expires_at"]) > now:
                if handoff["provider"] != provider or handoff["user_id"] != principal.user_id:
                    raise CreativeError("handoff_in_progress", "Finish the current image-app request before changing services.")
            else:
                handoff = {"nonce": secrets.token_urlsafe(32), "provider": provider,
                    "user_id": principal.user_id, "expires_at": (now + timedelta(minutes=30)).isoformat()}
                row.checkpoint = {**row.checkpoint, "browser_handoff": handoff}
            attachments = []
            for visual in row.checkpoint["visual_assets"]:
                asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace,
                    WorkspaceAsset.id == visual["id"], WorkspaceAsset.status == "ready", WorkspaceAsset.source == "upload"))
                if not asset or asset.sha256 != visual["sha256"]:
                    raise CreativeError("asset_changed", "Upload the current brand images again.")
                content = self.storage.read_bytes(asset.storage_key)
                if hashlib.sha256(content).hexdigest() != asset.sha256:
                    raise CreativeError("asset_changed", "A saved image changed. Upload it again.")
                # Strip metadata without changing subject pixels, and bound transfer size.
                with Image.open(BytesIO(content)) as source:
                    image = ImageOps.exif_transpose(source).convert("RGBA")
                    image.thumbnail((2048, 2048)); image.info.clear()
                    stream = BytesIO(); image.save(stream, "PNG")
                attachments.append({"role": visual["role"], "name": f"{len(attachments)+1}-{visual['role']}.png",
                    "mime_type": "image/png", "data": base64.b64encode(stream.getvalue()).decode("ascii")})
            prompt = ("Generate ONE finished advertising image, portrait 4:5 (1080x1350). "
                "Use your image-generation tool, not a textual description. Attachment 1 = exact brand logo; "
                "attachment 2 = product identity ONLY, discard its background and composition; "
                "attachment 3 if present = optional style reference ONLY. Preserve the real product and logo.\n\n"
                + direction.image_prompt + f"\nExact headline: {direction.headline}\nExact CTA: {direction.cta}\n"
                + f"Language: {direction.language}. No additional invented text or claims.")
            if direction.language == "ar":
                prompt += ("\nAll advertising copy must be Arabic, with joined letters and correct right-to-left reading order. "
                    "Use an Arabic-capable font that matches the brand's typography. Preserve original logo and product-label lettering.")
            else:
                prompt += "\nAll advertising copy must be English with left-to-right reading order. Preserve original logo and product-label lettering."
            if row.checkpoint.get("pipeline_version") == 5:
                import json
                campaign = row.checkpoint.get("campaign", {})
                peers = [{"title": post["title"], **{key: str((post.get("visual_concept") or {}).get(key, ""))[:180]
                         for key in ("route", "camera", "composition", "visual_hook")}}
                         for post in campaign.get("other_posts", [])]
                observation = direction.product_observation
                if observation is None:
                    raise CreativeError("product_identity_missing", "Prepare a new direction that separates the product from its scenery.")
                prompt += ("\n\nMANDATORY VISUAL CONTRACT — applies to the entire image above:\n"
                    "Make a new photograph/composition. Extract or recreate ONLY the physical product from attachment 2; "
                    "do not reuse that photo, its backdrop, props, surface, crop, lighting arrangement or scene with added text. "
                    "The supplied image is an identity sheet, never a layout template.\n"
                    "Show the actual packaged product prominently with its real label visible. A generic drink or serving glass "
                    "must not replace it. In a human-moment scene, the person can hold the actual bottle/container, or the "
                    "real packaged product must be clearly visible beside any serving glass.\n"
                    "Product identity to preserve: " + observation.identity
                    + "\nSource-photo elements to discard: " + json.dumps(observation.source_scene_to_discard, ensure_ascii=False)
                    + "\nShared brand treatment: " + json.dumps(campaign.get("visual_identity"), ensure_ascii=False)
                    + "\nTHIS post's scene and composition (chosen before the product photo was inspected): "
                    + json.dumps(campaign.get("selected_visual_concept"), ensure_ascii=False)
                    + "\nOther posts' ideas — do not repeat these compositions: " + json.dumps(peers, ensure_ascii=False)
                    + "\nKeep the brand's palette, type family, weights, type scale and logo treatment consistent. "
                    "Change the actual scene, focal action, camera or spatial arrangement. Changing only words, fruit positions "
                    "or crop does not count as a new idea. The optional reference supplies visual character, not a scene to duplicate.")
            from .brand_treatment import cta_instruction
            treatment = row.checkpoint.get("campaign", {}).get("visual_identity", {}).get("cta_treatment")
            if treatment:
                prompt += "\n\n" + cta_instruction(treatment)
            return {"run_id": row.id, "design_id": row.checkpoint["design_id"], "workspace_id": workspace,
                "provider": provider, "url": PROVIDERS[provider], "nonce": handoff["nonce"],
                "expires_at": handoff["expires_at"], "prompt": prompt, "attachments": attachments}

    def import_image(self, principal, workspace, run_id, provider, nonce, content):
        self.accounts.require_permission(principal, workspace, "write")
        if not content or len(content) > 15_000_000:
            raise CreativeError("invalid_image", "Choose a generated PNG, JPEG or WebP under 15 MB.")
        input_digest = hashlib.sha256(content).hexdigest()
        try:
            with Image.open(BytesIO(content)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                    raise ValueError()
                width, height = source.size
                if width < 400 or height < 500 or width * height > 20_000_000 or abs(width / height - .8) > .015:
                    raise ValueError()
                image = ImageOps.exif_transpose(source)
                if abs(image.width / image.height - .8) > .015:
                    raise ValueError()
                image = image.convert("RGB")
                # Size normalization only: never overlay text/logo or synthesize composition.
                image = image.resize((1080, 1350), Image.Resampling.LANCZOS); image.info.clear()
                stream = BytesIO(); image.save(stream, "PNG"); png = stream.getvalue()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
            raise CreativeError("invalid_image", "Use a single portrait 4:5 generated image, at least 400 × 500 pixels.") from None
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            row = self._run(session, workspace, run_id)
            handoff = row.checkpoint.get("browser_handoff", {})
            if (provider != handoff.get("provider") or handoff.get("user_id") != principal.user_id
                or not hmac.compare_digest(str(nonce), str(handoff.get("nonce", "")))):
                raise CreativeError("invalid_handoff", "This image does not belong to your generation request.")
            if row.output.get("imported_design_id"):
                if input_digest != row.output.get("import_sha256"):
                    raise CreativeError("image_already_imported", "This request already has a different image. Create a new version.")
                saved = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace,
                    DesignVersion.id == row.output["imported_design_id"]))
                return self.creative._payload(saved)
            if datetime.fromisoformat(handoff["expires_at"]) <= datetime.now(timezone.utc):
                raise CreativeError("handoff_expired", "Reopen this saved direction before importing the image.")
            # Lock the parent before checking latest revision (serializes concurrent imports).
            parent = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace,
                DesignVersion.id == row.checkpoint["design_id"]).with_for_update())
            self._current(session, workspace, row)
            direction = DesignDirection.model_validate(row.output["direction"]).model_dump()
            digest = hashlib.sha256(png).hexdigest()
            key = f"workspaces/{workspace}/agent-runs/{run_id}/external-{digest}.png"
            self.storage.put_bytes(key, png)
            asset = WorkspaceAsset(workspace_id=workspace, storage_key=key, original_name="Generated ad.png",
                mime_type="image/png", sha256=digest, size=len(png), width=1080, height=1350,
                asset_type="image", source="external_generation", metadata_json={"agent_run_id": row.id,
                    "image_app": provider, "role": "complete_ad", "product_identity_review_required": True})
            session.add(asset); session.flush()
            # Complete artwork: compatibility layers contain no copy and add no visible overlay.
            scene = {"schema": 1, "layout": direction["layout"], "preset": "portrait", "slides": [{
                "id": parent.scene["slides"][0]["id"], "layers": [
                    _layer("rectangle", 0, 0, 1000, 1000, fill="#ffffff", role="background"),
                    _layer("text", 0, 0, 1000, 100, text="", color="#172d2b", font="Arial", size=48,
                        weight=700, direction="auto", align="start", role="headline"),
                    _layer("text", 0, 100, 1000, 100, text="", color="#172d2b", font="Arial", size=28,
                        weight=700, direction="auto", align="start", role="brand"),
                    _layer("image", 0, 0, 1000, 1000, asset_id=asset.id, sha256=asset.sha256, fit="contain", role="photo")]}]}
            for layer in scene["slides"][0]["layers"]:
                layer["editable"] = False
            scene = validate_scene(scene, {asset.id: asset})
            saved = DesignVersion(workspace_id=workspace, plan_id=parent.plan_id, item_id=parent.item_id,
                revision=parent.revision + 1, parent_id=parent.id, scene=scene, caption=direction["caption"],
                factual_refs=deepcopy(parent.factual_refs), needs_fact_review=True, created_by_user_id=principal.user_id,
                creative_direction={**direction, "run_id": row.id, "provider": row.provider, "model": row.model,
                    "image_app": provider, "context_digest": row.checkpoint["context_digest"],
                    "product_asset_id": row.checkpoint["inputs"]["photo_asset_id"], "generated_asset_id": asset.id,
                    "renderer": "browser_image_app", "product_identity_review_required": True})
            session.add(saved); session.flush()
            row.output = {**row.output, "imported_design_id": saved.id, "generated_asset_id": asset.id,
                "import_sha256": input_digest}
            row.checkpoint = {**row.checkpoint, "stage": "image_imported"}
            return self.creative._payload(saved)
