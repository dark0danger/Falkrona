"""A small owner survey, explicit uploaded assets, and a server-side design gate."""
from io import BytesIO
import json
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from .config import ExecutionMode, ModelProvider
from .database import set_workspace_context
from .models import AgentRun, BrandingSetup, BrandProfileVersion, WorkspaceAsset, Workspace, utc_now
from .phase3 import Phase3Error
from .phase4 import Phase4Error

KEYS = ("brand_name", "category", "audience", "style")
STARTER = {"questions": [
    {"key": "brand_name", "question": "What is your brand called?", "examples": ["Nile Coffee", "Luna Skincare"]},
    {"key": "category", "question": "What do you sell, and what makes your brand special?", "examples": ["Fresh coffee for busy mornings", "Gentle skincare made locally"]},
    {"key": "audience", "question": "Who would you most like to reach?", "examples": ["Young adults who love coffee", "Parents looking for thoughtful gifts"]},
    {"key": "style", "question": "What should your posts feel like?", "examples": ["Clean and simple: open space and calm colors", "Bold and playful: bright colors and lively shapes", "Elegant and warm: rich colors and thoughtful details"]},
]}


class SurveyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Literal["brand_name", "category", "audience", "style"]
    question: str = Field(min_length=1, max_length=250)
    examples: list[str] = Field(min_length=2, max_length=3)


class BrandingSurvey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[SurveyQuestion] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def required_questions(self):
        if tuple(q.key for q in self.questions) != KEYS or any(len(e) > 180 for q in self.questions for e in q.examples):
            raise ValueError("Use the four required questions in order, with short examples.")
        return self


def require_branding(session, workspace_id):
    row = session.get(BrandingSetup, workspace_id)
    profile = session.scalar(select(BrandProfileVersion).where(BrandProfileVersion.workspace_id == workspace_id,
        BrandProfileVersion.status == "confirmed").order_by(BrandProfileVersion.version.desc()))
    logo = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id,
        WorkspaceAsset.id == (row.logo_asset_id if row else None)))
    if (not row or not row.completed_at or not profile or
        any(not str(row.answers.get(k, "")).strip() or profile.fields.get(k) != row.answers[k] for k in KEYS) or
        not logo or logo.status != "ready" or logo.source != "upload" or
        not logo.metadata_json.get("verified_transparent_logo")):
        raise Phase3Error("branding_required", "Complete Branding and upload a logo with a transparent background before creating a design.")
    return row


class BrandingService:
    def __init__(self, sessions, accounts, storage, phase3, phase4, runtime):
        self.sessions, self.accounts, self.storage = sessions, accounts, storage
        self.phase3, self.phase4, self.runtime = phase3, phase4, runtime

    def get(self, principal, workspace_id):
        self.accounts.require_permission(principal, workspace_id, "read")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = session.get(BrandingSetup, workspace_id)
            try:
                require_branding(session, workspace_id)
                ready = True
            except Phase3Error:
                ready = False
            run = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id,
                AgentRun.dedupe_key.like("branding-survey:%")).order_by(AgentRun.created_at.desc()))
            survey = run.output.get("survey") if run and run.status == "completed" else None
            offline = self.runtime.execution_mode is ExecutionMode.OFFLINE_TEST
            return {"ready": ready, "answers": row.answers if row else {},
                "logo_asset_id": row.logo_asset_id if row else None,
                "reference_asset_id": row.reference_asset_id if row else None,
                "public_context_confirmed": bool(row and row.public_context_confirmed),
                "survey": survey or (STARTER if offline else None),
                "survey_source": "gemini" if survey else "offline_starter" if offline else "pending",
                "survey_run_id": run.id if run else None,
                "survey_status": run.status if run else None,
                "reports": "Every Monday after your first week, while Falkrona's worker is running."}

    def survey(self, principal, workspace_id, retry_failed=False):
        self.accounts.require_permission(principal, workspace_id, "write")
        if self.runtime.execution_mode is ExecutionMode.OFFLINE_TEST:
            return self.get(principal, workspace_id)
        if self.runtime.model_provider is not ModelProvider.GEMINI:
            raise Phase4Error("gemini_not_configured", "Gemini needs to be connected to prepare your brand questions.")
        key = "branding-survey:v1"
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            prior = session.scalar(select(AgentRun).where(AgentRun.workspace_id == workspace_id,
                AgentRun.dedupe_key.like(key + "%")).order_by(AgentRun.created_at.desc()))
            if prior:
                key = key + ":" + prior.id if retry_failed and prior.status in {"failed", "cancelled"} else prior.dedupe_key
        prompt = ("Make a friendly four-question branding survey for a small business owner using Facebook and Instagram. "
            "Ask brand name, what they sell and stand for, target audience, and preferred visual style, in that order. "
            "Use everyday English, no designer jargon. Give 2 or 3 short, concrete examples per question. "
            "For style explain the visual feel, such as clean and simple, bold and playful, elegant and warm. "
            "Do not request credentials, social asset access or personal customer information. Return only JSON matching: "
            + json.dumps(BrandingSurvey.model_json_schema()))
        self.phase4.create_run(principal, workspace_id, prompt, key, job_kind="branding.survey", checkpoint={"task": "branding.survey"})
        return self.get(principal, workspace_id)

    def upload(self, principal, workspace_id, role, filename, content, mime):
        self.accounts.require_permission(principal, workspace_id, "write")
        if role not in {"logo", "reference"}:
            raise Phase3Error("invalid_role", "Choose a logo or optional design reference.")
        from .phase3 import parse_upload
        parsed = parse_upload(filename, content, mime, max_upload_bytes=self.phase3._max_upload_bytes)
        if parsed.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise Phase3Error("invalid_image", "Upload a PNG or WebP logo, or a PNG, JPG or WebP reference.")
        if role == "logo":
            with Image.open(BytesIO(parsed.content)) as image:
                extrema = image.convert("RGBA").getchannel("A").getextrema()
            if extrema[0] != 0 or extrema[1] == 0:
                raise Phase3Error("transparent_logo_required", "Your logo needs a transparent background. Upload a PNG or WebP with visible artwork and transparent space around it.")
        asset = self.phase3.upload_asset(principal, workspace_id, filename, content, mime, purpose=role)
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id, WorkspaceAsset.id == asset["id"]))
            if role == "logo":
                row.metadata_json = {**row.metadata_json, "verified_transparent_logo": True}
        return asset

    def save(self, principal, workspace_id, answers, logo_asset_id, reference_asset_id=None, public_context_confirmed=False):
        self.accounts.require_permission(principal, workspace_id, "approve")
        normalized = {k: str(answers.get(k, "")).strip() for k in KEYS}
        if any(not v or len(v) > (200 if k == "brand_name" else 1000) for k, v in normalized.items()):
            raise Phase3Error("brand_details_required", "Answer the four short questions before saving your brand.")
        with self.sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            session.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
            for role, asset_id in (("logo", logo_asset_id), ("reference", reference_asset_id)):
                if role == "reference" and not asset_id:
                    continue
                asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id, WorkspaceAsset.id == asset_id))
                if (not asset or asset.status != "ready" or asset.source != "upload" or asset.mime_type not in {"image/png", "image/jpeg", "image/webp"} or
                    (role == "logo" and not asset.metadata_json.get("verified_transparent_logo"))):
                    raise Phase3Error("invalid_brand_asset", "Upload your transparent logo and optional reference in Branding.")
                asset.metadata_json = {**asset.metadata_json, "purpose": role}
            row = session.get(BrandingSetup, workspace_id)
            if not row:
                row = BrandingSetup(workspace_id=workspace_id)
                session.add(row)
            row.answers, row.logo_asset_id, row.reference_asset_id = normalized, logo_asset_id, reference_asset_id
            row.public_context_confirmed, row.updated_at = public_context_confirmed, utc_now()
            row.completed_at = row.completed_at or utc_now()
            profile = session.scalar(select(BrandProfileVersion).where(BrandProfileVersion.workspace_id == workspace_id,
                BrandProfileVersion.status == "confirmed").order_by(BrandProfileVersion.version.desc()))
            if not profile or any(profile.fields.get(k) != v for k, v in normalized.items()):
                version = (session.scalar(select(func.max(BrandProfileVersion.version)).where(BrandProfileVersion.workspace_id == workspace_id)) or 0) + 1
                session.add(BrandProfileVersion(workspace_id=workspace_id, version=version, status="confirmed",
                    fields={**(profile.fields if profile else {}), **normalized}, provenance={"source": "owner_branding_survey"},
                    created_by_user_id=principal.user_id, confirmed_at=utc_now()))
        return self.get(principal, workspace_id)
