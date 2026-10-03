"""Generate every post from one owner action; save each result independently."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import hashlib
from io import BytesIO
import json
import zipfile

from sqlalchemy import select

from .creative import CreativeError, _branding
from .database import set_workspace_context
from .models import AgentRun, DesignVersion, Job, PublicationApproval, WeeklyPlan, Workspace, WorkspaceAsset
from .asset_roles import asset_purpose, upload_roles
from .brand_treatment import with_cta


class PlanGenerationService:
    def __init__(self, sessions, accounts, creative, directions, storage):
        self.sessions, self.accounts = sessions, accounts
        self.creative, self.directions, self.storage = creative, directions, storage

    @staticmethod
    def _plan(session, workspace_id, plan_id, lock=False):
        query = select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == plan_id)
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise CreativeError("plan_not_found", "This week's plan is unavailable.")
        return row

    def start(self, principal, workspace_id, plan_id, inputs, provider, consent):
        self.accounts.require_permission(principal, workspace_id, "write")
        if provider not in {"chatgpt", "gemini"} or not consent:
            raise CreativeError("consent_required", "Allow your image app to receive the week's brand details and images.")
        language = inputs.get("language", "auto")
        if language not in {"auto", "ar", "en"}:
            raise CreativeError("invalid_language", "Choose Arabic or English for your designs.")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            session.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
            plan = self._plan(session, workspace_id, plan_id, True)
            self._editable(session, workspace_id, plan)
            brand = _branding(session, workspace_id)
            if plan.strategy.get("planner") != "gemini":
                raise CreativeError("gemini_plan_required", "Draft this week with Gemini before generating images.")
            if plan.strategy.get("visual_planning_version") != 2 or any(not item.get("visual_concept") for item in plan.items):
                raise CreativeError("new_visual_plan_required", "Draft a new week to create distinct designs using the updated brand direction.")
            current = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id,
                WeeklyPlan.week_start == plan.week_start).order_by(WeeklyPlan.revision.desc()))
            if current.id != plan.id:
                raise CreativeError("plan_stale", "Use the latest weekly plan.")
            photo = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id,
                WorkspaceAsset.id == inputs["photo_asset_id"], WorkspaceAsset.source == "upload", WorkspaceAsset.status == "ready"))
            if not photo or asset_purpose(photo, upload_roles(session, workspace_id)) != "product" or photo.id in {brand.logo_asset_id, brand.reference_asset_id} or photo.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise CreativeError("invalid_asset", "Choose a product photo from this workspace.")
            normalized = {**inputs, "logo_asset_id": brand.logo_asset_id, "product_image_confirmed": True,
                          "logo_includes_name": False, "language": language}
            config = {"inputs": normalized, "provider": provider}
            previous = plan.strategy.get("generation")
            if previous and previous["config"] != config:
                raise CreativeError("generation_started", "This week already has a generation request. Draft a new week to change its images.")
            if not previous:
                plan.strategy = {**plan.strategy, "generation": {"config": config, "entries": []}}
            entries = deepcopy((previous or {}).get("entries", []))
            items = deepcopy(plan.items)
        known = {entry["item_id"]: entry for entry in entries}
        for item in items:
            if item.get("status") == "rejected":
                continue
            existing = known.get(item["id"])
            if existing:
                with self.sessions() as session, session.begin():
                    set_workspace_context(session, workspace_id)
                    old_run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id,
                        AgentRun.id == existing["run_id"]))
                    if old_run and old_run.status not in {"failed", "cancelled"}:
                        continue
                draft = {"id": existing["design_id"]}
            else:
                draft = self.creative.create(principal, workspace_id, plan_id, item["id"])
            run = self.directions.start(principal, workspace_id, draft["id"], normalized,
                public_context_confirmed=True, retry_failed=bool(existing))
            entry = {"item_id": item["id"], "title": item["title"], "design_id": draft["id"], "run_id": run["id"]}
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace_id)
                row = self._plan(session, workspace_id, plan_id, True)
                generation = deepcopy(row.strategy["generation"])
                if existing:
                    generation["entries"] = [entry if value["item_id"] == item["id"] else value for value in generation["entries"]]
                elif not any(value["item_id"] == item["id"] for value in generation["entries"]):
                    generation["entries"].append(entry)
                row.strategy = {**row.strategy, "generation": generation}
        return self.get(principal, workspace_id, plan_id)

    @staticmethod
    def _editable(session, workspace, plan):
        latest = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace,
            WeeklyPlan.week_start == plan.week_start).order_by(WeeklyPlan.revision.desc()))
        if latest.id != plan.id:
            raise CreativeError("plan_stale", "Use the latest weekly plan.")
        approval = session.scalar(select(PublicationApproval.id).where(PublicationApproval.workspace_id == workspace,
            PublicationApproval.status == "approved", PublicationApproval.design_version_id.in_(
                select(DesignVersion.id).where(DesignVersion.workspace_id == workspace, DesignVersion.plan_id == plan.id))))
        if approval or plan.status == "approved":
            raise CreativeError("plan_scheduled", "Cancel unpublished posts and draft a new plan before changing scheduled designs. Published posts stay in your history.")
        if plan.status != "draft":
            raise CreativeError("plan_deleted", "This plan was deleted. Undo deletion or draft a new week.")

    def reschedule(self, principal, workspace, plan_id, item_id, local_time, previous_time):
        self.accounts.require_permission(principal, workspace, "write")
        from .publication import cairo_instant, PublicationError
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            session.scalar(select(Workspace).where(Workspace.id == workspace).with_for_update())
            plan = self._plan(session, workspace, plan_id, True)
            self._editable(session, workspace, plan)
            self._no_pending(session, workspace, plan)
            items = deepcopy(plan.items)
            item = next((item for item in items if item["id"] == item_id), None)
            if not item:
                raise CreativeError("item_not_found", "This post is unavailable.")
            if item["scheduled_at"] != previous_time:
                raise CreativeError("schedule_stale", "This posting time changed. Refresh the plan and try again.")
            try:
                moment, _ = cairo_instant(local_time, None)
            except PublicationError as exc:
                message = "This hour repeats when Cairo clocks change. Choose a different time." if exc.code == "ambiguous_schedule" else str(exc)
                raise CreativeError(exc.code, message) from None
            if not plan.week_start <= moment.astimezone(ZoneInfo("Africa/Cairo")).date() < plan.week_start + timedelta(days=7):
                raise CreativeError("outside_week", "Choose a date within this plan's week.")
            if any(other["id"] != item_id and datetime.fromisoformat(other["scheduled_at"]) == moment for other in items):
                raise CreativeError("schedule_conflict", "Another post uses that time. Choose a different time.")
            item["scheduled_at"] = moment.isoformat()
            plan.items = sorted(items, key=lambda item: item["scheduled_at"])
        return self.get(principal, workspace, plan_id)

    def remove(self, principal, workspace, plan_id, item_id=None, restore=False):
        self.accounts.require_permission(principal, workspace, "write")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            session.scalar(select(Workspace).where(Workspace.id == workspace).with_for_update())
            plan = self._plan(session, workspace, plan_id, True)
            # A deleted latest plan can be restored, but cannot supersede a newer draft.
            if restore and item_id is None and plan.status == "deleted":
                latest = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace,
                    WeeklyPlan.week_start == plan.week_start).order_by(WeeklyPlan.revision.desc()))
                if latest.id != plan.id:
                    raise CreativeError("plan_stale", "A newer plan exists. Keep that plan or draft another week.")
                plan.status = "draft"
                return {"restored": True}
            self._editable(session, workspace, plan)
            strategy = deepcopy(plan.strategy)
            if item_id is None:
                plan.status = "deleted"
                ids = [entry.get("run_id") for entry in strategy.get("generation", {}).get("entries", [])]
                for run in session.scalars(select(AgentRun).where(AgentRun.workspace_id == workspace, AgentRun.id.in_(ids))):
                    if run.status in {"queued", "running"}:
                        run.cancel_requested = True
                        job = session.scalar(select(Job).where(Job.workspace_id == workspace, Job.id == run.job_id))
                        if run.status == "queued":
                            run.status = "cancelled"
                            if job and job.status == "queued":
                                job.status = "cancelled"
                return {"deleted": True}
            removed = strategy.get("removed_items", [])
            items = deepcopy(plan.items)
            if restore:
                self._no_pending(session, workspace, plan)
                saved = next((value for value in removed if value["item"]["id"] == item_id), None)
                if not saved:
                    raise CreativeError("item_not_found", "This deleted design is unavailable.")
                items.insert(min(saved["index"], len(items)), saved["item"])
                items.sort(key=lambda item: item["scheduled_at"])
                removed = [value for value in removed if value["item"]["id"] != item_id]
            else:
                index = next((index for index, item in enumerate(items) if item["id"] == item_id), None)
                if index is None:
                    raise CreativeError("item_not_found", "This design is unavailable.")
                # Other pending briefs include the weekly context; do not invalidate a live handoff.
                self._no_pending(session, workspace, plan)
                removed.append({"index": index, "item": items.pop(index)})
            strategy["removed_items"] = removed
            strategy["cadence"] = len(items)
            strategy["content_mix"] = {purpose: sum(item["purpose"] == purpose for item in items)
                for purpose in {"education", "conversation", "product", "offer"}}
            plan.items, plan.strategy = items, strategy
            return {"restored": restore, "deleted": not restore}

    @staticmethod
    def _no_pending(session, workspace, plan):
        ids = [entry.get("run_id") for entry in plan.strategy.get("generation", {}).get("entries", [])
            if entry["item_id"] in {item["id"] for item in plan.items}]
        if None in ids:
            raise CreativeError("generation_in_progress", "Continue creating designs before changing individual posts.")
        runs = session.scalars(select(AgentRun).where(AgentRun.workspace_id == workspace, AgentRun.id.in_(ids))).all()
        if any(run.status in {"queued", "running"} or run.status == "completed" and not run.output.get("imported_design_id") for run in runs):
            raise CreativeError("generation_in_progress", "Finish the current image request before changing individual designs. You can delete the whole plan to stop using it.")

    def regenerate(self, principal, workspace, plan_id, item_id, expected_design_id):
        self.accounts.require_permission(principal, workspace, "write")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace)
            session.scalar(select(Workspace).where(Workspace.id == workspace).with_for_update())
            plan = self._plan(session, workspace, plan_id, True)
            self._editable(session, workspace, plan)
            self._no_pending(session, workspace, plan)
            parent = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace,
                DesignVersion.plan_id == plan_id, DesignVersion.item_id == item_id).order_by(DesignVersion.revision.desc()))
            if not parent or parent.id != expected_design_id or not parent.creative_direction.get("generated_asset_id"):
                raise CreativeError("design_stale", "Refresh this design before regenerating it.")
            items = deepcopy(plan.items)
            item = next((item for item in items if item["id"] == item_id), None)
            if not item or not plan.strategy.get("generation"):
                raise CreativeError("item_not_found", "This design is unavailable.")
            old = item["visual_concept"]
            # Assign an unused route BEFORE inspecting the product, so its photo cannot dictate the idea.
            routes = ["graphic_story", "detail_study", "ingredient_story", "overhead_arrangement", "human_moment", "product_hero"]
            used = {other["visual_concept"]["route"] for other in items}
            route = next(route for route in routes if route not in used)
            directions = {
                "graphic_story": ("eye_level", "diagonal_motion", "A fresh graphic narrative uses layered brand-color shapes and unexpected negative space around the actual product."),
                "detail_study": ("close_up", "immersive_crop", "An intimate detail study explores the actual product's material and texture in an entirely new studio setting."),
                "ingredient_story": ("low_angle", "split_comparison", "A new editorial story connects only confirmed product details with a fresh setting and a clear visual relationship."),
                "overhead_arrangement": ("overhead", "overhead_grid", "An overhead editorial arrangement uses the actual product in a fresh geometric grouping with generous negative space."),
                "human_moment": ("wide_environment", "asymmetric_editorial", "A relatable human interaction features the actual product in a completely new everyday moment and environment."),
                "product_hero": ("low_angle", "central_sculptural", "A sculptural product portrait places the actual product in a new architectural setting with a strong silhouette."),
            }
            camera, composition, scene = directions[route]
            if camera == old["camera"] and composition == old["composition"]:
                camera = "overhead" if camera != "overhead" else "eye_level"
            item["idea_history"] = [*item.get("idea_history", []), old][-5:]
            item["visual_concept"] = {"route": route, "camera": camera, "composition": composition,
                "scene": scene, "visual_hook": "Gemini must invent a new focal action and setting for this message; preserve the fixed brand CTA zone.",
                "background_color": old["background_color"]}
            revision = DesignVersion(workspace_id=workspace, plan_id=plan_id, item_id=item_id,
                revision=parent.revision+1, parent_id=parent.id, scene=deepcopy(parent.scene), caption=parent.caption,
                creative_direction={}, factual_refs=deepcopy(parent.factual_refs), needs_fact_review=parent.needs_fact_review,
                created_by_user_id=principal.user_id)
            session.add(revision); session.flush()
            strategy = deepcopy(plan.strategy)
            strategy["visual_identity"] = with_cta(strategy.get("visual_identity"), strategy["visual_identity"]["palette"])
            generation = strategy["generation"]
            replacement = {"item_id": item_id, "title": item["title"], "design_id": revision.id, "run_id": None}
            generation["entries"] = [replacement if entry["item_id"] == item_id else entry for entry in generation["entries"]]
            plan.items, plan.strategy = items, strategy
            config = deepcopy(generation["config"])
        # A reserved revision can be resumed by start() if the process stops here.
        return self.start(principal, workspace, plan_id, config["inputs"], config["provider"], True)

    def get(self, principal, workspace_id, plan_id):
        self.accounts.require_permission(principal, workspace_id, "read")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            plan = self._plan(session, workspace_id, plan_id)
            if plan.status == "deleted":
                return {"provider": None, "entries": [], "complete": False}
            generation = plan.strategy.get("generation")
            if not generation:
                return {"provider": None, "entries": [], "complete": False}
            entries = []
            for entry in generation["entries"]:
                if entry["item_id"] not in {item["id"] for item in plan.items if item.get("status") != "rejected"}:
                    continue
                run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id, AgentRun.id == entry["run_id"]))
                imported_id = run.output.get("imported_design_id") if run else None
                asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id,
                    WorkspaceAsset.id == run.output.get("generated_asset_id"))) if imported_id else None
                current = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace_id,
                    DesignVersion.plan_id == plan_id, DesignVersion.item_id == entry["item_id"]).order_by(DesignVersion.revision.desc()))
                item = next(item for item in plan.items if item["id"] == entry["item_id"])
                if current:
                    asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id,
                        WorkspaceAsset.id == current.creative_direction.get("generated_asset_id"),
                        WorkspaceAsset.source == "external_generation", WorkspaceAsset.status == "ready"))
                    imported_id = current.id if asset else None
                entries.append({**entry, "status": "ready" if imported_id else run.status if run else "unavailable",
                    "last_error": run.last_error if run else "run_unavailable", "imported_design_id": imported_id,
                    "caption": current.caption if imported_id and current else None,
                    "scheduled_at": item["scheduled_at"], "platform": item["platform"],
                    "image_asset_id": asset.id if asset else None})
            return {"provider": generation["config"]["provider"], "entries": entries,
                "complete": bool(entries) and len(entries) == len([item for item in plan.items if item.get("status") != "rejected"])
                    and all(entry["status"] == "ready" for entry in entries)}

    def package(self, principal, workspace_id, plan_id):
        state = self.get(principal, workspace_id, plan_id)
        if not state["complete"]:
            raise CreativeError("images_pending", "Wait until every image is ready before downloading the week.")
        output = BytesIO()
        with self.sessions() as session, session.begin(), zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            set_workspace_context(session, workspace_id)
            plan = self._plan(session, workspace_id, plan_id)
            schedule = []
            for index, entry in enumerate(state["entries"], 1):
                design = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace_id,
                    DesignVersion.id == entry["imported_design_id"]))
                asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id,
                    WorkspaceAsset.id == entry["image_asset_id"]))
                current = session.scalar(select(DesignVersion).where(
                    DesignVersion.workspace_id == workspace_id, DesignVersion.plan_id == plan_id,
                    DesignVersion.item_id == entry["item_id"]).order_by(DesignVersion.revision.desc()))
                # Caption edits create a revision while retaining the complete artwork.
                # Export that saved copy only when it belongs to this exact image.
                if current and current.creative_direction.get("generated_asset_id") == asset.id:
                    design = current
                content = self.storage.read_bytes(asset.storage_key)
                if hashlib.sha256(content).hexdigest() != asset.sha256:
                    raise CreativeError("image_unavailable", "A generated image changed. Your other posts are saved.")
                archive.writestr(f"post-{index}/image.png", content)
                archive.writestr(f"post-{index}/caption.txt", design.caption)
                item = next(item for item in plan.items if item["id"] == entry["item_id"])
                schedule.append({"folder": f"post-{index}", "title": item["title"], "platform": item["platform"],
                                 "scheduled_at": item["scheduled_at"]})
            archive.writestr("schedule.json", json.dumps(schedule, indent=2, ensure_ascii=False))
        return output.getvalue()
