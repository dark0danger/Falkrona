"""FastAPI bootstrap with authenticated workspace boundaries."""

from __future__ import annotations

from typing import Literal

from contextlib import asynccontextmanager
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import File, FastAPI, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from brandpilot.accounts import (
    AccountService,
    AuthenticationError,
    AuthorizationError,
    Principal,
    RateLimitError,
)
from brandpilot.analytics import AnalyticsError, AnalyticsService
from brandpilot.branding import BrandingService
from brandpilot.creative import CreativeError, CreativeService
from brandpilot.design_direction import DirectionService
from brandpilot.browser_images import BrowserImageService
from brandpilot.database import build_engine, build_session_factory
from brandpilot.health import HealthService
from brandpilot.jobs import JobStore
from brandpilot.learning import LearningError, LearningService
from brandpilot.logging_utils import configure_logging
from brandpilot.phase4 import Phase4Error, Phase4Service
from brandpilot.phase3 import Phase3Error, Phase3Service
from brandpilot.planning import PlanningError, PlanningService
from brandpilot.weekly_planning import WeeklyPlannerService
from brandpilot.plan_generation import PlanGenerationService
from brandpilot.publication import PublicationError, PublicationService
from brandpilot.scheduled_publishing import ScheduledPublishing
from brandpilot.results import ResultsService
from brandpilot.security import (
    AssetDownloadSigner,
    CredentialCipher,
    InvalidCredential,
    RunCredentialSigner,
)
from brandpilot.settings import AppSettings
from brandpilot.social import MetaConfig, MetaTransport, SocialError, SocialService
from brandpilot.storage import LocalStorage, StorageError


logger = logging.getLogger("brandpilot.api")


class BrandingSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, str]
    logo_asset_id: str
    reference_asset_id: str | None = None
    public_context_confirmed: bool = False


class BrandingSurveyRequest(BaseModel):
    retry_failed: bool = False


class BrowserPacketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(pattern="^(gemini|chatgpt)$")
    consent: bool = False


class MetaAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    publishing: bool = False


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")
    payload: dict = Field(default_factory=dict)
    dedupe_key: str = Field(min_length=1, max_length=200)
    max_attempts: int = Field(default=3, ge=1, le=20)


class OwnerSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    workspace_name: str = Field(min_length=1, max_length=160)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class WorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)


class MemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    role: str = Field(pattern=r"^(owner|editor|analyst)$")


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    secret: str = Field(min_length=1, max_length=10000)


class ToolAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=36, max_length=36)
    job_id: str = Field(min_length=36, max_length=36)
    operation: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,99}$")


class UrlImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    dedupe_key: str = Field(min_length=1, max_length=200)


class ProfileProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict = Field(min_length=1)


class OnboardingTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    answer: str = Field(min_length=1, max_length=4000)
    confirmed: bool = False


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=20_000)
    dedupe_key: str = Field(min_length=1, max_length=160)


class AgentArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=36, max_length=36)
    job_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20_000)


class AgentContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=36, max_length=36)
    job_id: str = Field(min_length=36, max_length=36)


class SelectSocialAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=160, pattern=r"^(ig:)?[0-9]+$")


class SocialSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dedupe_key: str = Field(min_length=1, max_length=160)


class MetricObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=36, max_length=36)
    metric: str
    traffic: str
    status: str
    value: int | None = Field(default=None, ge=0)
    window_start: datetime
    window_end: datetime
    source_ref: str = Field(min_length=1, max_length=200)


class AuditCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_id: str = Field(min_length=36, max_length=36)
    source_ref: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4000)


class PlanGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date
    goal: str
    platforms: list[str] = Field(min_length=1, max_length=2)
    cadence: int | None = Field(default=None, ge=1, le=5)
    language: Literal["ar", "en"] = "en"
    public_context_confirmed: bool = False


class PlanImagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_asset_id: str = Field(min_length=36, max_length=36)
    product_description: str = Field(default="", max_length=2000)
    language: str = Field(default="auto", pattern=r"^(auto|ar|en)$")
    provider: str = Field(pattern="^(gemini|chatgpt)$")
    consent: bool = False


class PlanPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=36, max_length=36)
    design_ids: list[str] = Field(min_length=1, max_length=5)
    facts_reviewed: bool = False


class PlanRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_id: str = Field(min_length=36, max_length=36)


class PostScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    previous_scheduled_at: str = Field(min_length=16, max_length=40)


class StrategyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str | None = Field(default=None, min_length=1, max_length=200)
    direction: str | None = Field(default=None, min_length=1, max_length=1000)


class PlanItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_at: str | None = None
    platform: str | None = None
    format: str | None = None
    purpose: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    concept: str | None = Field(default=None, min_length=1, max_length=4000)
    cta: str | None = Field(default=None, min_length=1, max_length=300)
    rationale: str | None = Field(default=None, min_length=1, max_length=1000)
    status: str | None = None
    locked: bool | None = None


class DesignRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene: dict
    caption: str = Field(max_length=4000)


class WeeklyCycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_start: date
    refresh: bool = False


class DesignRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_asset_id: str = Field(min_length=36, max_length=36)
    photo_asset_id: str = Field(min_length=36, max_length=36)
    product_image_confirmed: bool = False
    logo_includes_name: bool = False
    language: str = Field(default="auto", pattern=r"^(auto|ar|en)$")
    direction_run_id: str | None = None
    product_description: str = Field(default="", max_length=2000)


class DesignDirectionRequest(DesignRegenerateRequest):
    public_context_confirmed: bool = False
    retry_failed: bool = False


class PublicationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(pattern=r"^(facebook_pages|instagram)$")
    account_id: str = Field(min_length=1, max_length=160)
    connection_id: str | None = None
    schedule_local: str = Field(min_length=16, max_length=32)
    fold: int | None = Field(default=None, ge=0, le=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    facts_reviewed: bool


class DesignFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1, max_length=4000)
    interpretation: str = Field(min_length=1, max_length=1000)
    category: str
    kind: str = "preference"
    scope: str


class FeedbackDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supersedes_id: str | None = None


def create_app(
    settings: AppSettings,
    *,
    engine: Engine | None = None,
    storage: LocalStorage | None = None,
    meta_transport: MetaTransport | None = None,
) -> FastAPI:
    configure_logging(settings.log_level)
    database = engine or build_engine(settings.database_url, role="brandpilot_app")
    local_storage = storage or LocalStorage(settings.storage_root)
    sessions = build_session_factory(database)
    jobs = JobStore(sessions, lease_seconds=settings.job_lease_seconds)
    credential_cipher = CredentialCipher(
        {1: settings.credential_encryption_key}, current_version=1
    )
    accounts = AccountService(
        sessions,
        app_secret_key=settings.app_secret_key,
        credential_cipher=credential_cipher,
        session_ttl_seconds=settings.session_ttl_seconds,
        login_window_seconds=settings.login_window_seconds,
        login_max_attempts=settings.login_max_attempts,
    )
    run_credentials = RunCredentialSigner(settings.app_secret_key)
    download_signer = AssetDownloadSigner(settings.app_secret_key)
    phase3 = Phase3Service(
        sessions,
        accounts,
        local_storage,
        max_upload_bytes=settings.max_upload_bytes,
        max_archive_bytes=settings.max_archive_bytes,
        max_rows=settings.max_import_rows,
        offline=settings.runtime.execution_mode.value == "offline_test",
    )
    phase4 = Phase4Service(
        sessions,
        accounts,
        local_storage,
        settings.runtime,
        gemini_model=settings.gemini_model,
        openai_model=settings.openai_model,
        max_model_calls=settings.agent_max_model_calls,
        max_input_tokens=settings.agent_max_input_tokens,
        max_output_tokens=settings.agent_max_output_tokens,
    )
    social = SocialService(
        sessions, accounts, credential_cipher,
        MetaConfig(
            app_id=settings.meta_app_id,
            app_secret=settings.meta_app_secret,
            callback_url=settings.meta_callback_url,
            graph_version=settings.meta_graph_version,
        ),
        local_storage,
        offline=settings.runtime.execution_mode.value == "offline_test",
        max_upload_bytes=settings.max_upload_bytes,
        max_rows=settings.max_import_rows,
        transport=meta_transport,
        live_publish_enabled=settings.runtime.execution_mode.value != "offline_test",
    )
    analytics = AnalyticsService(sessions, accounts)
    planning = PlanningService(sessions, accounts)
    weekly_planner = WeeklyPlannerService(sessions, accounts, phase4, settings.runtime)
    creative = CreativeService(sessions, accounts, local_storage, runtime=settings.runtime)
    directions = DirectionService(sessions, accounts, local_storage, phase4, settings.runtime)
    browser_images = BrowserImageService(sessions, accounts, local_storage, creative)
    plan_images = PlanGenerationService(sessions, accounts, creative, directions, local_storage)
    learning = LearningService(sessions, accounts)
    publication = PublicationService(sessions, accounts, creative, local_storage)
    publishing = ScheduledPublishing(sessions, accounts, planning, publication, social,
        enabled=settings.runtime.execution_mode.value != "offline_test" and social.meta_read_available)
    results = ResultsService(sessions, accounts, planning, publication)
    branding = BrandingService(sessions, accounts, local_storage, phase3, phase4, settings.runtime)
    health = HealthService.from_resources(database, local_storage)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.info("API starting in execution_mode=%s", settings.runtime.execution_mode)
        yield
        if engine is None:
            database.dispose()

    app = FastAPI(
        title="Falkrona API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = database
    app.state.storage = local_storage
    app.state.jobs = jobs
    app.state.accounts = accounts
    app.state.run_credentials = run_credentials
    app.state.download_signer = download_signer
    app.state.phase3 = phase3
    app.state.phase4 = phase4
    app.state.branding = branding
    app.state.results = results
    app.state.social = social
    app.state.analytics = analytics
    app.state.planning = planning
    app.state.creative = creative
    app.state.learning = learning
    app.state.publication = publication
    app.state.publishing = publishing

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unavailable")
        logger.exception("Unhandled API error", extra={"request_id": request_id})
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                    "request_id": request_id,
                }
            },
        )

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        report = health.ready()
        return JSONResponse(
            status_code=200 if report.healthy else 503,
            content={"status": report.status, "components": report.components},
        )

    @app.get("/api/status")
    def status() -> dict:
        return {
            "browser_helper_protocol": 1,
            "creative_renderer": "browser_image_app",
            "execution_mode": settings.runtime.execution_mode,
            "model_provider": settings.runtime.model_provider,
            "paid_calls_enabled": settings.runtime.openai_paid_enabled,
            "image_api_enabled": settings.runtime.image_api_enabled,
            "creative_generation_ready": bool(settings.runtime.execution_mode.value != "offline_test"
                and settings.runtime.model_provider.value == "gemini" and settings.gemini_model and settings.gemini_api_key),
        }

    def current_principal(request: Request) -> Principal:
        try:
            return accounts.authenticate(request.cookies.get("brandpilot_session"))
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=401,
                detail={"code": "authentication_required", "message": str(exc)},
            ) from exc

    def require_csrf(request: Request, principal: Principal) -> None:
        try:
            accounts.require_csrf(principal, request.headers.get("X-CSRF-Token"))
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "csrf_rejected", "message": str(exc)},
            ) from exc

    def require_workspace(
        principal: Principal, workspace_id: str, permission: str
    ) -> str:
        try:
            return accounts.require_permission(principal, workspace_id, permission)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc

    def phase3_error(exc: Phase3Error) -> HTTPException:
        status = 404 if exc.code.endswith("_not_found") else 422
        return HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        )

    def social_error(exc: SocialError) -> HTTPException:
        status = 404 if exc.code == "connection_not_found" else 409 if exc.code in {
            "state_replayed", "selection_unavailable", "account_already_connected",
        } else 503 if exc.code in {"not_configured", "external_disabled", "provider_unavailable"} else 422
        return HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        )

    @app.post("/api/v1/setup/owner", status_code=201)
    def setup_owner(
        body: OwnerSetupRequest,
        setup_token: str = Header(default="", alias="X-Setup-Token"),
    ) -> dict:
        try:
            user_id, workspace_id = accounts.setup_owner(
                body.email,
                body.password,
                body.workspace_name,
                supplied_token=setup_token,
                expected_token=settings.owner_setup_token,
            )
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "owner_setup_denied", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_owner_setup", "message": str(exc)},
            ) from exc
        return {"user_id": user_id, "workspace_id": workspace_id}

    @app.post("/api/v1/session")
    def create_session(body: LoginRequest, request: Request, response: Response) -> dict:
        client_id = request.client.host if request.client else "unknown"
        try:
            grant = accounts.login(body.email, body.password, client_id)
        except RateLimitError as exc:
            raise HTTPException(
                status_code=429,
                detail={"code": "login_rate_limited", "message": str(exc)},
            ) from exc
        except (AuthenticationError, ValueError) as exc:
            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_credentials", "message": str(exc)},
            ) from exc
        response.set_cookie(
            "brandpilot_session",
            grant.token,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="strict",
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return {
            "user": {"id": grant.principal.user_id, "email": grant.principal.email},
            "csrf_token": grant.csrf_token,
            "expires_at": grant.expires_at.isoformat(),
        }

    @app.delete("/api/v1/session", status_code=204)
    def delete_session(request: Request) -> Response:
        principal = current_principal(request)
        require_csrf(request, principal)
        accounts.revoke_session(principal)
        response = Response(status_code=204)
        response.delete_cookie("brandpilot_session", path="/")
        return response

    @app.get("/api/v1/me")
    def me(request: Request) -> dict:
        principal = current_principal(request)
        return {
            "id": principal.user_id,
            "email": principal.email,
            "workspaces": accounts.memberships(principal),
        }

    @app.get("/api/v1/session/csrf")
    def refresh_csrf(request: Request, response: Response) -> dict:
        principal = current_principal(request)
        response.headers["Cache-Control"] = "no-store"
        return {"csrf_token": accounts.rotate_csrf(principal)}

    @app.post("/api/v1/workspaces", status_code=201)
    def create_workspace(body: WorkspaceRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        return {"workspace_id": accounts.create_workspace(principal, body.name)}

    @app.post("/api/v1/workspaces/{workspace_id}/members", status_code=201)
    def add_member(workspace_id: str, body: MemberRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            membership_id = accounts.add_member(
                principal, workspace_id, body.email, body.role
            )
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_membership", "message": str(exc)},
            ) from exc
        return {"membership_id": membership_id, "role": body.role}

    @app.delete(
        "/api/v1/workspaces/{workspace_id}/members/{membership_id}", status_code=204
    )
    def revoke_member(workspace_id: str, membership_id: str, request: Request) -> Response:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            accounts.revoke_member(principal, workspace_id, membership_id)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "membership_not_found", "message": str(exc)},
            ) from exc
        return Response(status_code=204)

    @app.post("/api/v1/workspaces/{workspace_id}/credentials", status_code=201)
    def store_credential(
        workspace_id: str, body: CredentialRequest, request: Request
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            credential_id = accounts.store_credential(
                principal, workspace_id, body.provider, body.secret
            )
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc
        return {"credential_id": credential_id, "provider": body.provider}

    @app.get("/api/v1/workspaces/{workspace_id}/social/connections")
    def social_connections(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return {"connections": social.list_connections(principal, workspace_id)}
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/social/capabilities")
    def social_capabilities(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_workspace(principal, workspace_id, "read")
        return {"meta_read_available": social.meta_read_available}

    @app.post("/api/v1/workspaces/{workspace_id}/social/meta/authorize")
    def begin_meta_authorization(workspace_id: str, request: Request, response: Response,
                                 body: MetaAuthorizationRequest | None = None) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            grant = social.begin(principal, workspace_id, publishing=bool(body and body.publishing))
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc
        response.set_cookie(
            "falkrona_meta_oauth", grant["browser_cookie"], httponly=True,
            secure=settings.session_cookie_secure, samesite="lax", max_age=600,
            path="/api/v1/social/meta/callback",
        )
        response.headers["Cache-Control"] = "no-store"
        return {"authorization_url": grant["authorization_url"]}

    @app.get("/api/v1/social/meta/callback")
    def meta_callback(request: Request, state: str = "", code: str | None = None, error: str | None = None) -> Response:
        try:
            outcome = social.callback(state, request.cookies.get("falkrona_meta_oauth"), code, error)
        except SocialError as exc:
            raise social_error(exc) from exc
        response = RedirectResponse(f"/?social={outcome}", status_code=303)
        response.delete_cookie("falkrona_meta_oauth", path="/api/v1/social/meta/callback")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/workspaces/{workspace_id}/social/connections/{connection_id}/accounts")
    def meta_accounts(workspace_id: str, connection_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return {"accounts": social.managed_accounts(principal, workspace_id, connection_id)}
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/social/connections/{connection_id}/account")
    def select_meta_account(workspace_id: str, connection_id: str, body: SelectSocialAccountRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return social.select_account(principal, workspace_id, connection_id, body.account_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.delete("/api/v1/workspaces/{workspace_id}/social/connections/{connection_id}")
    def disconnect_social(workspace_id: str, connection_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return social.disconnect(principal, workspace_id, connection_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/social/imports", status_code=201)
    async def create_social_import(
        workspace_id: str, request: Request, provider: str = Form(...),
        account_id: str = Form(...), dedupe_key: str = Form(...), file: UploadFile = File(...),
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return social.create_manual_import(
                principal, workspace_id, provider, account_id,
                file.filename or "import.csv", await file.read(settings.max_upload_bytes + 1),
                dedupe_key,
            )
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/social/connections/{connection_id}/sync", status_code=202)
    def queue_social_sync(
        workspace_id: str, connection_id: str, body: SocialSyncRequest, request: Request,
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return social.queue_sync(principal, workspace_id, connection_id, body.dedupe_key)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/social/imports/{import_id}/confirm")
    def confirm_social_import(workspace_id: str, import_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return social.confirm_manual_import(principal, workspace_id, import_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except SocialError as exc:
            raise social_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/social/posts")
    def list_social_posts(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return {"posts": social.list_posts(principal, workspace_id)}
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/social/posts/export")
    def export_social_posts(workspace_id: str, request: Request) -> StreamingResponse:
        principal = current_principal(request)
        try:
            chunks = social.export_posts_csv(principal, workspace_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        return StreamingResponse(
            chunks, media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="falkrona-social-posts.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/v1/workspaces/{workspace_id}/analytics/audit")
    def social_audit(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return analytics.audit(principal, workspace_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/analytics/evidence/{evidence_id}")
    def audit_evidence(workspace_id: str, evidence_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return analytics.evidence(principal, workspace_id, evidence_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except AnalyticsError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/analytics/metrics", status_code=201)
    def add_metric(workspace_id: str, body: MetricObservationRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return analytics.record_metric(principal, workspace_id, **body.model_dump())
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except AnalyticsError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/analytics/comments", status_code=201)
    def add_audit_comment(workspace_id: str, body: AuditCommentRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return analytics.record_comment(principal, workspace_id, **body.model_dump())
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except AnalyticsError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/analytics/{kind}/{evidence_id}/invalidate")
    def invalidate_audit_evidence(workspace_id: str, kind: str, evidence_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return analytics.invalidate(principal, workspace_id, kind, evidence_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except AnalyticsError as exc:
            raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/assets", status_code=201)
    async def upload_asset(
        workspace_id: str,
        request: Request,
        file: UploadFile = File(...),
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.upload_asset(
                principal,
                workspace_id,
                file.filename or "upload",
                await file.read(settings.max_upload_bytes + 1),
                file.content_type,
            )
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/assets")
    def list_assets(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        return {"assets": phase3.list_assets(principal, workspace_id)}

    @app.post("/api/v1/workspaces/{workspace_id}/imports", status_code=201)
    async def create_import(
        workspace_id: str,
        request: Request,
        dedupe_key: str = Form(...),
        file: UploadFile = File(...),
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.create_import(
                principal,
                workspace_id,
                file.filename or "import",
                await file.read(settings.max_upload_bytes + 1),
                file.content_type,
                dedupe_key,
            )
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/imports/url", status_code=201)
    def create_url_import(
        workspace_id: str, body: UrlImportRequest, request: Request
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.create_url_import(
                principal, workspace_id, body.url, body.dedupe_key
            )
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/imports/{import_id}")
    def get_import(workspace_id: str, import_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return phase3.get_import(principal, workspace_id, import_id)
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/imports/{import_id}/confirm")
    def confirm_import(workspace_id: str, import_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.confirm_import(principal, workspace_id, import_id)
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/brand/proposals", status_code=201)
    def create_profile_proposal(
        workspace_id: str, body: ProfileProposalRequest, request: Request
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.profile_proposal(principal, workspace_id, body.fields)
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/brand")
    def get_profile(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        return {"profile": phase3.current_profile(principal, workspace_id)}

    def planning_error(exc: PlanningError) -> HTTPException:
        return HTTPException(status_code=404 if exc.code in {"plan_not_found", "item_not_found"} else
                             409 if exc.code in {"plan_approved", "stale_plan", "profile_changed"} else 422,
                             detail={"code": exc.code, "message": str(exc)})

    @app.get("/api/v1/workspaces/{workspace_id}/plans")
    def current_plan(workspace_id: str, week_start: date, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return planning.current(principal, workspace_id, week_start)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans", status_code=201)
    def generate_plan(workspace_id: str, body: PlanGenerateRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            if settings.runtime.execution_mode.value != "offline_test":
                return JSONResponse(status_code=202, content=weekly_planner.start(principal, workspace_id, **body.model_dump()))
            values = body.model_dump(exclude={"public_context_confirmed", "language"})
            return planning.generate(principal, workspace_id, **values)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PlanningError as exc:
            raise planning_error(exc) from exc
        except Phase4Error as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/generate-images")
    def generate_plan_images(workspace_id: str, plan_id: str, body: PlanImagesRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return plan_images.start(principal, workspace_id, plan_id,
                {"photo_asset_id": body.photo_asset_id, "product_description": body.product_description,
                 "language": body.language}, body.provider, body.consent)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc
        except Phase4Error as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/images")
    def get_plan_images(workspace_id: str, plan_id: str, request: Request):
        try:
            return plan_images.get(current_principal(request), workspace_id, plan_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.delete("/api/v1/workspaces/{workspace_id}/plans/{plan_id}")
    @app.delete("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/posts/{item_id}")
    def delete_plan_or_post(workspace_id: str, plan_id: str, request: Request, item_id: str | None = None):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return plan_images.remove(principal, workspace_id, plan_id, item_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/restore")
    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/posts/{item_id}/restore")
    def restore_plan_or_post(workspace_id: str, plan_id: str, request: Request, item_id: str | None = None):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return plan_images.remove(principal, workspace_id, plan_id, item_id, restore=True)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/posts/{item_id}/regenerate")
    def regenerate_plan_post(workspace_id: str, plan_id: str, item_id: str, body: PlanRegenerateRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return plan_images.regenerate(principal, workspace_id, plan_id, item_id, body.design_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc
        except Phase4Error as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.patch("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/posts/{item_id}/schedule")
    def reschedule_plan_post(workspace_id: str, plan_id: str, item_id: str, body: PostScheduleRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return plan_images.reschedule(principal, workspace_id, plan_id, item_id, body.scheduled_at, body.previous_scheduled_at)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/images/package")
    def get_plan_images_package(workspace_id: str, plan_id: str, request: Request):
        try:
            return Response(content=plan_images.package(current_principal(request), workspace_id, plan_id),
                media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="Falkrona-week.zip"'})
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.patch("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/strategy")
    def update_plan_strategy(workspace_id: str, plan_id: str, body: StrategyUpdateRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return planning.update_strategy(principal, workspace_id, plan_id, **body.model_dump())
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PlanningError as exc:
            raise planning_error(exc) from exc

    @app.patch("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/items/{item_id}")
    def update_plan_item(workspace_id: str, plan_id: str, item_id: str, body: PlanItemUpdateRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return planning.update_item(principal, workspace_id, plan_id, item_id, body.model_dump(exclude_unset=True))
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PlanningError as exc:
            raise planning_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/approve")
    def approve_plan(workspace_id: str, plan_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return planning.approve(principal, workspace_id, plan_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PlanningError as exc:
            raise planning_error(exc) from exc

    def creative_error(exc: CreativeError) -> HTTPException:
        return HTTPException(
            status_code=404 if exc.code in {"design_not_found", "plan_not_found"} else
                        409 if exc.code in {"stale_design", "render_conflict", "render_incomplete"} else 422,
            detail={"code": exc.code, "message": str(exc)},
        )

    def learning_error(exc: LearningError) -> HTTPException:
        return HTTPException(status_code=404 if exc.code.endswith("not_found") else
                             409 if exc.code in {"feedback_decided", "preference_conflict",
                                                "stale_replacement", "preference_inactive"} else 422,
                             detail={"code": exc.code, "message": str(exc)})

    @app.get("/api/v1/workspaces/{workspace_id}/designs/{version_id}/feedback")
    def list_design_feedback(workspace_id: str, version_id: str, request: Request) -> list[dict]:
        principal = current_principal(request)
        try:
            return learning.list_feedback(principal, workspace_id, version_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/feedback", status_code=201)
    def submit_design_feedback(workspace_id: str, version_id: str, body: DesignFeedbackRequest,
                               request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return learning.submit(principal, workspace_id, version_id, **body.model_dump())
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except LearningError as exc:
            raise learning_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/feedback/{feedback_id}/approve")
    def approve_design_feedback(workspace_id: str, feedback_id: str, body: FeedbackDecisionRequest,
                                request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return learning.decide(principal, workspace_id, feedback_id, approve=True,
                                   supersedes_id=body.supersedes_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except LearningError as exc:
            raise learning_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/feedback/{feedback_id}/reject")
    def reject_design_feedback(workspace_id: str, feedback_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return learning.decide(principal, workspace_id, feedback_id, approve=False)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except LearningError as exc:
            raise learning_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/learning")
    def list_learning(workspace_id: str, request: Request) -> list[dict]:
        principal = current_principal(request)
        try:
            return learning.list_preferences(principal, workspace_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/learning/{preference_id}/revert")
    def revert_learning(workspace_id: str, preference_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return learning.revert(principal, workspace_id, preference_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except LearningError as exc:
            raise learning_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/branding")
    def branding_status(workspace_id: str, request: Request):
        return branding.get(current_principal(request), workspace_id)

    @app.post("/api/v1/workspaces/{workspace_id}/branding/survey", status_code=202)
    def branding_survey(workspace_id: str, body: BrandingSurveyRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return branding.survey(principal, workspace_id, body.retry_failed)
        except Phase4Error as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/branding/assets/{role}", status_code=201)
    async def branding_asset(workspace_id: str, role: str, request: Request, file: UploadFile = File(...)):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return branding.upload(principal, workspace_id, role, file.filename or "upload.png",
                await file.read(settings.max_upload_bytes + 1), file.content_type)
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.put("/api/v1/workspaces/{workspace_id}/branding")
    def save_branding(workspace_id: str, body: BrandingSaveRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return branding.save(principal, workspace_id, **body.model_dump())
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/results")
    def weekly_results(workspace_id: str, request: Request):
        try:
            return {"reports": results.list(current_principal(request), workspace_id)}
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/results/cycle", status_code=201)
    def weekly_cycle(workspace_id: str, body: WeeklyCycleRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return results.cycle(principal, workspace_id, body.week_start, refresh=body.refresh)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except PlanningError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/items/{item_id}/design")
    def latest_design(workspace_id: str, plan_id: str, item_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return creative.latest(principal, workspace_id, plan_id, item_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/items/{item_id}/design", status_code=201)
    def create_design(workspace_id: str, plan_id: str, item_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return creative.create(principal, workspace_id, plan_id, item_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/designs/{version_id}")
    def get_design(workspace_id: str, version_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return creative.get(principal, workspace_id, version_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/revisions", status_code=201)
    def revise_design(workspace_id: str, version_id: str, body: DesignRevisionRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return creative.revise(principal, workspace_id, version_id, body.scene, body.caption)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/regenerate", status_code=201)
    def regenerate_design(workspace_id: str, version_id: str,
                          body: DesignRegenerateRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return creative.regenerate(principal, workspace_id, version_id,
                                       body.logo_asset_id, body.photo_asset_id, body.language,
                                       body.product_image_confirmed, body.logo_includes_name,
                                       body.direction_run_id, body.product_description)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/direction", status_code=202)
    def prepare_design_direction(workspace_id: str, version_id: str, body: DesignDirectionRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return directions.start(principal, workspace_id, version_id,
                body.model_dump(exclude={"direction_run_id", "public_context_confirmed", "retry_failed"}),
                public_context_confirmed=body.public_context_confirmed, retry_failed=body.retry_failed)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc
        except Phase4Error as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}/browser-packet")
    def browser_packet(workspace_id: str, run_id: str, body: BrowserPacketRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return browser_images.packet(principal, workspace_id, run_id, body.provider, body.consent)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}/browser-image", status_code=201)
    async def browser_image(workspace_id: str, run_id: str, request: Request,
                            provider: str = Form(...), nonce: str = Form(...), file: UploadFile = File(...)):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return browser_images.import_image(principal, workspace_id, run_id, provider, nonce,
                                               await file.read(15_000_001))
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.get("/api/v1/browser-helper")
    def browser_helper_download(request: Request):
        current_principal(request)
        from pathlib import Path
        from io import BytesIO
        import zipfile
        root = Path(__file__).resolve().parents[2] / "apps/browser-helper"
        stream = BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in ("manifest.json", "popup.html", "popup.js", "background.js", "bridge.js", "provider-dom.js", "provider.js", "README.md"):
                archive.writestr(name, (root / name).read_bytes())
        return Response(stream.getvalue(), media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="Falkrona-Browser-Helper.zip"', "Cache-Control": "private, no-store"})

    @app.get("/api/v1/workspaces/{workspace_id}/assets/{asset_id}/reference-traits")
    def reference_traits(workspace_id: str, asset_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return creative.inspect_reference(principal, workspace_id, asset_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/slides/{slide_id}/renders")
    async def record_design_render(workspace_id: str, version_id: str, slide_id: str,
                                   request: Request, preset: str = Form(...), file: UploadFile = File(...)) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return creative.record_png(principal, workspace_id, version_id, slide_id,
                                       preset, await file.read(15_000_001))
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/designs/{version_id}/package")
    def design_package(workspace_id: str, version_id: str, request: Request) -> Response:
        principal = current_principal(request)
        try:
            content = creative.package(principal, workspace_id, version_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="falkrona-design-{version_id}.zip"',
            "Cache-Control": "private, no-store",
        })

    def publication_error(exc: PublicationError) -> HTTPException:
        return HTTPException(
            status_code=404 if exc.code.endswith("not_found") else
                        409 if exc.code in {"plan_unapproved", "plan_stale", "brief_unapproved",
                                             "design_stale", "facts_stale", "offer_expired",
                                             "product_unavailable", "timezone_changed", "outside_plan_week",
                                             "connection_reauth_required", "render_incomplete",
                                             "render_stale", "render_missing", "render_corrupt",
                                             "approval_inactive", "approval_stale", "request_conflict",
                                             "destination_conflict", "attempt_missing", "missed_schedule"} else 422,
            detail={"code": exc.code, "message": str(exc)},
        )

    @app.get("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/publishing")
    def plan_publishing(workspace_id: str, plan_id: str, request: Request):
        try:
            return publishing.list(current_principal(request), workspace_id, plan_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied"}) from exc
        except (PublicationError, PlanningError) as exc:
            raise publication_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/approve-and-schedule")
    def approve_and_schedule(workspace_id: str, plan_id: str, body: PlanPublicationRequest, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return publishing.approve(principal, workspace_id, plan_id, body.connection_id, body.design_ids, body.facts_reviewed)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied"}) from exc
        except (PublicationError, PlanningError, SocialError, StorageError) as exc:
            raise HTTPException(status_code=409, detail={"code": getattr(exc, "code", "image_unavailable"), "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/plans/{plan_id}/cancel-schedule")
    def cancel_plan_schedule(workspace_id: str, plan_id: str, request: Request):
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return publishing.cancel(principal, workspace_id, plan_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied"}) from exc
        except (PublicationError, PlanningError) as exc:
            raise publication_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/designs/{version_id}/publication-approvals")
    def list_publication_approvals(workspace_id: str, version_id: str, request: Request) -> list[dict]:
        principal = current_principal(request)
        try:
            return publication.list_for_design(principal, workspace_id, version_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/designs/{version_id}/publication-approvals", status_code=201)
    def approve_publication(workspace_id: str, version_id: str, body: PublicationApprovalRequest,
                            request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return publication.approve(principal, workspace_id, version_id,
                                       **body.model_dump())
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PublicationError as exc:
            raise publication_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/publication-approvals/{approval_id}/cancel")
    def cancel_publication_approval(workspace_id: str, approval_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return publication.cancel(principal, workspace_id, approval_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PublicationError as exc:
            raise publication_error(exc) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/publication-approvals/{approval_id}/manual-package")
    def manual_publication_package(workspace_id: str, approval_id: str, request: Request) -> Response:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            content = publication.manual_package(principal, workspace_id, approval_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail={"code": "workspace_access_denied", "message": str(exc)}) from exc
        except PublicationError as exc:
            raise publication_error(exc) from exc
        except CreativeError as exc:
            raise creative_error(exc) from exc
        return Response(content, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="falkrona-approved-{approval_id}.zip"',
            "Cache-Control": "private, no-store",
        })

    @app.post("/api/v1/workspaces/{workspace_id}/brand/versions/{version}/confirm")
    def confirm_profile(workspace_id: str, version: int, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.confirm_profile(principal, workspace_id, version)
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/onboarding/status")
    def onboarding_status(workspace_id: str, request: Request) -> dict:
        principal = current_principal(request)
        return phase3.onboarding_status(principal, workspace_id)

    @app.post("/api/v1/workspaces/{workspace_id}/interview/turns")
    def onboarding_turn(
        workspace_id: str, body: OnboardingTurnRequest, request: Request
    ) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase3.onboarding_turn(
                principal,
                workspace_id,
                body.question_key,
                body.answer,
                body.confirmed,
            )
        except Phase3Error as exc:
            raise phase3_error(exc) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/assets/{asset_id}/download-url")
    def create_download_url(workspace_id: str, asset_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            accounts.get_asset(principal, workspace_id, asset_id)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
        token = download_signer.issue(
            workspace_id,
            asset_id,
            principal.user_id,
            expires_at=int(expires_at.timestamp()),
        )
        return {
            "download_url": (
                f"/api/v1/workspaces/{workspace_id}/assets/{asset_id}/download?token={quote(token)}"
            ),
            "expires_at": expires_at.isoformat(),
        }

    @app.get("/api/v1/workspaces/{workspace_id}/assets/{asset_id}/download")
    def download_asset(
        workspace_id: str, asset_id: str, request: Request, token: str = ""
    ) -> Response:
        principal = current_principal(request)
        try:
            download_signer.verify(
                token,
                workspace_id=workspace_id,
                asset_id=asset_id,
                user_id=principal.user_id,
            )
            asset = accounts.get_asset(principal, workspace_id, asset_id)
            content = local_storage.read_bytes(asset.storage_key)
        except InvalidCredential as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "download_token_rejected", "message": str(exc)},
            ) from exc
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "workspace_access_denied", "message": str(exc)},
            ) from exc
        except StorageError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "asset_not_found", "message": str(exc)},
            ) from exc
        return Response(
            content,
            media_type=asset.mime_type,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(asset.original_name)}",
                "Cache-Control": "private, no-store",
            },
        )

    @app.post("/api/v1/workspaces/{workspace_id}/jobs", status_code=202)
    def create_job(workspace_id: str, body: CreateJobRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        require_workspace(principal, workspace_id, "write")
        if body.kind != "fixture.artifact":
            raise HTTPException(
                status_code=422,
                detail={"code": "unsupported_job_kind", "message": "Use the dedicated operation endpoint."},
            )
        scoped_jobs = JobStore(
            sessions,
            lease_seconds=settings.job_lease_seconds,
            workspace_id=workspace_id,
        )
        job_id = scoped_jobs.enqueue(
            body.kind,
            body.payload,
            dedupe_key=body.dedupe_key,
            max_attempts=body.max_attempts,
            created_by_user_id=principal.user_id,
        )
        return {"job_id": job_id, "status": "queued"}

    @app.post("/api/v1/workspaces/{workspace_id}/agent-runs", status_code=202)
    def create_agent_run(workspace_id: str, body: AgentRunRequest, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase4.create_run(principal, workspace_id, body.prompt, body.dedupe_key)
        except (Phase4Error, AuthorizationError) as exc:
            status_code = 403 if isinstance(exc, AuthorizationError) else 422
            raise HTTPException(status_code=status_code, detail={"code": getattr(exc, "code", "workspace_access_denied"), "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}")
    def get_agent_run(workspace_id: str, run_id: str, request: Request) -> dict:
        principal = current_principal(request)
        try:
            return phase4.get_run(principal, workspace_id, run_id)
        except (Phase4Error, AuthorizationError) as exc:
            raise HTTPException(status_code=404 if getattr(exc, "code", "") == "run_not_found" else 403, detail={"code": getattr(exc, "code", "workspace_access_denied"), "message": str(exc)}) from exc

    @app.post("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}/cancel")
    def cancel_agent_run(workspace_id: str, run_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_csrf(request, principal)
        try:
            return phase4.cancel_run(principal, workspace_id, run_id)
        except (Phase4Error, AuthorizationError) as exc:
            raise HTTPException(status_code=404 if getattr(exc, "code", "") == "run_not_found" else 403, detail={"code": getattr(exc, "code", "workspace_access_denied"), "message": str(exc)}) from exc

    @app.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}")
    def get_job(workspace_id: str, job_id: str, request: Request) -> dict:
        principal = current_principal(request)
        require_workspace(principal, workspace_id, "read")
        job = JobStore(sessions, workspace_id=workspace_id).get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "job_not_found", "message": "Job was not found."},
            )
        return job

    @app.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/events")
    def get_job_events(
        workspace_id: str, job_id: str, request: Request
    ) -> StreamingResponse:
        principal = current_principal(request)
        require_workspace(principal, workspace_id, "read")
        job = JobStore(sessions, workspace_id=workspace_id).get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "job_not_found", "message": "Job was not found."},
            )

        def event_stream():
            yield f"event: status\ndata: {job['status']}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/internal/v1/tool-call/authorize", status_code=204)
    def authorize_tool_call(
        body: ToolAuthorizationRequest,
        authorization: str = Header(default=""),
    ) -> Response:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail={"code": "run_credential_required", "message": "Run credential is required."},
            )
        try:
            run_credentials.verify(
                authorization.removeprefix("Bearer "),
                workspace_id=body.workspace_id,
                job_id=body.job_id,
                operation=body.operation,
            )
            accounts.validate_tool_job(body.workspace_id, body.job_id)
        except (InvalidCredential, AuthorizationError) as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": "run_scope_denied", "message": str(exc)},
            ) from exc
        return Response(status_code=204)

    def require_agent_tool_credential(authorization: str, workspace_id: str, job_id: str, operation: str) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail={"code": "run_credential_required", "message": "Run credential is required."})
        try:
            run_credentials.verify(authorization.removeprefix("Bearer "), workspace_id=workspace_id, job_id=job_id, operation=operation)
            accounts.validate_tool_job(workspace_id, job_id)
        except (InvalidCredential, AuthorizationError) as exc:
            raise HTTPException(status_code=403, detail={"code": "run_scope_denied", "message": str(exc)}) from exc

    @app.post("/internal/v1/agent-tools/brand-context")
    def agent_brand_context(body: AgentContextRequest, authorization: str = Header(default="")) -> dict:
        require_agent_tool_credential(authorization, body.workspace_id, body.job_id, "brand.read")
        try:
            return phase4.get_brand_context(body.workspace_id, body.job_id)
        except (Phase4Error, AuthorizationError) as exc:
            raise HTTPException(status_code=403, detail={"code": getattr(exc, "code", "run_scope_denied"), "message": str(exc)}) from exc

    @app.post("/internal/v1/agent-tools/artifacts", status_code=201)
    def agent_store_artifact(body: AgentArtifactRequest, authorization: str = Header(default="")) -> dict:
        require_agent_tool_credential(authorization, body.workspace_id, body.job_id, "artifact.write")
        try:
            return phase4.store_artifact(body.workspace_id, body.job_id, body.title, body.content)
        except (Phase4Error, AuthorizationError) as exc:
            raise HTTPException(status_code=422 if isinstance(exc, Phase4Error) else 403, detail={"code": getattr(exc, "code", "run_scope_denied"), "message": str(exc)}) from exc

    return app
