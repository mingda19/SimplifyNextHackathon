"""Cross-service guardrails missed by fixture-only orchestrator tests."""
from pathlib import Path
import sys
import uuid

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

from orchestrator import services
from orchestrator.config import settings
from orchestrator.graph import compile_graph, make_checkpointer
from orchestrator.nodes.act import act
from orchestrator.nodes.approval import build_summary
from orchestrator.nodes.commit import commit, reset_idempotency
from orchestrator.state import PlanStep, new_state
from langgraph.types import Command


@pytest.fixture
def live_graph(stack, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "fake_llm", True)
    monkeypatch.setattr(settings, "fake_inventory", False)
    monkeypatch.setattr(settings, "fake_feedback", False)
    monkeypatch.setattr(settings, "fake_pricing", False)
    for service in ("inventory", "feedback", "pricing"):
        monkeypatch.setattr(settings, service + "_url", stack["urls"][service])
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "spend.json")
    stack["sql"]("UPDATE vendor_offers SET available_qty=10000 WHERE sku='RICE-5KG'")
    reset_idempotency()
    saver = make_checkpointer(str(tmp_path / "checkpoints.db"))
    yield compile_graph(saver)
    saver.conn.close()
    reset_idempotency()


def plan_state(action="place_order"):
    state = new_state("qa-" + uuid.uuid4().hex)
    state["plan"] = {"stockout_sku": "RICE-5KG", "days_until_failure": 8,
                     "reasoning": "Readiness test", "steps": [
                         {"action": action, "sku": "RICE-5KG", "qty": 250,
                          "vendor_id": "VENDOR-COMMUNITY", "rationale": "Replenish"}]}
    return state


@pytest.mark.parametrize("charity_type", ["A", "B"])
def test_no_real_order_exists_before_approval(live_graph, stack, charity_type):
    before = stack["sql"]("SELECT count(*) FROM orders")[0][0]
    state = new_state("qa-" + uuid.uuid4().hex, charity_type)
    result = live_graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert "__interrupt__" in result
    after = stack["sql"]("SELECT count(*) FROM orders")[0][0]
    assert after == before, f"Created {after - before} real order(s) BEFORE human approval for Type {charity_type}"


def test_rejecting_a_live_plan_leaves_no_orders(live_graph, stack):
    before = stack["sql"]("SELECT count(*) FROM orders")[0][0]
    state = new_state("qa-" + uuid.uuid4().hex)
    cfg = {"configurable": {"thread_id": state["thread_id"]}}
    assert "__interrupt__" in live_graph.invoke(state, cfg)
    result = live_graph.invoke(Command(resume={"decision": "rejected"}), cfg)
    assert result["approval"] == "rejected"
    assert stack["sql"]("SELECT count(*) FROM orders")[0][0] == before


def test_request_quote_does_not_place_an_order(live_graph, stack):
    before = stack["sql"]("SELECT count(*) FROM orders")[0][0]
    act(plan_state("request_quote"))
    assert stack["sql"]("SELECT count(*) FROM orders")[0][0] == before


def test_summary_uses_real_inventory_quote_total(live_graph, api):
    state = plan_state()
    quote = api("inventory", "POST", "/vendor/VENDOR-COMMUNITY/quote", json={"sku": "RICE-5KG", "qty": 250})
    assert quote.status_code == 200
    state["staged"] = [{"type": "order", "step": state["plan"]["steps"][0], "result": quote.json()}]
    summary = build_summary(state)
    assert summary["queued"]["total_sgd"] == quote.json()["total_price_sgd"] == 562.50


def test_commit_places_the_staged_order_only_after_approval(live_graph, api, stack):
    state = plan_state()
    state["approval"] = "approved"
    quote = api("inventory", "POST", "/vendor/VENDOR-COMMUNITY/quote", json={"sku": "RICE-5KG", "qty": 250}).json()
    state["staged"] = [{"type": "order", "step": state["plan"]["steps"][0], "result": quote}]
    before = stack["sql"]("SELECT count(*) FROM orders")[0][0]
    commit(state)
    assert stack["sql"]("SELECT count(*) FROM orders")[0][0] == before + 1


@pytest.mark.parametrize("step", [
    {"action": "place_order", "sku": "RICE-5KG", "qty": -1, "vendor_id": "VENDOR-HARVEST"},
    {"action": "place_order", "sku": "RICE-5KG", "qty": 0, "vendor_id": "VENDOR-HARVEST"},
    {"action": "place_order", "sku": "RICE-5KG", "qty": 250},
    {"action": "reallocate_lot", "sku": "RICE-5KG", "qty": 1},
])
def test_typed_plan_rejects_non_executable_steps(step):
    with pytest.raises(ValidationError):
        PlanStep.model_validate(step)


def test_retry_after_is_available_to_adapt(monkeypatch):
    import httpx

    class Client:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            return httpx.Response(429, headers={"Retry-After": "7"}, json={
                "code": "RATE_LIMITED", "message": "Wait", "remedy_hint": "Use Retry-After", "alternatives": []})

    monkeypatch.setattr(settings, "fake_inventory", False)
    monkeypatch.setattr(services.httpx, "Client", Client)
    with pytest.raises(services.VendorError) as caught:
        services.vendor_order("VENDOR-HARVEST", "RICE-5KG", 250)
    error = caught.value
    assert getattr(error, "retry_after_seconds", None) == 7 or error.body.get("retry_after_seconds") == 7


def test_all_five_errors_reach_adapt_with_body_intact(monkeypatch, tmp_path):
    from orchestrator import llm
    from orchestrator.state import Adaptation
    monkeypatch.setattr(settings, "fake_llm", True)
    for flag in ("fake_inventory", "fake_feedback", "fake_pricing"):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "spend.json")
    for status, code in [(400, "MOQ_NOT_MET"), (409, "OUT_OF_STOCK"), (422, "LEAD_TIME_EXCEEDED"),
                         (410, "LOT_EXPIRED"), (429, "RATE_LIMITED")]:
        seen = []
        alternatives = [{"action": "choose_vendor", "vendor_id": "VENDOR-COMMUNITY"}]
        def fail(vendor_id, sku, qty):
            raise services.VendorError(status, code, "QA failure", alternatives, "QA remedy")
        def adapt(step, error, attempt_no):
            seen.append(error)
            return Adaptation(revised_step=PlanStep(**step), what_changed="Retry"), None
        monkeypatch.setattr(services, "vendor_order", fail)
        monkeypatch.setattr(llm, "adapt_step", adapt)
        saver = make_checkpointer(str(tmp_path / f"{code}.db"))
        try:
            graph = compile_graph(saver)
            state = new_state(code)
            result = graph.invoke(state, {"configurable": {"thread_id": code}})
            assert "__interrupt__" in result
            assert len(seen) == settings.max_retries == 3
            assert all(e["code"] == code and e["alternatives"] == alternatives for e in seen)
            assert code in result["halt_reason"]
        finally:
            saver.conn.close()
