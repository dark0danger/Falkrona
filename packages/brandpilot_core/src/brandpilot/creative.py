"""Workspace-scoped creative scenes and local, browser-shaped export records."""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import uuid
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .database import set_workspace_context
from .models import BrandProfileVersion, DesignVersion, RenderArtifact, WeeklyPlan, WorkspaceAsset
from .storage import LocalStorage, StorageError
from .config import ExecutionMode


PRESETS = {
    "portrait": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920),
    "landscape": (1200, 628),
}
LAYOUTS = frozenset({"editorial", "product", "type"})
IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _branding(session, workspace_id):
    from .branding import require_branding
    from .phase3 import Phase3Error
    try:
        return require_branding(session, workspace_id)
    except Phase3Error as exc:
        raise CreativeError(exc.code, str(exc)) from exc
DESIGN_POLICY = json.loads((Path(__file__).resolve().parents[4] / "infra" / "hermes" / "skills" /
                            "social-media-graphic-design" / "references" / "design-policy.json").read_text(encoding="utf-8"))


class CreativeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _layer(kind: str, x: int, y: int, w: int, h: int, **fields: object) -> dict:
    return {"id": str(uuid.uuid4()), "type": kind, "x": x, "y": y, "w": w, "h": h,
            "rotation": 0, "opacity": 1, "editable": True, **fields}


def starter_scene(item: dict) -> dict:
    brand = next((ref["value"] for ref in item.get("factual_refs", []) if ref.get("field") == "brand_name"), "Brand")
    slides = []
    count = 2 if item.get("format") == "carousel" else 1
    for index in range(count):
        headline = item["title"] if index == 0 else item["concept"].split(".")[0]
        summary = item["concept"].split(".")[0][:180]
        slides.append({"id": str(uuid.uuid4()), "layers": [
            _layer("rectangle", 0, 0, 1000, 1000, fill="#f4f6f3", role="background"),
            _layer("rectangle", 62, 70, 76, 10, fill="#b83b32", role="accent"),
            _layer("rectangle", 0, 650, 1000, 160, fill="#dce4df", role="cta_panel"),
            _layer("rectangle", 0, 830, 1000, 170, fill="#172d2b", role="footer"),
            _layer("text", 62, 130, 876, 350, text=headline[:600], color="#17231d",
                   font="Arial", size=72, weight=700, direction="auto", align="start", role="headline"),
            _layer("text", 62, 500, 876, 125, text=summary, color="#445149",
                   font="Arial", size=28, weight=400, direction="auto", align="start", role="summary"),
            _layer("text", 62, 670, 850, 120, text=item["cta"][:300], color="#17231d",
                   font="Arial", size=34, weight=700, direction="auto", align="start", role="cta"),
            _layer("text", 62, 870, 850, 65, text=brand[:200], color="#ffffff",
                   font="Arial", size=30, weight=700, direction="auto", align="start", role="brand"),
        ]})
    return {"schema": 1, "layout": "editorial", "preset": "portrait", "slides": slides}


def _logo_palette(content: bytes) -> tuple[str, str, str]:
    try:
        with Image.open(BytesIO(content)) as source:
            image = source.convert("RGBA")
            image.thumbnail((96, 96), Image.Resampling.NEAREST)
            quantized = image.convert("RGB").quantize(colors=12, method=Image.Quantize.MEDIANCUT).convert("RGB")
            colors = Counter(rgb for rgb, (_, _, _, alpha) in zip(quantized.getdata(), image.getdata())
                             if alpha >= 220)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise CreativeError("invalid_logo", "The selected logo cannot be analyzed.") from exc
    prominent = ["#%02x%02x%02x" % rgb for rgb, count in colors.most_common(24)
                 if count >= max(2, image.width * image.height // 400)]
    if not prominent:
        raise CreativeError("logo_palette_unusable", "The logo needs visible artwork.")
    if not any(_contrast(a, b) >= 4.5 for a in prominent for b in prominent):
        # Add neutral contrast, never a fabricated Falkrona color to another logo.
        prominent += ["#ffffff"]
        if not any(_contrast(a, b) >= 4.5 for a in prominent for b in prominent):
            prominent += ["#000000"]
    pairs = [(a, b) for a in prominent for b in prominent if _contrast(a, b) >= 4.5]
    if not pairs:
        raise CreativeError("logo_palette_unusable", "The logo needs light and dark colors for readable artwork.")
    background, foreground = max(pairs, key=lambda pair: (_contrast(*pair), -int(pair[0][1:], 16)))
    if sum(int(background[i:i + 2], 16) for i in (1, 3, 5)) > sum(int(foreground[i:i + 2], 16) for i in (1, 3, 5)):
        background, foreground = foreground, background
    def color_distance(first: str, second: str) -> int:
        return sum(abs(int(first[index:index + 2], 16) - int(second[index:index + 2], 16))
                   for index in (1, 3, 5))

    accent = next((color for color in prominent
                   if color_distance(color, background) > 100 and color_distance(color, foreground) > 100),
                  foreground)
    return background, foreground, accent


def _is_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06ff]", text))


def guided_scene(item: dict, brand: str, logo: WorkspaceAsset, photo: WorkspaceAsset,
                 palette: tuple[str, str, str], language: str,
                 logo_includes_name: bool = False, generated_scene: bool = False,
                 headline: str | None = None, call_to_action: str | None = None) -> dict:
    ink, paper, _accent = palette
    rtl = language == "ar"
    title = headline if headline is not None else str(item["title"]).split("|")[0].strip()
    if _is_arabic(title) != rtl:
        category = next((str(ref["value"]) for ref in item.get("factual_refs", [])
                         if ref.get("field") == "category"), "")
        title = ((f"لنتحدث عن {category}" if _is_arabic(category) else "ما الذي يجمع\nفريقك؟") if rtl
                 else (f"Let's talk {category}" if category and not _is_arabic(category) else "A moment worth sharing"))
    words = title.split()
    if len(words) > DESIGN_POLICY["max_headline_words"]:
        title = " ".join(words[:DESIGN_POLICY["max_headline_words"]]).rstrip(".,;:!?")
    cta = call_to_action if call_to_action is not None else str(item.get("cta", "")).strip()
    if _is_arabic(cta) != rtl or len(cta.split()) > 6:
        cta = "تواصل معنا" if rtl else "Join the conversation"
    logo_x = 810 if rtl else 50
    brand_x = 80 if rtl else 220
    sizes = DESIGN_POLICY["type_scale"]
    slides = []
    for _ in range(2 if item.get("format") == "carousel" else 1):
        slides.append({"id": str(uuid.uuid4()), "layers": [
            _layer("rectangle", 0, 0, 1000, 1000, fill=paper, role="background"),
            _layer("image", 0 if generated_scene else 280, 0 if generated_scene else 450,
                   1000 if generated_scene else 440, 1000 if generated_scene else 500,
                   asset_id=photo.id, sha256=photo.sha256,
                   fit="cover" if generated_scene else "contain", role="photo"),
            _layer("image", logo_x, 45, 140, 140, asset_id=logo.id, sha256=logo.sha256,
                   fit="contain", role="logo"),
            _layer("text", brand_x, 67, 700, 75, text="" if logo_includes_name else brand[:120], color=ink,
                   font="Arial", size=sizes["brand"], weight=700, direction="rtl" if rtl else "ltr",
                   align="start", role="brand"),
            _layer("text", 60, 185, 880, 175, text=title[:120], color=ink,
                   font="Arial", size=sizes["headline"], weight=700, direction="rtl" if rtl else "ltr",
                   align="center", role="headline"),
            _layer("text", 60, 365, 880, 55, text=cta[:100], color=ink,
                   font="Arial", size=sizes["cta"], weight=400, direction="rtl" if rtl else "ltr",
                   align="center", role="cta"),
        ]})
    return {"schema": 1, "layout": "product", "preset": DESIGN_POLICY["canvas"]["preset"], "slides": slides}


def _exact(value: dict, fields: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == fields


def _contrast(first: str, second: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]
    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + .05) / (dark + .05)


def validate_scene(scene: dict, assets: dict[str, WorkspaceAsset]) -> dict:
    if not _exact(scene, {"schema", "layout", "preset", "slides"}) or scene["schema"] != 1:
        raise CreativeError("invalid_scene", "The scene schema is not supported.")
    if not isinstance(scene["layout"], str) or not isinstance(scene["preset"], str) or scene["layout"] not in LAYOUTS or scene["preset"] not in PRESETS:
        raise CreativeError("invalid_scene", "Choose a supported layout and output size.")
    slides = scene["slides"]
    if not isinstance(slides, list) or not 1 <= len(slides) <= 8:
        raise CreativeError("invalid_scene", "A design needs one to eight slides.")
    ids: set[str] = set()
    normalized = deepcopy(scene)
    for slide in slides:
        if not _exact(slide, {"id", "layers"}) or not isinstance(slide["layers"], list) or not 1 <= len(slide["layers"]) <= 16:
            raise CreativeError("invalid_scene", "Each slide needs valid layers.")
        try:
            uuid.UUID(slide["id"])
        except (ValueError, TypeError):
            raise CreativeError("invalid_scene", "Slide IDs must be stable UUIDs.") from None
        if slide["id"] in ids:
            raise CreativeError("invalid_scene", "Duplicate slide ID.")
        ids.add(slide["id"])
        roles: set[str] = set()
        for layer in slide["layers"]:
            kind = layer.get("type") if isinstance(layer, dict) else None
            if not isinstance(kind, str):
                raise CreativeError("invalid_scene", "Layer type is invalid.")
            extra = ({"text", "color", "font", "size", "weight", "direction", "align", "role"} if kind == "text"
                     else {"fill", "role"} if kind in {"rectangle", "ellipse"}
                     else {"asset_id", "sha256", "role", "fit"} if kind == "image" else set())
            if not extra or not _exact(layer, {"id", "type", "x", "y", "w", "h", "rotation", "opacity", "editable"} | extra):
                raise CreativeError("invalid_scene", "Only reviewed scene layers are allowed.")
            try:
                uuid.UUID(layer["id"])
            except (ValueError, TypeError):
                raise CreativeError("invalid_scene", "Layer IDs must be stable UUIDs.") from None
            if layer["id"] in ids:
                raise CreativeError("invalid_scene", "Duplicate layer ID.")
            ids.add(layer["id"])
            if any(type(layer[name]) is not int for name in ("x", "y", "w", "h", "rotation")) or (
                layer["x"] < 0 or layer["y"] < 0 or layer["w"] <= 0 or layer["h"] <= 0 or
                layer["x"] + layer["w"] > 1000 or layer["y"] + layer["h"] > 1000 or
                not -180 <= layer["rotation"] <= 180
            ):
                raise CreativeError("out_of_bounds", "A layer falls outside the canvas.")
            if not isinstance(layer["opacity"], (int, float)) or not 0 <= layer["opacity"] <= 1 or type(layer["editable"]) is not bool:
                raise CreativeError("invalid_scene", "Layer opacity or editability is invalid.")
            role = layer["role"]
            if not isinstance(role, str) or not re.fullmatch(r"[a-z_]{1,32}", role):
                raise CreativeError("invalid_scene", "Layer role is invalid.")
            if role in {"background", "headline", "cta", "brand", "logo", "product"}:
                if role in roles:
                    raise CreativeError("invalid_scene", "A required layer role is duplicated.")
                roles.add(role)
            if kind == "text":
                if (not isinstance(layer["text"], str) or len(layer["text"]) > 600 or
                    "\x00" in layer["text"] or "<script" in layer["text"].lower() or
                    not isinstance(layer["color"], str) or not COLOR.fullmatch(layer["color"]) or layer["font"] != "Arial" or
                    type(layer["size"]) is not int or not 12 <= layer["size"] <= 160 or
                    type(layer["weight"]) is not int or layer["weight"] not in {400, 700} or
                    not isinstance(layer["direction"], str) or layer["direction"] not in {"auto", "ltr", "rtl"} or
                    not isinstance(layer["align"], str) or layer["align"] not in {"start", "center", "end"}):
                    raise CreativeError("invalid_scene", "Text properties are invalid.")
            elif kind in {"rectangle", "ellipse"}:
                if not isinstance(layer["fill"], str) or not COLOR.fullmatch(layer["fill"]):
                    raise CreativeError("invalid_scene", "Shape color is invalid.")
            else:
                asset = assets.get(layer["asset_id"]) if isinstance(layer["asset_id"], str) else None
                if (asset is None or asset.mime_type not in IMAGE_MIMES or asset.status != "ready" or
                    layer["sha256"] != asset.sha256 or layer["role"] not in {"logo", "product", "photo"} or
                    (layer["fit"] not in {"cover", "contain"} if layer["role"] == "photo" else layer["fit"] != "contain")):
                    raise CreativeError("invalid_asset", "Use a current, approved workspace image without cropping.")
        if not {"background", "headline", "brand"} <= roles:
            raise CreativeError("invalid_scene", "Keep the background, headline, and brand layers.")
        background = next(layer for layer in slide["layers"] if layer["role"] == "background")
        if background["type"] != "rectangle" or any(background[key] != value for key, value in
                                                        {"x": 0, "y": 0, "w": 1000, "h": 1000, "opacity": 1, "rotation": 0}.items()):
            raise CreativeError("invalid_scene", "The background must cover the entire canvas.")
        for layer in slide["layers"]:
            if layer["type"] == "text" and layer["role"] in {"headline", "cta"}:
                if _contrast(layer["color"], background["fill"]) < 4.5:
                    raise CreativeError("low_contrast", "Headline and CTA text must be readable against the background.")
    return normalized


def reference_traits(content: bytes) -> dict:
    try:
        with Image.open(BytesIO(content)) as image:
            image.thumbnail((64, 64))
            rgb = image.convert("RGB")
            colors = rgb.quantize(colors=4, method=Image.Quantize.MEDIANCUT).convert("RGB")
            palette = sorted(set(colors.getdata()), key=lambda color: sum(color))
            return {"aspect_ratio": round(image.width / image.height, 3),
                    "palette": ["#%02x%02x%02x" % color for color in palette[:4]],
                    "source_copy_used": False, "source_logo_used": False}
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ZeroDivisionError) as exc:
        raise CreativeError("invalid_reference", "Reference image could not be analyzed.") from exc


class CreativeService:
    def __init__(self, sessions: sessionmaker[Session], accounts: AccountService, storage: LocalStorage, runtime=None) -> None:
        self._sessions = sessions
        self._accounts = accounts
        self._storage = storage
        self._runtime = runtime

    @staticmethod
    def _payload(row: DesignVersion) -> dict:
        return {"id": row.id, "plan_id": row.plan_id, "item_id": row.item_id,
                "revision": row.revision, "parent_id": row.parent_id, "scene": row.scene,
                "caption": row.caption, "factual_refs": row.factual_refs,
                "creative_direction": row.creative_direction,
                "needs_fact_review": row.needs_fact_review, "created_at": row.created_at.isoformat()}

    @staticmethod
    def _version(session: Session, workspace_id: str, version_id: str) -> DesignVersion:
        row = session.scalar(select(DesignVersion).where(
            DesignVersion.workspace_id == workspace_id, DesignVersion.id == version_id))
        if row is None:
            raise CreativeError("design_not_found", "The design version is unavailable.")
        return row

    @staticmethod
    def _assets(session: Session, workspace_id: str, scene: dict) -> dict[str, WorkspaceAsset]:
        slides = scene.get("slides")
        if not isinstance(slides, list):
            return {}
        ids = {layer.get("asset_id") for slide in slides if isinstance(slide, dict)
               for layer in (slide.get("layers") if isinstance(slide.get("layers"), list) else [])
               if isinstance(layer, dict) and layer.get("type") == "image"
               and isinstance(layer.get("asset_id"), str)}
        if not ids:
            return {}
        return {row.id: row for row in session.scalars(select(WorkspaceAsset).where(
            WorkspaceAsset.workspace_id == workspace_id, WorkspaceAsset.id.in_(ids)))}

    def latest(self, principal: Principal, workspace_id: str, plan_id: str, item_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == plan_id))
            if plan and (plan.status == "deleted" or not any(item["id"] == item_id for item in plan.items)):
                return {"current": None, "history": []}
            versions = session.scalars(select(DesignVersion).where(
                DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == plan_id,
                DesignVersion.item_id == item_id).order_by(DesignVersion.revision.desc())).all()
            return {"current": self._payload(versions[0]) if versions else None,
                    "history": [{"id": row.id, "revision": row.revision, "created_at": row.created_at.isoformat()}
                                for row in versions]}

    def create(self, principal: Principal, workspace_id: str, plan_id: str, item_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            _branding(session, workspace_id)
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == plan_id))
            if plan is None:
                raise CreativeError("plan_not_found", "The source plan is unavailable.")
            if plan.status == "deleted":
                raise CreativeError("plan_deleted", "This plan was deleted. Undo deletion or draft a new week.")
            item = next((entry for entry in plan.items if entry.get("id") == item_id), None)
            if item is None or item.get("status") == "rejected" or item.get("conflicts"):
                raise CreativeError("brief_unavailable", "Choose a current, non-conflicting brief.")
            existing = session.scalar(select(DesignVersion).where(
                DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == plan_id,
                DesignVersion.item_id == item_id).order_by(DesignVersion.revision.desc()))
            if existing:
                return self._payload(existing)
            row = DesignVersion(workspace_id=workspace_id, plan_id=plan_id, item_id=item_id,
                                revision=1, parent_id=None, scene=starter_scene(item),
                                caption=f"{item['title']}\n\n{item['cta']}", factual_refs=deepcopy(item["factual_refs"]),
                                needs_fact_review=False, created_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            return self._payload(row)

    def regenerate(self, principal: Principal, workspace_id: str, version_id: str,
                   logo_asset_id: str, photo_asset_id: str, language: str,
                   product_image_confirmed: bool = False,
                   logo_includes_name: bool = False, direction_run_id: str | None = None,
                   product_description: str = "") -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        if not product_image_confirmed:
            raise CreativeError("product_image_unconfirmed", "Confirm that the selected image shows this brand's product before generating.")
        if language not in {"auto", "ar", "en"}:
            raise CreativeError("invalid_language", "Choose Arabic, English, or automatic language.")
        if logo_asset_id == photo_asset_id:
            raise CreativeError("invalid_asset", "Choose a separate logo and photograph.")
        requested_language = language
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            branding = _branding(session, workspace_id)
            if branding.logo_asset_id != logo_asset_id:
                raise CreativeError("brand_logo_mismatch", "Use the logo saved in Branding.")
            parent = self._version(session, workspace_id, version_id)
            latest = session.scalar(select(DesignVersion).where(
                DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == parent.plan_id,
                DesignVersion.item_id == parent.item_id).order_by(DesignVersion.revision.desc()))
            if latest.id != parent.id:
                raise CreativeError("stale_design", "Refresh the design before regenerating.")
            plan = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == parent.plan_id))
            item = next((entry for entry in plan.items if entry.get("id") == parent.item_id), None)
            if item is None or item.get("status") == "rejected" or item.get("conflicts"):
                raise CreativeError("brief_unavailable", "Choose a current, non-conflicting brief.")
            selected = {row.id: row for row in session.scalars(select(WorkspaceAsset).where(
                WorkspaceAsset.workspace_id == workspace_id,
                WorkspaceAsset.id.in_([logo_asset_id, photo_asset_id])))}
            logo, photo = selected.get(logo_asset_id), selected.get(photo_asset_id)
            if any(asset is None or asset.status != "ready" or asset.mime_type not in IMAGE_MIMES
                   for asset in (logo, photo)):
                raise CreativeError("invalid_asset", "Choose an approved logo and photograph from this workspace.")
            profile = session.scalar(select(BrandProfileVersion).where(
                BrandProfileVersion.workspace_id == workspace_id,
                BrandProfileVersion.status == "confirmed").order_by(BrandProfileVersion.version.desc()))
            if profile is None or not str(profile.fields.get("brand_name", "")).strip():
                raise CreativeError("brand_unconfirmed", "Confirm the workspace brand name before creating a design.")
            audience = str(profile.fields.get("audience", "")) if profile else ""
            if language == "auto":
                language = "ar" if _is_arabic(audience) else "en"
            brand = next((str(ref["value"]) for ref in parent.factual_refs
                          if ref.get("field") == "brand_name"), "Brand")
            if brand.casefold() != str(profile.fields["brand_name"]).strip().casefold():
                raise CreativeError("brand_mismatch", "The brief brand no longer matches the confirmed profile. Refresh the plan.")
            logo_bytes = self._storage.read_bytes(logo.storage_key)
            palette = _logo_palette(logo_bytes)
            direction = {}
            if direction_run_id:
                raise CreativeError("image_app_required", "Return the complete image from your image app before saving a new design.")
            if self._runtime and self._runtime.execution_mode is not ExecutionMode.OFFLINE_TEST:
                raise CreativeError("generated_scene_required", "Prepare your Gemini direction and generate the complete ad in your image app.")
            # Deterministic offline fixtures only; live requests cannot use photo overlays.
            scene = guided_scene(item, brand, logo, photo, palette, language,
                                 logo_includes_name=logo_includes_name)
            normalized = validate_scene(scene, selected)
            row = DesignVersion(workspace_id=workspace_id, plan_id=parent.plan_id,
                                item_id=parent.item_id, revision=parent.revision + 1,
                                parent_id=parent.id, scene=normalized, creative_direction=direction,
                                caption=direction.get("caption", parent.caption), factual_refs=deepcopy(parent.factual_refs),
                                needs_fact_review=True, created_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            return self._payload(row)

    def revise(self, principal: Principal, workspace_id: str, version_id: str,
               scene: dict, caption: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        if not isinstance(caption, str) or len(caption) > 4000:
            raise CreativeError("invalid_caption", "Caption must be under 4,000 characters.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            _branding(session, workspace_id)
            parent = self._version(session, workspace_id, version_id)
            latest = session.scalar(select(DesignVersion).where(
                DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == parent.plan_id,
                DesignVersion.item_id == parent.item_id).order_by(DesignVersion.revision.desc()))
            if latest.id != parent.id:
                raise CreativeError("stale_design", "Refresh the design before saving another revision.")
            normalized = validate_scene(scene, self._assets(session, workspace_id, scene))
            if normalized == parent.scene and caption == parent.caption:
                return self._payload(parent)
            row = DesignVersion(workspace_id=workspace_id, plan_id=parent.plan_id, item_id=parent.item_id,
                                revision=parent.revision + 1, parent_id=parent.id, scene=normalized,
                                caption=caption, factual_refs=deepcopy(parent.factual_refs),
                                creative_direction=deepcopy(parent.creative_direction),
                                needs_fact_review=normalized != parent.scene or caption != parent.caption,
                                created_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            return self._payload(row)

    def get(self, principal: Principal, workspace_id: str, version_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            return self._payload(self._version(session, workspace_id, version_id))

    def inspect_reference(self, principal: Principal, workspace_id: str, asset_id: str) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            asset = session.scalar(select(WorkspaceAsset).where(
                WorkspaceAsset.workspace_id == workspace_id, WorkspaceAsset.id == asset_id))
            if asset is None or asset.mime_type not in IMAGE_MIMES:
                raise CreativeError("invalid_reference", "Choose a workspace raster image.")
            return reference_traits(self._storage.read_bytes(asset.storage_key))

    def record_png(self, principal: Principal, workspace_id: str, version_id: str,
                   slide_id: str, preset: str, content: bytes) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        if preset not in PRESETS or len(content) > 15_000_000 or len(content) < 100:
            raise CreativeError("invalid_render", "The PNG is missing, too large, or has an unsupported preset.")
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                if image.format != "PNG" or image.size != PRESETS[preset]:
                    raise CreativeError("invalid_render", "PNG dimensions do not match the selected preset.")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise CreativeError("invalid_render", "The renderer did not return a valid PNG.") from exc
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            version = self._version(session, workspace_id, version_id)
            if preset != version.scene["preset"] or slide_id not in {slide["id"] for slide in version.scene["slides"]}:
                raise CreativeError("invalid_render", "Render does not match this scene version.")
            existing = session.scalar(select(RenderArtifact).where(
                RenderArtifact.workspace_id == workspace_id, RenderArtifact.design_version_id == version_id,
                RenderArtifact.slide_id == slide_id, RenderArtifact.preset == preset))
            if existing:
                if existing.sha256 != hashlib.sha256(content).hexdigest():
                    raise CreativeError("render_conflict", "This version already has a different render.")
                return {"id": existing.id, "sha256": existing.sha256}
            digest = hashlib.sha256(content).hexdigest()
            key = f"workspaces/{workspace_id}/designs/{version_id}/{slide_id}/{digest}.png"
            try:
                self._storage.put_bytes(key, content)
            except StorageError as exc:
                raise CreativeError("storage_failure", "Render storage failed; the scene draft is preserved.") from exc
            row = RenderArtifact(workspace_id=workspace_id, design_version_id=version_id,
                                 slide_id=slide_id, preset=preset, storage_key=key, sha256=digest,
                                 width=PRESETS[preset][0], height=PRESETS[preset][1])
            session.add(row)
            session.flush()
            return {"id": row.id, "sha256": digest}

    def package(self, principal: Principal, workspace_id: str, version_id: str) -> bytes:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            version = self._version(session, workspace_id, version_id)
            artifacts = {row.slide_id: row for row in session.scalars(select(RenderArtifact).where(
                RenderArtifact.workspace_id == workspace_id, RenderArtifact.design_version_id == version_id))}
            ordered = version.scene["slides"]
            if len(artifacts) != len(ordered) or any(slide["id"] not in artifacts for slide in ordered):
                raise CreativeError("render_incomplete", "Render every slide before downloading the package.")
            output = BytesIO()
            manifest = {"design_version_id": version.id, "revision": version.revision,
                        "preset": version.scene["preset"], "caption": version.caption,
                        "needs_fact_review": version.needs_fact_review, "factual_refs": version.factual_refs,
                        "slides": []}
            with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                for index, slide in enumerate(ordered, 1):
                    artifact = artifacts[slide["id"]]
                    name = f"{index:02d}-{version.scene['preset']}.png"
                    jpeg_name = f"{index:02d}-{version.scene['preset']}.jpg"
                    try:
                        data = self._storage.read_bytes(artifact.storage_key)
                    except StorageError as exc:
                        raise CreativeError("render_missing", "A stored render is missing; the design draft remains available.") from exc
                    if hashlib.sha256(data).hexdigest() != artifact.sha256:
                        raise CreativeError("render_corrupt", "A stored render failed its hash check.")
                    archive.writestr(name, data)
                    jpeg = BytesIO()
                    try:
                        with Image.open(BytesIO(data)) as image:
                            image.convert("RGB").save(jpeg, "JPEG", quality=92, optimize=True)
                    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
                        raise CreativeError("render_corrupt", "A stored render could not be converted.") from exc
                    jpeg_bytes = jpeg.getvalue()
                    archive.writestr(jpeg_name, jpeg_bytes)
                    manifest["slides"].append({"order": index, "id": slide["id"], "filename": name,
                                               "sha256": artifact.sha256, "width": artifact.width,
                                               "height": artifact.height, "jpeg_filename": jpeg_name,
                                               "jpeg_sha256": hashlib.sha256(jpeg_bytes).hexdigest()})
                archive.writestr("caption.txt", version.caption)
                archive.writestr("alt-text.txt", "Draft alt text: " + next((layer["text"] for layer in ordered[0]["layers"]
                                 if layer.get("role") == "headline"), "Design"))
                archive.writestr("scene.json", json.dumps(version.scene, ensure_ascii=False, indent=2))
                if version.creative_direction:
                    archive.writestr("creative-direction.json", json.dumps(version.creative_direction, ensure_ascii=False, indent=2))
                    archive.writestr("image-prompt.txt", version.creative_direction["image_prompt"])
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            return output.getvalue()
