"""
Graph mechanics tests, driven by a scripted stand-in for `llm.agent_step`
-- never real Bedrock, so this whole suite costs $0 and can run constantly.

There is no more `FAKE_LLM` production flag (see `config.py`/`llm.py`): the
agent node always calls real Bedrock. What replaces cheap testing here is
NOT a fake-mode code path but a plain `pytest` monkeypatch of
`orchestrator.llm.agent_step` with a fixed script of canned `AIMessage`s --
test-only, never reachable from production code. Tool EXECUTION is real:
`ToolNode` dispatches to the actual tool functions in `orchestrator/tools/`,
which hit `orchestrator/services.py`'s fixture-backed fake HTTP layer
(`FAKE_SERVICES=1`, unrelated to the LLM). Only the model call itself is
scripted.
"""
from __future__ import annotations

import sqlite3

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from orchestrator import ledger, llm, services
from orchestrator.config import settings
from orchestrator.graph import build_graph
# `from orchestrator.nodes.finalize import X` (not `import ... as finalize_mod`):
# nodes/__init__.py does `from .finalize import finalize`, which rebinds the
# `finalize` ATTRIBUTE on the `orchestrator.nodes` package object to the
# function -- `import orchestrator.nodes.finalize as x` resolves through that
# attribute and silently gets the function instead of the module. A direct
# `from module import name` looks `orchestrator.nodes.finalize` up in
# sys.modules instead, which is unaffected by the __init__.py rebind.
from orchestrator.nodes.finalize import _COMMITTED, _checklist, build_summary
from orchestrator.state import new_state


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Every test gets its own ledger, checkpoint DB, and idempotency set."""
    monkeypatch.setattr(settings, "ledger_path", tmp_path / "spend.json")
    for flag in ("fake_services", "fake_inventory", "fake_feedback", "fake_pricing"):
        monkeypatch.setattr(settings, flag, True)
    _COMMITTED.clear()
    yield


@pytest.fixture
def graph(tmp_path):
    conn = sqlite3.connect(tmp_path / "cp.db", check_same_thread=False)
    return build_graph().compile(checkpointer=SqliteSaver(conn))


# ------------------------------------------------------------- LLM script --
def tc(call_id: str, name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def script_llm(monkeypatch, turns: list[list[dict]]) -> None:
    """Monkeypatch `llm.agent_step` to a fixed script.

    `turns[i]` is the list of tool calls the i-th agent turn makes. Once the
    script is exhausted, every further call returns an AIMessage with no
    tool calls -- exactly what a real model does when it's done, so
    `tools_condition` routes to `finalize` the same way either path would.
    """
    state = {"i": 0}

    def _agent_step(messages, tools):
        i = state["i"]
        state["i"] += 1
        if i < len(turns):
            return AIMessage(content="", tool_calls=turns[i]), None
        return AIMessage(content="done, nothing further to stage"), None

    monkeypatch.setattr(llm, "agent_step", _agent_step)


def run(graph, thread="t1", decision="approved", approved_steps=None):
    cfg = {"configurable": {"thread_id": thread}}
    res = graph.invoke(new_state(thread, "B"), cfg)
    if "__interrupt__" in res:
        payload = res["__interrupt__"][0].value
        resume = {"approved_steps": approved_steps} if approved_steps is not None \
            else {"decision": decision}
        res = graph.invoke(Command(resume=resume), cfg)
        return res, payload
    return res, None


def run_a(graph, thread="t1", decision="approved"):
    cfg = {"configurable": {"thread_id": thread}}
    res = graph.invoke(new_state(thread, "A"), cfg)
    if "__interrupt__" in res:
        payload = res["__interrupt__"][0].value
        res = graph.invoke(Command(resume={"decision": decision}), cfg)
        return res, payload
    return res, None


DIAGNOSIS = {"stockout_sku": "RICE-5KG", "days_until_failure": 8,
             "reasoning": "test diagnosis"}


# ------------------------------------------------------------- end-to-end --
def test_full_run_commits_purchase_order(graph, monkeypatch):
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY",
                                      "rationale": "cover shortfall"}),
    ]])
    res, summary = run(graph, "e2e-b")
    assert summary is not None, "graph must pause for human approval"
    assert res["outcome"]["kind"] == "purchase_order"
    assert res["outcome"]["total_sgd"] > 0


def test_rejection_commits_nothing(graph, monkeypatch):
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])
    res, _ = run(graph, "e2e-rej", decision="rejected")
    assert res.get("outcome") is None
    assert res["approval"] == "rejected"


def test_donation_fed_charity_gets_checklist(graph, monkeypatch):
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])
    res, _ = run_a(graph, "e2e-a")
    assert res["outcome"]["kind"] == "acquisition_checklist"


def test_the_demo_beat_moq_then_vendor_switch(graph, monkeypatch):
    """The load-bearing scenario, now via REAL tool execution against the
    fixture vendors (VENDOR-HARVEST moq=250, VENDOR-COMMUNITY moq=100 with a
    volume break to 1.98 at 250+ units) -- not a canned tool result. The
    script only stands in for the model deciding what to try next."""
    script_llm(monkeypatch, [
        [tc("c1", "submit_diagnosis", DIAGNOSIS),
         tc("c2", "action_generator",
            {"action": "place_order", "sku": "RICE-5KG", "qty": 200,
             "vendor_id": "VENDOR-HARVEST", "rationale": "initial order"})],
        [tc("c3", "action_generator",
            {"action": "place_order", "sku": "RICE-5KG", "qty": 250,
             "vendor_id": "VENDOR-COMMUNITY",
             "rationale": "Raised to VENDOR-HARVEST's 250 MOQ and switched to "
                          "VENDOR-COMMUNITY, whose volume price at 250 units "
                          "undercuts it"})],
    ])
    _, summary = run(graph, "e2e-moq")

    adaptations = summary["adaptations"]
    assert len(adaptations) == 1
    assert adaptations[0]["error_code"] == "MOQ_NOT_MET"
    assert "VENDOR-COMMUNITY" in adaptations[0]["what_changed"]

    order = next(s for s in summary["queued"]["steps"] if s["action"] == "place_order")
    assert order["qty"] == 250, "should have been raised to the MOQ"
    assert order["vendor_id"] == "VENDOR-COMMUNITY", "should have switched vendor"


def test_unmatched_need_is_flagged_for_human(graph, monkeypatch):
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator",
           {"action": "flag_for_human", "sku": "SOFT-FOOD-GAP", "qty": 0,
            "rationale": "no stocked SKU covers softer food for elderly"}),
    ]])
    _, summary = run(graph, "e2e-gap")
    assert any(s["action"] == "flag_for_human" for s in summary["queued"]["steps"])


def test_approval_summary_has_all_four_panels(graph, monkeypatch):
    script_llm(monkeypatch, [[tc("c1", "submit_diagnosis", DIAGNOSIS)]])
    _, summary = run(graph, "e2e-panels")
    for panel in ("sensed", "predicted", "queued", "adaptations"):
        assert panel in summary


def test_price_forecaster_and_feedback_extraction_same_turn_do_not_crash(graph, monkeypatch):
    """Regression test for the InvalidUpdateError two Command-returning tools
    writing `state_of_world` in the same batch used to raise -- confirmed via
    a standalone repro before `_merge_dicts` was added as its reducer."""
    script_llm(monkeypatch, [
        [tc("c1", "price_forecaster", {"series": "Rice"}),
         tc("c2", "feedback_extraction", {})],
        [tc("c3", "submit_diagnosis", DIAGNOSIS)],
    ])
    res, summary = run(graph, "e2e-same-turn")
    assert summary is not None
    sow = res["state_of_world"]
    assert "Rice" in (sow.get("price_forecast") or {}).get("forecasts", {})
    assert "unmet_needs" in sow


# ------------------------------------------------------------- validation --
def test_action_generator_invalid_args_is_recoverable(graph, monkeypatch):
    """qty=0 on an executable action must come back as a ToolMessage the
    model can retry from, not a crash -- mirrors the old schema-repair
    behavior, now handled inside the tool itself rather than a special
    retry loop in llm.py."""
    script_llm(monkeypatch, [
        [tc("c1", "submit_diagnosis", DIAGNOSIS),
         tc("c2", "action_generator",
            {"action": "place_order", "sku": "RICE-5KG", "qty": 0,
             "vendor_id": "VENDOR-COMMUNITY"})],
        [tc("c3", "action_generator",
            {"action": "place_order", "sku": "RICE-5KG", "qty": 150,
             "vendor_id": "VENDOR-COMMUNITY", "rationale": "corrected qty"})],
    ])
    res, summary = run(graph, "e2e-invalid-args")
    assert len(res["staged"]) == 1, "only the corrected call should have staged"
    assert summary["queued"]["total_sgd"] > 0


def test_reallocate_lot_action_generator_works(graph, monkeypatch):
    """Exercises the newly-implemented `services.allocate_lot` (previously
    called by the old act.py but never implemented -- see services.py)."""
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator",
           {"action": "reallocate_lot", "sku": "RICE-5KG", "qty": 10,
            "lot_id": "LOT-TEST-1", "rationale": "move donated stock"}),
    ]])
    res, _ = run(graph, "e2e-reallocate")
    assert res["outcome"]["allocations"], "reallocation should have committed"


# ------------------------------------------------------- failure handling --
def test_turn_cap_with_nothing_staged_fails_cleanly_no_interrupt(graph, monkeypatch):
    """An uncapped agent loop calling Bedrock forever is the one bug in this
    design that can actually drain the budget -- same concern the old
    adapt.py retry cap existed for, generalized to any turn.

    Every action_generator call here fails (qty=1 is always below MOQ), so
    nothing is ever staged -- there is nothing for a human to review. This
    should skip the interrupt entirely and come back as a clean halt
    (`summary is None`, `halt_reason` set directly on the result), not a
    `pending_approval` with an empty plan -- see finalize.py's early-return
    for exactly this case."""
    monkeypatch.setattr(settings, "max_agent_turns", 2)

    def always_retry(messages, tools):
        # never stops calling tools, however many turns it gets
        return AIMessage(content="", tool_calls=[
            tc("cX", "action_generator",
               {"action": "place_order", "sku": "RICE-5KG", "qty": 1,
                "vendor_id": "VENDOR-HARVEST"}),
        ]), None

    monkeypatch.setattr(llm, "agent_step", always_retry)
    res, summary = run(graph, "e2e-cap")
    assert summary is None, "nothing was ever staged -- no interrupt should fire"
    assert res.get("halt_reason") and "turn limit" in res["halt_reason"]
    assert not res.get("staged")


def test_turn_cap_with_staged_actions_preserves_and_commits_them(graph, monkeypatch):
    """The companion case: the turn cap hits AFTER real actions already
    staged successfully. That work must survive to the human -- and
    approving it must actually commit it, not silently no-op because a
    stale halt_reason from the turn cap blocks the commit path."""
    monkeypatch.setattr(settings, "max_agent_turns", 2)

    def stage_then_cap(messages, tools):
        return AIMessage(content="", tool_calls=[
            tc("c1", "submit_diagnosis", DIAGNOSIS),
            tc("c2", "action_generator",
               {"action": "place_order", "sku": "RICE-5KG", "qty": 150,
                "vendor_id": "VENDOR-COMMUNITY"}),
        ]), None

    monkeypatch.setattr(llm, "agent_step", stage_then_cap)
    res, summary = run(graph, "e2e-cap-preserved")
    assert summary is not None, "staged work exists -- must go through interrupt for review"
    assert summary["guardrails"]["halt_reason"] and "turn limit" in summary["guardrails"]["halt_reason"]
    # The mock reissues the same call every turn it's given (max_agent_turns=2
    # means 2 turns run before the cap trips on turn 3), so 2 items stage --
    # the exact count isn't the point, only that something real survived.
    assert len(summary["queued"]["steps"]) == 2

    # Approving it must actually commit -- this used to bail out silently
    # because `halt_reason` was still set at the commit-gating check.
    assert res["outcome"]["kind"] == "purchase_order"
    assert res["outcome"]["total_sgd"] > 0
    assert res.get("halt_reason") is None, "a successful commit must clear the stale halt_reason"


def test_rejected_run_is_not_mislabeled_as_halted(graph, monkeypatch):
    """`decide()` in api.py treats any truthy `halt_reason` as status='failed'.
    A human rejecting a plan is a normal outcome, not a failure -- it must
    not leave halt_reason set, or every rejected run shows up as 'failed'
    in the dashboard next to genuine agent errors."""
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])
    res, _ = run(graph, "e2e-reject-label", decision="rejected")
    assert res["approval"] == "rejected"
    assert res.get("halt_reason") is None


def test_degrades_when_services_are_down(graph, monkeypatch):
    for flag in ("fake_services", "fake_inventory", "fake_feedback", "fake_pricing"):
        monkeypatch.setattr(settings, flag, False)
    monkeypatch.setattr(settings, "inventory_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "feedback_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "pricing_url", "http://127.0.0.1:9")
    script_llm(monkeypatch, [[tc("c1", "submit_diagnosis", DIAGNOSIS)]])

    res, summary = run(graph, "e2e-degraded")
    # seed only pre-fetches inventory/alerts/inbound now (feedback/price are
    # tools) -- so seed-level degradation covers only those three.
    assert set(res["degraded_services"]) == {"inventory", "alerts", "inbound_orders"}
    assert summary is not None


def test_checkpoint_survives_a_new_graph_instance(tmp_path, monkeypatch):
    """A pending approval must survive a process restart — hence SqliteSaver."""
    db = tmp_path / "cp.db"
    cfg = {"configurable": {"thread_id": "resume-me"}}
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])

    g1 = build_graph().compile(
        checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    res = g1.invoke(new_state("resume-me", "B"), cfg)
    assert "__interrupt__" in res

    # Simulate a restart: brand-new graph + connection, same DB file. The LLM
    # mock is process-global (monkeypatch), so no re-scripting needed here --
    # resume never calls the agent node again, only finalize.
    g2 = build_graph().compile(
        checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    res2 = g2.invoke(Command(resume={"decision": "approved"}), cfg)
    assert res2["outcome"]["kind"] == "purchase_order"


# ------------------------------------------------------------ cost control --
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


@pytest.mark.parametrize("charity_type", ["A", "B"])
def test_committing_calls_only_happen_after_approval(graph, monkeypatch, charity_type):
    calls = []
    original = services.vendor_order

    def order(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(services, "vendor_order", order)
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "place_order", "sku": "RICE-5KG",
                                      "qty": 150, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])

    thread = f"explicit-boundary-{charity_type}"
    cfg = {"configurable": {"thread_id": thread}}
    result = graph.invoke(new_state(thread, charity_type), cfg)
    assert "__interrupt__" in result and calls == []
    result = graph.invoke(Command(resume={"decision": "approved"}), cfg)
    assert len(calls) == (1 if charity_type == "B" else 0)


def test_quote_only_action_does_not_commit(graph, monkeypatch):
    script_llm(monkeypatch, [[
        tc("c1", "submit_diagnosis", DIAGNOSIS),
        tc("c2", "action_generator", {"action": "request_quote", "sku": "RICE-5KG",
                                      "qty": 250, "vendor_id": "VENDOR-COMMUNITY"}),
    ]])
    monkeypatch.setattr(services, "vendor_order",
                        lambda *a, **kw: pytest.fail("a quote must never commit"))
    result, summary = run(graph, "only-quote")
    assert summary["queued"]["total_sgd"] == 0, "a quote has no order value"
    assert result["outcome"]["orders"] == []


# --------------------------------------------------- pure-function tests --
# `build_summary` and `_checklist` are plain functions (no `interrupt()`
# call of their own -- only the `finalize` node wraps them with one), so
# they can still be unit-tested directly on a hand-built state, unlike
# `finalize` itself which now always needs real graph/interrupt context
# since approval+commit were merged into one node.
def test_single_order_cap_is_per_order():
    state = new_state("money")
    state["staged"] = [{"type": "order", "step": {"action": "place_order"},
                        "result": {"total_price_sgd": 1000}} for _ in range(2)]
    summary = build_summary(state)
    assert summary["queued"]["total_sgd"] == 2000
    assert not summary["guardrails"]["exceeds_single_order_cap"]
    state["staged"][0]["result"]["total_price_sgd"] = 1500.01
    assert build_summary(state)["guardrails"]["exceeds_single_order_cap"]


def test_donation_checklist_ranks_need_and_separates_flags():
    state = new_state("ranked", "A")
    state["state_of_world"] = {"inventory": [
        {"sku": "LOW", "on_hand": 9, "avg_daily_draw": 1},
        {"sku": "HIGH", "on_hand": 2, "avg_daily_draw": 1}],
        "unmet_needs": {"ranked": [{"mentioned_skus": ["LOW"], "urgency": 5},
                                   {"mentioned_skus": ["HIGH"], "urgency": 3}]}}
    staged = [{"step": {"action": "place_order", "sku": sku, "qty": 10}}
              for sku in ["LOW", "HIGH"]]
    staged.append({"step": {"action": "flag_for_human", "sku": "GAP", "qty": 0}})
    outcome = _checklist(state, staged)
    assert [i["sku"] for i in outcome["items"]] == ["HIGH", "LOW"]
    assert [i["priority_score"] for i in outcome["items"]] == [24, 5]
    assert len(outcome["review_flags"]) == 1


def test_legacy_checkpoint_cannot_commit(graph, monkeypatch):
    """`finalize` always calls `interrupt()` before checking anything -- see
    its module docstring -- so this can no longer be tested by calling the
    node function directly with a pre-set `approval`; it has to go through a
    real invoke + resume, with the checkpointed state doctored in between to
    simulate a pre-APPROVAL_VERSION checkpoint."""
    script_llm(monkeypatch, [[tc("c1", "submit_diagnosis", DIAGNOSIS)]])
    thread = "old-checkpoint"
    cfg = {"configurable": {"thread_id": thread}}
    monkeypatch.setattr(services, "vendor_order",
                        lambda *a, **kw: pytest.fail("legacy commit"))

    result = graph.invoke(new_state(thread, "B"), cfg)
    assert "__interrupt__" in result
    graph.update_state(cfg, {"approval_version": None})
    result = graph.invoke(Command(resume={"decision": "approved"}), cfg)
    assert "Legacy approval" in result["halt_reason"]
