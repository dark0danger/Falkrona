"""Versioned offline strategy and weekly creative briefs."""

from __future__ import annotations
from contextlib import nullcontext

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .accounts import AccountService, Principal
from .database import set_workspace_context
from .learning import applicable_preferences
from .models import BrandProfileVersion, OnboardingInterview, Product, SocialPost, WeeklyPlan, Workspace, utc_now


GOALS = frozenset({"awareness", "engagement", "leads", "sales"})
PLATFORMS = frozenset({"facebook_pages", "instagram"})
PURPOSES = frozenset({"education", "conversation", "offer", "product"})
FORMATS = frozenset({"post", "carousel", "story"})
AVAILABLE = frozenset({"available", "in_stock", "in stock", "yes", "true", "متوفر"})
PROMOTION_WORDS = re.compile(r"\b(?:sale|discount|limited|promo|promotion|free|off)\b|[%٪]|خصم|تخفيض|عرض|مجانا", re.IGNORECASE)


class PlanningError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _offer(profile: BrandProfileVersion, answers: dict, local_date: date) -> str:
    value = _text(profile.fields.get("offer")) or _text(answers.get("offer"))
    if not value:
        return ""
    expiry_text = _text(profile.fields.get("offer_expires_at"))
    if expiry_text:
        try:
            expiry = date.fromisoformat(expiry_text)
        except ValueError:
            return ""
        if local_date > expiry:
            return ""
    elif PROMOTION_WORDS.search(value):
        return ""
    return value


def _available_products(products: list[Product]) -> list[Product]:
    return sorted((row for row in products if _text(row.availability).lower() in AVAILABLE), key=lambda row: row.sku)


def suggested_cadence(recent_post_count: int) -> int:
    return 2 if recent_post_count < 4 else 3 if recent_post_count < 8 else 4


def _slot(week_start: date, index: int, cadence: int, zone: ZoneInfo) -> datetime:
    day = (2 * index + 1) * 7 // (2 * cadence)
    return datetime.combine(week_start + timedelta(days=day), time(11 if index % 2 == 0 else 17), zone)


def _brief(
    profile: BrandProfileVersion, answers: dict, interview_id: str | None,
    products: list[Product], goal: str, platform: str, scheduled_local: datetime,
    purpose: str,
) -> dict:
    brand = _text(profile.fields.get("brand_name")) or _text(answers.get("brand_name"))
    category = _text(profile.fields.get("category")) or _text(answers.get("category"))
    audience = _text(profile.fields.get("audience")) or _text(answers.get("audience")) or "your audience"
    refs = [{"kind": "profile" if _text(profile.fields.get("brand_name")) else "onboarding",
             "id": profile.id if _text(profile.fields.get("brand_name")) else interview_id,
             "field": "brand_name", "value": brand}]
    if category:
        refs.append({"kind": "profile" if _text(profile.fields.get("category")) else "onboarding",
                     "id": profile.id if _text(profile.fields.get("category")) else interview_id,
                     "field": "category", "value": category})
    if audience != "your audience":
        refs.append({"kind": "profile" if _text(profile.fields.get("audience")) else "onboarding",
                     "id": profile.id if _text(profile.fields.get("audience")) else interview_id,
                     "field": "audience", "value": audience})
    offer = _offer(profile, answers, scheduled_local.date())
    available = _available_products(products)
    if purpose == "offer" and not offer:
        purpose = "education"
    if purpose == "product" and not available:
        purpose = "education"
    if purpose == "offer":
        title = f"A closer look at {offer}"
        concept = f"Introduce the confirmed {offer} for {audience}. Verify current terms before publication."
        cta = "Ask us about current details"
        refs.append({"kind": "profile" if _text(profile.fields.get("offer")) else "onboarding",
                     "id": profile.id if _text(profile.fields.get("offer")) else interview_id,
                     "field": "offer", "value": offer})
    elif purpose == "product":
        product = available[0]
        title = f"Meet {product.name}"
        concept = f"Show {product.name} in a real {category or 'customer'} context. Use verified product details only."
        cta = "Ask about current availability"
        refs.append({"kind": "product", "id": product.id, "field": "name", "value": product.name})
    elif purpose == "conversation":
        title = f"A question for {audience}"
        concept = f"Invite {audience} to share a challenge related to {category or brand}. Respond without promising an outcome."
        cta = "Tell us what matters to you"
    else:
        title = f"Choosing {category or brand} with confidence"
        concept = f"Explain one practical consideration for {audience} when exploring {category or brand}. Ground examples in confirmed {brand} information."
        cta = "Save this for later"
    return {
        "id": str(uuid.uuid4()), "scheduled_at": scheduled_local.astimezone(timezone.utc).isoformat(),
        "platform": platform, "format": "carousel" if platform == "instagram" and purpose in {"education", "product"} else "post",
        "purpose": purpose, "title": title, "concept": concept, "cta": cta,
        "rationale": f"Supports {goal} for {audience} with a {purpose} angle.",
        "factual_refs": refs, "status": "draft", "locked": False, "conflicts": [],
    }


def draft_plan(
    profile: BrandProfileVersion, answers: dict, interview_id: str | None,
    products: list[Product], week_start: date, zone: ZoneInfo, goal: str,
    platforms: list[str], cadence: int, recent_posts: list[SocialPost],
    previous_items: list[dict] | None = None,
) -> tuple[dict, list[dict]]:
    brand = _text(profile.fields.get("brand_name")) or _text(answers.get("brand_name"))
    audience = _text(profile.fields.get("audience")) or _text(answers.get("audience")) or "your audience"
    category = _text(profile.fields.get("category")) or _text(answers.get("category")) or "its category"
    has_offer = bool(_offer(profile, answers, week_start))
    has_product = bool(_available_products(products))
    cycle = ["education"] + (["offer"] if has_offer else []) + (["product"] if has_product else []) + ["conversation"]
    slots = [_slot(week_start, index, cadence, zone) for index in range(cadence)]
    kept = [deepcopy(item) for item in (previous_items or []) if item.get("locked") or item.get("status") == "approved"]
    product_by_id = {product.id: product for product in products}
    for item in kept:
        conflicts = []
        local = _utc(datetime.fromisoformat(item["scheduled_at"])).astimezone(zone)
        if not week_start <= local.date() < week_start + timedelta(days=7):
            conflicts.append("outside_week")
        if item["platform"] not in platforms:
            conflicts.append("platform_removed")
        if item["purpose"] == "offer" and not _offer(profile, answers, local.date()):
            conflicts.append("offer_unavailable")
        if item["purpose"] == "product" and not any(
            ref.get("id") in {product.id for product in _available_products(products)}
            for ref in item.get("factual_refs", []) if ref.get("kind") == "product"
        ):
            conflicts.append("product_unavailable")
        if any(ref.get("kind") == "profile" and ref.get("id") != profile.id for ref in item.get("factual_refs", [])):
            conflicts.append("profile_changed")
        if any(
            _text(profile.fields.get(ref.get("field"))) != ref.get("value") if ref.get("kind") == "profile"
            else _text(answers.get(ref.get("field"))) != ref.get("value") if ref.get("kind") == "onboarding"
            else _text(product_by_id[ref["id"]].name) != ref.get("value") if ref.get("kind") == "product" and ref.get("id") in product_by_id
            else False
            for ref in item.get("factual_refs", [])
        ):
            conflicts.append("fact_changed")
        item["conflicts"] = conflicts
    if len(kept) > cadence:
        for item in kept:
            item["conflicts"] = sorted(set([*item["conflicts"], "cadence_exceeded"]))
    occupied = {item["scheduled_at"] for item in kept}
    items = kept[:]
    for index, slot in enumerate(slots):
        if len(items) >= cadence:
            break
        if slot.astimezone(timezone.utc).isoformat() in occupied:
            continue
        purpose = cycle[index % len(cycle)]
        items.append(_brief(profile, answers, interview_id, products, goal,
                            platforms[index % len(platforms)], slot, purpose))
    if len(items) < cadence:
        for slot in slots:
            if len(items) >= cadence:
                break
            if slot.astimezone(timezone.utc).isoformat() not in {item["scheduled_at"] for item in items}:
                items.append(_brief(profile, answers, interview_id, products, goal,
                                    platforms[len(items) % len(platforms)], slot, cycle[len(items) % len(cycle)]))
    items.sort(key=lambda item: (item["scheduled_at"], item["id"]))
    counts = {purpose: sum(item["purpose"] == purpose for item in items) for purpose in PURPOSES}
    strategy = {
        "goal": goal, "audience": audience,
        "direction": f"Position {brand} in {category} for {audience}; use confirmed facts and invite a clear next step.",
        "platforms": platforms, "cadence": cadence, "content_mix": counts,
        "cadence_basis": {"recent_post_count": len(recent_posts),
                          "evidence_ids": sorted(post.id for post in recent_posts), "source": "last_28_days"},
        "publication_mode": "manual_only",
    }
    return strategy, items


class PlanningService:
    def __init__(self, sessions: sessionmaker[Session], accounts: AccountService) -> None:
        self._sessions = sessions
        self._accounts = accounts

    @staticmethod
    def _payload(row: WeeklyPlan | None) -> dict | None:
        if row is None:
            return None
        return {"id": row.id, "workspace_id": row.workspace_id, "week_start": row.week_start.isoformat(),
                "revision": row.revision, "status": row.status, "profile_version": row.profile_version,
                "strategy": row.strategy, "items": row.items,
                "created_at": row.created_at.isoformat(),
                "approved_at": row.approved_at.isoformat() if row.approved_at else None}

    @staticmethod
    def _profile(session: Session, workspace_id: str) -> BrandProfileVersion:
        profile = session.scalar(select(BrandProfileVersion).where(
            BrandProfileVersion.workspace_id == workspace_id, BrandProfileVersion.status == "confirmed"
        ).order_by(BrandProfileVersion.version.desc()))
        if profile is None:
            raise PlanningError("profile_required", "Confirm a brand profile before making a plan.")
        return profile

    @staticmethod
    def _plan(session: Session, workspace_id: str, plan_id: str, *, lock: bool = False) -> WeeklyPlan:
        query = select(WeeklyPlan).where(WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.id == plan_id)
        if lock and session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise PlanningError("plan_not_found", "The plan is unavailable.")
        return row

    def current(self, principal: Principal, workspace_id: str, week_start: date) -> dict:
        self._accounts.require_permission(principal, workspace_id, "read")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            rows = session.scalars(select(WeeklyPlan).where(
                WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.week_start == week_start
            ).order_by(WeeklyPlan.revision.desc())).all()
            return {"plan": self._payload(rows[0] if rows and rows[0].status != "deleted" else None),
                    "deleted_plan_id": rows[0].id if rows and rows[0].status == "deleted" else None,
                    "last_approved": self._payload(next((row for row in rows if row.status == "approved"), None))}

    def generate(self, principal: Principal, workspace_id: str, *, week_start: date,
                 goal: str, platforms: list[str], cadence: int | None, reuse_existing: bool = False) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        if week_start.weekday() != 0:
            raise PlanningError("invalid_week", "The week must start on Monday.")
        if goal not in GOALS or not platforms or len(set(platforms)) != len(platforms) or not set(platforms) <= PLATFORMS:
            raise PlanningError("invalid_direction", "Choose a goal and Facebook/Instagram platforms.")
        if cadence is not None and not 1 <= cadence <= 5:
            raise PlanningError("invalid_cadence", "Cadence must be 1 to 5 posts per week.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            workspace_query = select(Workspace).where(Workspace.id == workspace_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                workspace_query = workspace_query.with_for_update()
            workspace = session.scalar(workspace_query)
            if workspace is None:
                raise PlanningError("workspace_not_found", "Workspace is unavailable.")
            try:
                zone = ZoneInfo(workspace.timezone)
            except ZoneInfoNotFoundError as exc:
                raise PlanningError("invalid_timezone", "Workspace timezone is unavailable.") from exc
            profile = self._profile(session, workspace_id)
            interview = session.scalar(select(OnboardingInterview).where(
                OnboardingInterview.workspace_id == workspace_id).order_by(OnboardingInterview.created_at.desc()))
            answers = interview.confirmed_answers or {} if interview else {}
            brand = _text(profile.fields.get("brand_name")) or _text(answers.get("brand_name"))
            if not brand:
                raise PlanningError("brand_name_required", "Confirm a brand name before making a plan.")
            products = session.scalars(select(Product).where(Product.workspace_id == workspace_id)).all()
            window_start = datetime.combine(week_start - timedelta(days=28), time.min, zone).astimezone(timezone.utc)
            window_end = datetime.combine(week_start, time.min, zone).astimezone(timezone.utc)
            recent = session.scalars(select(SocialPost).where(
                SocialPost.workspace_id == workspace_id,
                SocialPost.provider.in_(tuple(PLATFORMS)),
                SocialPost.published_at >= window_start, SocialPost.published_at < window_end,
                SocialPost.published_at <= utc_now(),
            )).all()
            suggested = suggested_cadence(len(recent))
            frequency = cadence or suggested
            previous = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.week_start == week_start
            ).order_by(WeeklyPlan.revision.desc()))
            if reuse_existing and previous is not None:
                return self._payload(previous)
            strategy, items = draft_plan(
                profile, answers, interview.id if interview else None, products,
                week_start, zone, goal, platforms, frequency, recent,
                previous.items if previous else None,
            )
            for item in items:
                item["preferences"] = applicable_preferences(
                    session, workspace_id, platform=item["platform"],
                    campaign_key=week_start.isoformat(), post_key=item["id"])
            row = WeeklyPlan(workspace_id=workspace_id, week_start=week_start,
                             revision=previous.revision + 1 if previous else 1,
                             status="draft", profile_version=profile.version,
                             strategy=strategy, items=items, created_by_user_id=principal.user_id)
            session.add(row)
            session.flush()
            return self._payload(row)

    def update_strategy(self, principal: Principal, workspace_id: str, plan_id: str,
                        *, audience: str | None, direction: str | None) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._plan(session, workspace_id, plan_id, lock=True)
            if row.status != "draft":
                raise PlanningError("plan_approved", "Create a new revision to change an approved plan.")
            strategy = dict(row.strategy)
            if audience is not None:
                strategy["audience"] = audience.strip()
            if direction is not None:
                strategy["direction"] = direction.strip()
            if not strategy["audience"] or not strategy["direction"]:
                raise PlanningError("incomplete_strategy", "Audience and direction are required.")
            row.strategy = strategy
            return self._payload(row)

    def update_item(self, principal: Principal, workspace_id: str, plan_id: str,
                    item_id: str, changes: dict) -> dict:
        self._accounts.require_permission(principal, workspace_id, "write")
        allowed = {"scheduled_at", "platform", "format", "purpose", "title", "concept", "cta", "rationale", "status", "locked"}
        if not changes or not set(changes) <= allowed or any(value is None for value in changes.values()):
            raise PlanningError("invalid_item", "Unsupported item changes.")
        with self._sessions() as session, session.begin():
            set_workspace_context(session, workspace_id)
            row = self._plan(session, workspace_id, plan_id, lock=True)
            if row.status != "draft":
                raise PlanningError("plan_approved", "Create a new revision to change an approved plan.")
            items = deepcopy(row.items)
            item = next((entry for entry in items if entry["id"] == item_id), None)
            if item is None:
                raise PlanningError("item_not_found", "Calendar item is unavailable.")
            content_changes = set(changes) - {"locked", "status"}
            if item["locked"] and content_changes and changes.get("locked") is not False:
                raise PlanningError("item_locked", "Unlock this item before editing it.")
            if item["status"] == "approved" and content_changes and changes.get("status") != "draft":
                raise PlanningError("item_approved", "Return the item to draft before editing it.")
            for key, value in changes.items():
                item[key] = value.strip() if isinstance(value, str) else value
            if item["status"] not in {"draft", "approved", "rejected"} or item["platform"] not in PLATFORMS or item["format"] not in FORMATS or item["purpose"] not in PURPOSES:
                raise PlanningError("invalid_item", "Item status, platform, format, or purpose is invalid.")
            if not all(_text(item[key]) for key in ("title", "concept", "cta", "rationale")):
                raise PlanningError("incomplete_item", "Title, concept, CTA, and rationale are required.")
            try:
                scheduled = datetime.fromisoformat(item["scheduled_at"])
                zone = ZoneInfo(session.get(Workspace, workspace_id).timezone)
            except (ValueError, ZoneInfoNotFoundError) as exc:
                raise PlanningError("invalid_schedule", "Use a timezone-aware schedule.") from exc
            if scheduled.utcoffset() is None:
                local_candidate = scheduled.replace(tzinfo=zone)
                if (local_candidate.replace(fold=1).utcoffset() != local_candidate.utcoffset()
                    or local_candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != scheduled):
                    raise PlanningError("invalid_schedule", "Choose an unambiguous local time.")
                scheduled = local_candidate
            local = scheduled.astimezone(zone)
            if not row.week_start <= local.date() < row.week_start + timedelta(days=7):
                raise PlanningError("outside_week", "The item must stay in its planning week.")
            item["scheduled_at"] = scheduled.astimezone(timezone.utc).isoformat()
            if content_changes:
                item["conflicts"] = []
            row.items = items
            row.strategy = {**row.strategy, "content_mix": {
                purpose: sum(entry["purpose"] == purpose for entry in items) for purpose in PURPOSES
            }}
            return self._payload(row)

    def approve(self, principal: Principal, workspace_id: str, plan_id: str, *, _session=None) -> dict:
        self._accounts.require_permission(principal, workspace_id, "approve")
        with (nullcontext(_session) if _session is not None else self._sessions()) as session, \
             (nullcontext() if _session is not None else session.begin()):
            set_workspace_context(session, workspace_id)
            row = self._plan(session, workspace_id, plan_id, lock=True)
            latest = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.workspace_id == workspace_id, WeeklyPlan.week_start == row.week_start
            ).order_by(WeeklyPlan.revision.desc()))
            if latest.id != row.id or row.status != "draft":
                raise PlanningError("stale_plan", "Only the latest draft can be approved.")
            profile = self._profile(session, workspace_id)
            if profile.version != row.profile_version:
                raise PlanningError("profile_changed", "Replan from the latest confirmed brand profile.")
            items = row.items
            if len(items) != row.strategy["cadence"] or any(
                item["status"] == "rejected" or item["conflicts"] or not item["factual_refs"]
                or not all(_text(item[key]) for key in ("title", "concept", "cta", "rationale"))
                or item["platform"] not in PLATFORMS or item["purpose"] not in PURPOSES or item["format"] not in FORMATS
                for item in items
            ):
                raise PlanningError("plan_incomplete", "Resolve conflicts and rejected or incomplete items first.")
            zone = ZoneInfo(session.get(Workspace, workspace_id).timezone)
            scheduled = [_utc(datetime.fromisoformat(item["scheduled_at"])) for item in items]
            if len(set(scheduled)) != len(scheduled) or any(
                not row.week_start <= moment.astimezone(zone).date() < row.week_start + timedelta(days=7)
                for moment in scheduled
            ):
                raise PlanningError("schedule_conflict", "Calendar slots must be distinct and within the week.")
            if any(item["platform"] not in row.strategy["platforms"] for item in items):
                raise PlanningError("platform_conflict", "An item uses a platform outside the strategy.")
            products = {product.id: product for product in session.scalars(select(Product).where(Product.workspace_id == workspace_id))}
            interview = session.scalar(select(OnboardingInterview).where(
                OnboardingInterview.workspace_id == workspace_id).order_by(OnboardingInterview.created_at.desc()))
            answers = interview.confirmed_answers or {} if interview else {}
            for item, moment in zip(items, scheduled):
                local_date = moment.astimezone(zone).date()
                if item["purpose"] == "offer" and not _offer(profile, answers, local_date):
                    raise PlanningError("offer_unavailable", "The offer is unverified or expired.")
                if item["purpose"] == "offer" and not any(ref.get("field") == "offer" for ref in item["factual_refs"]):
                    raise PlanningError("offer_unreferenced", "The offer needs a confirmed source reference.")
                if item["purpose"] == "product" and not any(ref.get("kind") == "product" for ref in item["factual_refs"]):
                    raise PlanningError("product_unreferenced", "The product needs a confirmed source reference.")
                for ref in item["factual_refs"]:
                    if ref.get("field") == "offer" and not _offer(profile, answers, local_date):
                        raise PlanningError("offer_unavailable", "The offer is unverified or expired.")
                    if ref.get("kind") == "profile" and (ref.get("id") != profile.id or _text(profile.fields.get(ref.get("field"))) != ref.get("value")):
                        raise PlanningError("stale_reference", "An item references an older or missing profile fact.")
                    if ref.get("kind") == "onboarding" and (interview is None or ref.get("id") != interview.id or _text(answers.get(ref.get("field"))) != ref.get("value")):
                        raise PlanningError("stale_reference", "An item references an unconfirmed onboarding fact.")
                    if ref.get("kind") == "product" and (ref.get("id") not in products or _text(products[ref["id"]].availability).lower() not in AVAILABLE or products[ref["id"]].name != ref.get("value")):
                        raise PlanningError("product_unavailable", "An item references an unavailable product.")
                    if ref.get("kind") not in {"profile", "onboarding", "product"}:
                        raise PlanningError("invalid_reference", "An item has an unsupported fact reference.")
            row.status = "approved"
            row.approved_at = utc_now()
            row.items = [{**item, "status": "approved"} for item in items]
            return self._payload(row)
