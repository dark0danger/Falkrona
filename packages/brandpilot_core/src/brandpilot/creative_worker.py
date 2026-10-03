"""Durable, bounded creative planning worker. No fallback or automatic resubmission."""
from __future__ import annotations

import hashlib
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from sqlalchemy import select
from PIL import Image, ImageOps
from pydantic import ValidationError

from .config import ModelProvider
from .database import set_workspace_context
from .design_direction import DesignDirection, direction_schema
from .models import AgentRun, WeeklyPlan, WorkspaceAsset, utc_now
from .visual_planning import repeats_image_prompt
from .phase4 import Phase4Error, classify_and_redact
from .provider_policy import ModelRequest, admit_model_request


class HermesCreativeExecutor:
    def __init__(self, *, api_key: str, python_path: str = "", timeout_seconds=120):
        self.api_key, self.python_path, self.timeout_seconds = api_key, python_path, timeout_seconds

    def __call__(self, prompt, model, progress, schema=None, images=None):
        if not self.api_key:
            raise Phase4Error("missing_key", "The server has no Gemini API key.")
        root = Path(__file__).resolve().parents[4]
        checkout = root / ".dependencies" / "hermes-agent"
        pin = json.loads((root / "infra/hermes/pin.json").read_text(encoding="utf-8"))
        checked = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout,
                                 capture_output=True, text=True, check=True).stdout.strip()
        if checked != pin["commit"]:
            raise Phase4Error("runtime_pin_mismatch", "Prepare the pinned Hermes runtime first.")
        python = self.python_path
        if not python:
            install_key = hashlib.sha256(str(checkout.resolve()).encode()).hexdigest()[:16]
            facts = root / ".runtime/hermes/spike-bootstrap/installs" / install_key / "facts.json"
            if not facts.is_file():
                raise Phase4Error("runtime_unavailable", "Prepare Hermes or configure BRANDPILOT_HERMES_PYTHON.")
            environment = Path(json.loads(facts.read_text(encoding="utf-8"))["packages"]["venv"]["environment"])
            python = str(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        runtime = root / ".runtime" / "creative"
        runtime.mkdir(parents=True, exist_ok=True)
        # Fresh process and private home per request; never inherit app/database/social credentials.
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            home = Path(directory)
            (home / "config.yaml").write_text("_config_version: 12\nagent:\n  api_max_retries: 1\nfallback_providers: []\n", encoding="utf-8")
            output = home / "result.json"
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
            env.update(HERMES_HOME=str(home), GEMINI_API_KEY=self.api_key,
                       USERPROFILE=str(home), LOCALAPPDATA=str(home / "local"), APPDATA=str(home / "roaming"),
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            process = subprocess.Popen([python, str(root / "scripts/hermes_creative_runner.py"),
                                        str(checkout), str(output)], cwd=home, env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                process.stdin.write(json.dumps({"prompt": prompt, "model": model,
                                                "schema": schema or direction_schema(), "images": images or []}).encode())
                process.stdin.close()
                deadline = time.monotonic() + self.timeout_seconds
                while process.poll() is None:
                    progress()
                    if time.monotonic() >= deadline:
                        raise Phase4Error("provider_timeout", "Gemini planning timed out. The saved design is preserved.")
                    time.sleep(.5)
                if process.returncode or not output.is_file():
                    raise Phase4Error("provider_unavailable", "Hermes could not complete Gemini planning. Check the configured model and key.")
                result = json.loads(output.read_text(encoding="utf-8"))
                if result.get("error"):
                    raise Phase4Error(result["error"], "Gemini planning failed; the saved design is preserved.")
                return result
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


class CreativeDirectionHandler:
    def __init__(self, sessions, store, phase4, runtime, executor, scene_executor=None):
        self.sessions, self.store, self.phase4 = sessions, store, phase4
        self.runtime, self.executor = runtime, executor
        self.scene_executor = scene_executor  # Legacy injection only; never invoked by planning.

    def run(self, claim):
        workspace = claim.workspace_id
        def progress():
            self.store.heartbeat(claim.id, claim.lease_owner)
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace)
                row = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace,
                                                           AgentRun.job_id == claim.id))
                if not row or row.cancel_requested:
                    raise Phase4Error("cancelled", "Design planning was cancelled.")
        try:
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace)
                row = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace, AgentRun.job_id == claim.id))
                if not row:
                    raise Phase4Error("run_not_found", "Creative run is unavailable.")
                run_id, prompt, model = row.id, row.redacted_prompt, row.model
                visual_assets = row.checkpoint.get("visual_assets", [])
                checkpoint = dict(row.checkpoint)
                if row.status == "completed":
                    self.store.complete(claim.id, claim.lease_owner)
                    return
                if row.status != "queued" or row.cancel_requested:
                    raise Phase4Error("run_not_admissible", "The prior attempt requires review; it will not be resent.")
                admission = admit_model_request(self.runtime, ModelRequest(provider=ModelProvider.GEMINI,
                    contains_private_data=bool(row.prompt_classification.get("labels"))))
                if not admission.ok:
                    raise Phase4Error(str(admission.code), admission.message)
                if row.provider != "gemini":
                    raise Phase4Error("provider_mismatch", "Creative planning requires the selected Gemini provider.")
                if claim.kind == "creative.direction":
                    if checkpoint.get("pipeline_version") != 5:
                        raise Phase4Error("direction_stale", "Prepare a new Gemini direction for your image app.")
                row.status = "running"
            # Reserve conservatively before transport, including Hermes's system prompt allowance.
            self.phase4.admit_model_call(workspace, run_id, input_tokens=len(prompt.encode()) // 2 + 4000 + 2048 * len(visual_assets),
                                         output_tokens=4000)
            progress()
            if claim.kind == "planning.week":
                from .weekly_planning import GeminiWeek
                result = (self.executor(prompt, model, progress, schema=checkpoint.get("response_schema") or GeminiWeek.model_json_schema())
                          if isinstance(self.executor, HermesCreativeExecutor) else self.executor(prompt, model, progress))
                validated = {"plan": GeminiWeek.model_validate_json(result["text"]).model_dump()}
            elif claim.kind == "branding.survey":
                from .branding import BrandingSurvey
                result = (self.executor(prompt, model, progress, schema=BrandingSurvey.model_json_schema())
                          if isinstance(self.executor, HermesCreativeExecutor) else self.executor(prompt, model, progress))
                validated = {"survey": BrandingSurvey.model_validate_json(result["text"]).model_dump()}
            else:
                images = []
                if isinstance(self.executor, HermesCreativeExecutor):
                    # Small in-memory previews strip metadata; no remote asset URLs or original files reach Hermes.
                    storage = self.phase4._storage
                    with self.sessions() as session, session.begin():
                        set_workspace_context(session, workspace)
                        for visual in visual_assets:
                            asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace,
                                WorkspaceAsset.id == visual["id"], WorkspaceAsset.status == "ready", WorkspaceAsset.source == "upload"))
                            if not asset or asset.sha256 != visual["sha256"]:
                                raise Phase4Error("asset_changed", "Your brand images changed; prepare a new design idea.")
                            content = storage.read_bytes(asset.storage_key)
                            if hashlib.sha256(content).hexdigest() != asset.sha256:
                                raise Phase4Error("asset_changed", "A saved image is unavailable; upload it again.")
                            with Image.open(BytesIO(content)) as source:
                                preview = ImageOps.exif_transpose(source).convert("RGBA")
                                preview.thumbnail((512, 512))
                                preview.info.clear()
                                buffer = BytesIO(); preview.save(buffer, "PNG")
                            images.append({"role": visual["role"], "data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")})
                    result = self.executor(prompt, model, progress, images=images)
                else:
                    result = self.executor(prompt, model, progress)
                validated = {"direction": DesignDirection.model_validate_json(result["text"]).model_dump()}
                if not validated["direction"]["product_observation"]:
                    raise Phase4Error("product_identity_missing", "Gemini must distinguish the actual product from its photo's scenery.")
                requested_language = checkpoint["inputs"].get("language", "auto")
                if requested_language in {"ar", "en"} and validated["direction"]["language"] != requested_language:
                    raise Phase4Error("language_mismatch", "Gemini did not use your selected design language. Try again.")
                if requested_language in {"ar", "en"}:
                    copy = [validated["direction"][field] for field in ("headline", "cta", "caption")]
                    def has_selected_letters(text):
                        return any(character.isalpha() and (
                            "\u0600" <= character <= "\u06ff" if requested_language == "ar" else character.isascii())
                            for character in text)
                    if not all(has_selected_letters(text) for text in copy):
                        raise Phase4Error("language_mismatch", "Gemini did not write the copy in your selected language. Try again.")
            if result.get("model_calls", 0) != 1:
                raise Phase4Error("invalid_usage", "The runtime exceeded its single-call contract.")
            if claim.kind == "creative.direction":
                from .design_direction import context_snapshot
                with self.sessions() as session, session.begin():
                    set_workspace_context(session, workspace)
                    _, digest = context_snapshot(session, workspace, checkpoint["design_id"], checkpoint["inputs"], self.phase4._storage)
                    if digest != checkpoint["context_digest"]:
                        raise Phase4Error("direction_stale", "Your brand, product or brief changed; prepare a new direction.")
                validated.update(renderer="browser_image_app", image_api_calls=0)
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace)
                row = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace, AgentRun.id == run_id))
                if row.cancel_requested:
                    raise Phase4Error("cancelled", "Design planning was cancelled.")
                if claim.kind == "planning.week":
                    from .weekly_planning import GeminiWeek, apply_week
                    validated["plan_id"] = apply_week(session, workspace, row, GeminiWeek.model_validate(validated["plan"]), self.phase4._storage)
                if claim.kind == "creative.direction":
                    # Serialize the final comparison so concurrent workers cannot save duplicate prompts.
                    from .models import DesignVersion
                    design = session.scalar(select(DesignVersion).where(DesignVersion.workspace_id == workspace,
                        DesignVersion.id == checkpoint["design_id"]))
                    plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace,
                        WeeklyPlan.id == design.plan_id).with_for_update())
                    peer_ids = [entry["run_id"] for entry in plan.strategy.get("generation", {}).get("entries", [])
                                if entry["item_id"] != design.item_id]
                    peers = session.scalars(select(AgentRun).where(AgentRun.workspace_id == workspace,
                        AgentRun.id.in_(peer_ids), AgentRun.status == "completed")).all()
                    if any(peer.output.get("direction") and repeats_image_prompt(validated["direction"], peer.output["direction"]) for peer in peers):
                        raise Phase4Error("repeated_visual_direction", "Gemini repeated another post's composition. Continue generation to rewrite this prompt.")
                    previous = checkpoint.get("campaign", {}).get("previous_directions", [])
                    if any(repeats_image_prompt(validated["direction"], old) for old in previous):
                        raise Phase4Error("repeated_visual_direction", "Gemini repeated the rejected idea. Continue generation to write a different idea.")
                row.output = {**validated, "usage": result.get("usage", {}), "provenance": "gemini_via_hermes"}
                row.checkpoint = {**row.checkpoint, "stage": "awaiting_image_app" if claim.kind == "creative.direction" else "completed"}
                row.status, row.completed_at = "completed", utc_now()
            self.store.complete(claim.id, claim.lease_owner)
        except (Phase4Error, ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
            code = getattr(exc, "code", "invalid_direction")
            with self.sessions() as session, session.begin():
                set_workspace_context(session, workspace)
                row = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace, AgentRun.job_id == claim.id))
                if row:
                    row.status = "cancelled" if code == "cancelled" else "failed"
                    if isinstance(exc, ValidationError):
                        row.output = {**row.output, "validation_errors": [
                            {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"][:200]}
                            for error in exc.errors(include_input=False, include_url=False)[:8]]}
                    row.last_error, row.completed_at = code, utc_now()
                    if claim.kind == "planning.week" and hasattr(exc, "code"):
                        row.output = {**row.output, "failure_message": str(exc)[:400]}
            self.store.fail(claim.id, claim.lease_owner, code, retryable=False)
