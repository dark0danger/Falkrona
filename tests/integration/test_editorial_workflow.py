"""Exercise the actual worker, budgets, browser handoff and workspace memory."""
from copy import deepcopy
import json

import pytest
from sqlalchemy import select

from brandpilot.phase4 import Phase4Error
from brandpilot.models import AgentRun, PublicationApproval, DesignVersion, utc_now
from brandpilot.learning import writing_memory, post_feedback
from tests.integration import test_weekly_generation as fixtures
from tests.integration.test_design_direction import DIRECTION


@pytest.fixture
def flow():
    value = fixtures.WeekFlowTests()
    value.setUp()
    yield value
    value.tearDown()


def result(value):
    return {"text": json.dumps(value, ensure_ascii=False), "model_calls": 1,
            "usage": {"input_tokens": 100, "output_tokens": 100}}


def test_editor_revises_week_before_it_becomes_visible(flow):
    run = flow.draft().json()
    draft, polished = flow.content(), flow.content()
    polished["posts"][0]["title"] = "A little time for coffee"
    calls = []
    def executor(prompt, *_):
        calls.append(prompt)
        return result(draft if len(calls) == 1 else polished)
    flow.execute(executor)
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["status"] == "completed", saved
    assert len(calls) == 2
    assert saved["output"]["usage"]["input_tokens"] == 200
    assert saved["output"]["editorial_review"]["status"] == "completed"
    plan = flow.client.get(f"{flow.base}/plans?week_start=2026-12-28").json()["plan"]
    assert plan["items"][0]["title"] == polished["posts"][0]["title"]
    assert plan["status"] == "draft"
    with flow.sessions() as session:
        assert not session.scalars(select(PublicationApproval)).all()


@pytest.mark.parametrize("failure", ["invalid_json", "schedule_change", "extra_calls"])
def test_failed_review_keeps_previous_plan_and_cannot_publish(flow, failure):
    run = flow.draft().json()
    calls = []
    def executor(*_):
        calls.append(1)
        draft = flow.content()
        if len(calls) == 1:
            return result(draft)
        if failure == "invalid_json":
            return {"text": "not JSON", "model_calls": 1}
        if failure == "schedule_change":
            draft["posts"][0]["hour"] += 1
        value = result(draft)
        if failure == "extra_calls":
            value["model_calls"] = 2
        return value
    flow.execute(executor)
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["status"] == "failed"
    assert len(calls) == (3 if failure == "invalid_json" else 2)
    assert flow.client.get(f"{flow.base}/plans?week_start=2026-12-28").json()["plan"]["id"] == flow.plan_id


def test_budget_prevents_unadmitted_editor_call(flow):
    flow.app.state.phase4._max_model_calls = 1
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    calls = []
    flow.execute(lambda *_: calls.append(1) or result(DIRECTION))
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["last_error"] == "quota_exhausted"
    assert len(calls) == 1
    assert flow.client.post(f"{flow.base}/agent-runs/{run['id']}/browser-packet", headers=flow.csrf,
        json={"provider": "chatgpt", "consent": True}).status_code == 422


@pytest.mark.parametrize("failed_call", [1, 2])
def test_cut_off_direction_recovers_before_image_handoff(flow, failed_call):
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    calls = []

    def executor(prompt, *_):
        calls.append(prompt)
        if len(calls) == failed_call:
            raise Phase4Error("gemini_incomplete_response", "Gemini stopped early.")
        return result(DIRECTION)

    flow.execute(executor)
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["status"] == "completed", saved
    assert saved["output"]["editorial_review"]["model_calls"] == len(calls) == 3
    packet = flow.client.post(f"{flow.base}/agent-runs/{run['id']}/browser-packet", headers=flow.csrf,
        json={"provider": "chatgpt", "consent": True})
    assert packet.status_code == 200, packet.json()


def test_repeatedly_cut_off_direction_stays_failed(flow):
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    calls = []

    def executor(prompt, *_):
        calls.append(prompt)
        raise Phase4Error("gemini_incomplete_response", "Gemini stopped early.")

    flow.execute(executor)
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["status"] == "failed"
    assert saved["last_error"] == "gemini_incomplete_response"
    assert saved["output"]["failure_message"] == "Gemini stopped early."
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["copy_prompt_mismatch", "editorial_contract_changed", "language_mismatch"])
def test_editor_cannot_break_image_handoff_contract(flow, failure):
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    calls = []
    def executor(*_):
        calls.append(1)
        value = deepcopy(DIRECTION)
        if len(calls) == 2:
            if failure == "copy_prompt_mismatch":
                value["headline"] = "A completely different headline"
            elif failure == "editorial_contract_changed":
                value["product_observation"]["identity"] = "A different package"
            else:
                value["caption"] = "قهوة كل صباح"
        return result(value)
    flow.execute(executor)
    saved = flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()
    assert saved["last_error"] == failure, saved


def test_polished_copy_is_the_copy_sent_to_image_app(flow):
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    calls = []
    edited = deepcopy(DIRECTION)
    edited.update(headline="Your morning starts here", cta="Find your coffee", caption="Make a little time for coffee.")
    edited["image_prompt"] = "Create a new coffee scene. Headline: " + edited["headline"] + ". CTA: " + edited["cta"]
    flow.execute(lambda *_: calls.append(1) or result(DIRECTION if len(calls) == 1 else edited))
    packet = flow.client.post(f"{flow.base}/agent-runs/{run['id']}/browser-packet", headers=flow.csrf,
        json={"provider": "chatgpt", "consent": True})
    assert packet.status_code == 200, packet.text
    assert edited["headline"] in packet.json()["prompt"]
    assert DIRECTION["headline"] not in packet.json()["prompt"]


def test_only_approved_workspace_copy_enters_memory(flow):
    with flow.sessions() as session, session.begin():
        assert writing_memory(session, flow.workspace) == []
        design = session.get(DesignVersion, flow.first["id"])
        design.creative_direction = deepcopy(DIRECTION)
        design.caption = "An owner-approved voice example"
        row = PublicationApproval(workspace_id=flow.workspace, design_version_id=design.id,
            destination_platform="facebook_pages", destination_account_id="fixture-page",
            scheduled_at_utc=utc_now(), schedule_local="2026-12-29T11:00", schedule_fold=0,
            timezone_name="Africa/Cairo", content_hash="a"*64, source_snapshot={},
            idempotency_key="editorial-memory-test", approved_by_user_id=design.created_by_user_id)
        session.add(row); session.flush()
        assert writing_memory(session, flow.workspace)[0]["caption"] == design.caption
        assert writing_memory(session, "other-workspace") == []
        row.status = "cancelled"; session.flush()
        assert writing_memory(session, flow.workspace) == []


def test_owner_feedback_is_used_in_next_prompt_and_isolated(flow):
    feedback = flow.client.post(f"{flow.base}/designs/{flow.first['id']}/feedback", headers=flow.csrf,
        json={"original_text": "Use plain Arabic", "interpretation": "Use plain Arabic", "category": "copy",
              "kind": "preference", "scope": "post"})
    assert feedback.status_code == 201
    run = flow.client.post(flow.path, headers=flow.csrf, json=flow.inputs).json()
    captured = []
    flow.execute(lambda prompt, *_: captured.append(prompt) or result(DIRECTION))
    assert all("Use plain Arabic" in prompt for prompt in captured)
    with flow.sessions() as session:
        assert not post_feedback(session, "another-workspace", flow.plan_id, flow.first["item_id"])
    assert flow.client.get(f"{flow.base}/agent-runs/{run['id']}").json()["status"] == "completed"
