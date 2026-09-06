"""
Routing and cost-control tests. All run under FAKE_LLM=1, so the whole suite
costs nothing and can be run constantly.
"""
from __future__ import annotations

import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END
from langgraph.types import Command

from orchestrator import ledger, services
from orchestrator.config import settings
from orchestrator.graph import (build_graph, route_after_act, route_after_adapt,
                                route_after_approval, route_after_predict)
from orchestrator.state import new_state


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Every test gets its own ledger and checkpoint DB."""
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "spend.json")
    monkeypatch.setattr(settings, "fake_llm", True)
    for flag in ("fake_services", "fake_inventory", "fake_feedback", "fake_pricing"):
        monkeypatch.setattr(settings, flag, True)
    yield


@pytest.fixture
def graph(tmp_path):
    conn = sqlite3.connect(tmp_path / "cp.db", check_same_thread=False)
    return build_graph().compile(checkpointer=SqliteSaver(conn))


def run(graph, thread="t1", ctype="B", decision="approved"):
    cfg = {"configurable": {"thread_id": thread}}
    res = graph.invoke(new_state(thread, ctype), cfg)
    if "__interrupt__" in res:
        payload = res["__interrupt__"][0].value
        res = graph.invoke(Command(resume={"decision": decision}), cfg)
        return res, payload
    return res, None


# ----------------------------------------------------------------- routing --
def test_route_predict_ends_on_halt():
    assert route_after_predict({"halt_reason": "budget"}) == END


def test_route_predict_ends_with_no_steps():
    assert route_after_predict({"plan": {"steps": []}}) == END


def test_route_act_to_adapt_on_error():
    assert route_after_act({"last_error": {"code": "MOQ_NOT_MET"}}) == "adapt"


def test_route_act_continues_through_steps():
    st = {"plan": {"steps": [{}, {}]}, "current_step": 1}
    assert route_after_act(st) == "act"


def test_route_act_to_approval_when_done():
    st = {"plan": {"steps": [{}, {}]}, "current_step": 2}
    assert route_after_act(st) == "approval"


def test_route_adapt_escalates_on_halt():
    assert route_after_adapt({"halt_reason": "cap hit"}) == "approval"


def test_route_approval_gates_commit():
    assert route_after_approval({"approval": "approved"}) == "commit"
    assert route_after_approval({"approval": "rejected"}) == END


# ------------------------------------------------------------- end-to-end --
def test_only_pricing_live_still_degrades_cleanly(graph, monkeypatch):
    """Per-service flags let workstreams integrate one at a time.

    SENSE only calls the price service when something is actually at risk AND
    carries a dspi_series, so with fixture inventory it may make no price call
    at all — that is correct, not a silent failure. What must hold either way
    is that the run completes.
    """
    monkeypatch.setattr(settings, "fake_pricing", False)
    monkeypatch.setattr(settings, "pricing_url", "http://127.0.0.1:9")
    res, summary = run(graph, "e2e-partial", "B", "approved")
    assert res["degraded_services"] in ([], ["price_forecast"])
    assert res["outcome"]["kind"] == "purchase_order"


def test_full_run_commits_purchase_order(graph):
    res, summary = run(graph, "e2e-b", "B", "approved")
    assert summary is not None, "graph must pause for human approval"
    assert res["outcome"]["kind"] == "purchase_order"
    assert res["outcome"]["total_sgd"] > 0


def test_rejection_commits_nothing(graph):
    res, _ = run(graph, "e2e-rej", "B", "rejected")
    assert res.get("outcome") is None
    assert res["approval"] == "rejected"


def test_donation_fed_charity_gets_checklist(graph):
    res, _ = run(graph, "e2e-a", "A", "approved")
    assert res["outcome"]["kind"] == "acquisition_checklist"


def test_the_demo_beat_moq_then_vendor_switch(graph):
    """The load-bearing scenario: 400 MOQ_NOT_MET -> raise qty -> switch vendor."""
    _, summary = run(graph, "e2e-moq")
    adaptations = summary["adaptations"]
    assert len(adaptations) == 1
    assert adaptations[0]["error_code"] == "MOQ_NOT_MET"
    assert "VENDOR-COMMUNITY" in adaptations[0]["what_changed"]

    order = next(s for s in summary["queued"]["steps"]
                 if s["action"] == "place_order")
    assert order["qty"] == 250, "should have been raised to the MOQ"
    assert order["vendor_id"] == "VENDOR-COMMUNITY", "should have switched to the cheaper vendor"


def test_unmatched_need_is_flagged_for_human(graph):
    _, summary = run(graph, "e2e-gap")
    assert any(s["action"] == "flag_for_human" for s in summary["queued"]["steps"])


def test_approval_summary_has_all_four_panels(graph):
    _, summary = run(graph, "e2e-panels")
    for panel in ("sensed", "predicted", "queued", "adaptations"):
        assert panel in summary


# ------------------------------------------------------- failure handling --
def test_retry_cap_escalates_instead_of_looping(graph, monkeypatch):
    """An uncapped adapt loop is the one bug that can drain the budget."""
    def always_fail(vendor_id, sku, qty):
        raise services.VendorError(400, "MOQ_NOT_MET", "nope",
                                   [{"minimum_qty": 999_999}])
    # ACT stages via vendor_quote now (quotes cost nothing and commit nothing);
    # vendor_order is only reached from COMMIT.
    monkeypatch.setattr(services, "vendor_quote", always_fail)
    monkeypatch.setattr(services, "vendor_order", always_fail)

    _, summary = run(graph, "e2e-cap")
    assert summary["guardrails"]["halt_reason"], "should escalate with a reason"
    assert len(summary["adaptations"]) <= settings.max_retries


def test_degrades_when_services_are_down(graph, monkeypatch):
    for flag in ("fake_services", "fake_inventory", "fake_feedback", "fake_pricing"):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "inventory_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "feedback_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "pricing_url", "http://127.0.0.1:9")

    res, summary = run(graph, "e2e-degraded")
    # The graph must keep reasoning, not crash.
    assert set(res["degraded_services"]) == {
        "inventory", "alerts", "unmet_needs", "inbound_orders"}
    assert summary is not None


def test_checkpoint_survives_a_new_graph_instance(tmp_path):
    """A pending approval must survive a process restart — hence SqliteSaver."""
    db = tmp_path / "cp.db"
    cfg = {"configurable": {"thread_id": "resume-me"}}

    g1 = build_graph().compile(
        checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    res = g1.invoke(new_state("resume-me", "B"), cfg)
    assert "__interrupt__" in res

    # Simulate a restart: brand-new graph + connection, same DB file.
    g2 = build_graph().compile(
        checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    res2 = g2.invoke(Command(resume={"decision": "approved"}), cfg)
    assert res2["outcome"]["kind"] == "purchase_order"


# ------------------------------------------------------------ cost control --
def test_fake_mode_makes_zero_bedrock_calls(graph):
    run(graph, "e2e-cost")
    assert ledger.load()["calls"] == 0, "FAKE_LLM must never call Bedrock"


def test_budget_cap_raises_before_spending(monkeypatch):
    monkeypatch.setattr(settings, "max_session_spend_usd", 0.01)
    ledger.reset()
    led = ledger.load()
    led["usd"] = 0.02
    ledger._save(led)
    with pytest.raises(ledger.BudgetExceeded):
        ledger.check_budget()


def test_ledger_accounts_for_cache_discount():
    class U:
        input_tokens, output_tokens = 1000, 100
        cache_read_input_tokens, cache_creation_input_tokens = 5000, 0
    ledger.reset()
    led = ledger.record("anthropic.claude-haiku-4-5", U())
    # 1000 + 5000*0.1 = 1500 effective input tokens, not 6000
    assert led["cache_read"] == 5000
    assert led["usd"] == pytest.approx((1500 * 1.0 + 100 * 5.0) / 1e6, rel=1e-6)


@pytest.mark.parametrize('charity_type', ['A', 'B'])
def test_committing_calls_only_happen_after_approval(graph, monkeypatch, charity_type):
    calls = []
    original = services.vendor_order
    def order(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(services, 'vendor_order', order)
    thread = 'explicit-boundary-' + charity_type
    cfg = {'configurable': {'thread_id': thread}}
    result = graph.invoke(new_state(thread, charity_type), cfg)
    assert '__interrupt__' in result and calls == []
    result = graph.invoke(Command(resume={'decision': 'approved'}), cfg)
    assert len(calls) == (1 if charity_type == 'B' else 0)
    if calls:
        assert calls[0]['idempotency_key'] == thread + ':0'
        assert calls[0]['expected_unit_price_sgd'] > 0


def test_quote_only_plan_does_not_commit(graph, monkeypatch):
    from orchestrator import llm
    from orchestrator.state import Plan
    plan = Plan(stockout_sku='RICE-5KG', days_until_failure=8, reasoning='quote only', steps=[
        {'action': 'request_quote', 'sku': 'RICE-5KG', 'qty': 250, 'vendor_id': 'VENDOR-COMMUNITY'}])
    monkeypatch.setattr(llm, 'predict_plan', lambda *a, **kw: (plan, None))
    monkeypatch.setattr(services, 'vendor_order', lambda *a, **kw: pytest.fail('quote committed'))
    result, summary = run(graph, 'only-quote')
    assert summary['queued']['total_sgd'] == 0
    assert result['outcome']['orders'] == []


def test_direct_commit_requires_approval(monkeypatch):
    from orchestrator.nodes.commit import commit
    monkeypatch.setattr(services, 'vendor_order', lambda *a, **kw: pytest.fail('unapproved commit'))
    result = commit(new_state('unapproved'))
    assert result['halt_reason'] and not result.get('outcome')


def test_single_order_cap_is_per_order():
    from orchestrator.nodes.approval import build_summary
    state = new_state('money')
    state['staged'] = [{'type': 'order', 'step': {'action': 'place_order'},
                        'result': {'total_price_sgd': 1000}} for _ in range(2)]
    summary = build_summary(state)
    assert summary['queued']['total_sgd'] == 2000
    assert not summary['guardrails']['exceeds_single_order_cap']
    state['staged'][0]['result']['total_price_sgd'] = 1500.01
    assert build_summary(state)['guardrails']['exceeds_single_order_cap']


def test_donation_checklist_ranks_need_and_separates_flags():
    from orchestrator.nodes.commit import commit
    state = new_state('ranked', 'A')
    state['approval'] = 'approved'
    state['state_of_world'] = {'inventory': [
        {'sku': 'LOW', 'on_hand': 9, 'avg_daily_draw': 1},
        {'sku': 'HIGH', 'on_hand': 2, 'avg_daily_draw': 1}],
        'unmet_needs': {'ranked': [{'mentioned_skus': ['LOW'], 'urgency': 5},
                                  {'mentioned_skus': ['HIGH'], 'urgency': 3}]}}
    state['staged'] = [{'step': {'action': 'place_order', 'sku': sku, 'qty': 10}}
                       for sku in ['LOW', 'HIGH']]
    state['staged'].append({'step': {'action': 'flag_for_human', 'sku': 'GAP', 'qty': 0}})
    outcome = commit(state)['outcome']
    assert [i['sku'] for i in outcome['items']] == ['HIGH', 'LOW']
    assert [i['priority_score'] for i in outcome['items']] == [24, 5]
    assert len(outcome['review_flags']) == 1


def test_rate_limit_waits_before_readaptation(monkeypatch):
    import importlib
    module = importlib.import_module('orchestrator.nodes.adapt')
    waits = []
    monkeypatch.setattr(module.time, 'sleep', waits.append)
    state = new_state('wait')
    from orchestrator import fixtures
    state['plan'] = fixtures.FAKE_PLAN
    state['last_error'] = {'code': 'RATE_LIMITED', 'retry_after_seconds': 7,
                           'failed_step': fixtures.FAKE_PLAN['steps'][0], 'step_index': 0}
    result = module.adapt(state)
    assert waits == [7] and result['retry_count'] == 1


def test_legacy_checkpoint_cannot_commit(monkeypatch):
    from orchestrator.nodes.commit import commit
    monkeypatch.setattr(services, 'vendor_order', lambda *a, **kw: pytest.fail('legacy commit'))
    state = new_state('old-checkpoint')
    del state['approval_version']
    state['approval'] = 'approved'
    assert 'Legacy approval' in commit(state)['halt_reason']
