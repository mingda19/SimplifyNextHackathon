"""Typed graph state and the models the LLM agent's tools are constrained to."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field, ConfigDict, model_validator


def _merge_dicts(current: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer for `state_of_world`: shallow-merge instead of overwrite.

    `price_forecaster` and `feedback_extraction` both merge into this field
    via `Command(update={"state_of_world": {...}})` (see `tools/_util.py`).
    Without a reducer, LangGraph raises `InvalidUpdateError` the moment the
    agent calls both tools in the SAME turn (confirmed directly -- "Can
    receive only one value per step") -- a plain, non-Annotated field can only
    take one write per superstep, and a `ToolNode` batch executing several
    tool calls at once produces one write per tool. A single agent turn
    calling two read tools together is exactly the kind of turn-efficient
    behavior `settings.max_agent_turns` should be encouraging, not something
    that should crash the run.
    """
    return {**(current or {}), **(patch or {})}

# Actions `action_generator` can actually dispatch. Constraining the tool's
# arg schema to this Literal means a hallucinated verb becomes a tool-call
# validation error (visible to the model as a ToolMessage, self-correctable)
# rather than a crash mid-run.
Action = Literal["request_quote", "place_order", "reallocate_lot", "flag_for_human"]

# Actions that move money or stock. These are staged, never executed before
# human approval.
COMMITTING_ACTIONS: frozenset[str] = frozenset({"place_order", "reallocate_lot"})
APPROVAL_VERSION = 2


class PlanStep(BaseModel):
    """`action_generator`'s argument schema, reused unchanged.

    This used to be one step inside an upfront `Plan.steps` list emitted by a
    single `predict` call. In the tool-calling design there is no upfront
    plan — the agent calls `action_generator` once per action it decides to
    take, so this model is now the tool's input schema directly, called
    however many times the loop runs. The validation rules (qty>0 for
    executable actions, vendor_id/lot_id requirements) are exactly as load
    -bearing as before: a violation here becomes a ToolMessage error the
    model sees and retries from, not a schema exception that kills the run.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Action
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(default=0, ge=0, le=2**31 - 1, strict=True)
    vendor_id: str | None = Field(default=None, min_length=1, max_length=64)
    lot_id: str | None = Field(default=None, min_length=1, max_length=64)
    rationale: str = ""

    @model_validator(mode="after")
    def executable(self):
        if self.action != "flag_for_human" and self.qty <= 0:
            raise ValueError("executable steps require a positive quantity")
        if self.action in {"place_order", "request_quote"} and not self.vendor_id:
            raise ValueError("purchase and quote steps require vendor_id")
        if self.action == "reallocate_lot" and not self.lot_id:
            raise ValueError("reallocation requires lot_id")
        return self


class AgentState(MessagesState, total=False):
    """
    Graph state. Extends LangGraph's `MessagesState` (`messages`, reduced by
    `add_messages`) with the bookkeeping fields the rest of the graph needs.

    `state_of_world` is a shared scratchpad, not a one-shot snapshot: `seed`
    pre-populates it with inventory/alerts/inbound (deterministic, $0), and
    the `price_forecaster`/`feedback_extraction` tools merge their own
    results into it as the agent calls them mid-loop, via
    `InjectedState`-read + `Command(update={"state_of_world": {...}})`. This
    keeps `finalize`'s dashboard summary reading the same dict shape it
    always has, whether a given field was populated by `seed` or by a tool
    call three turns later.

    `staged` is `Annotated[..., operator.add]` (not a bare list) because
    `action_generator` returns `Command(update={"staged": [...]})` from
    inside a `ToolNode` — a plain field would be *overwritten* on each call,
    not appended to; the reducer makes each call's single new item append
    correctly, mirroring `attempts`, which already worked this way.

    `diagnosis` replaces the old `Plan.stockout_sku`/`days_until_failure`/
    `reasoning` fields — the agent calls a no-op `submit_diagnosis` tool once,
    early, so `finalize`'s summary has somewhere to read them from without an
    upfront `Plan` object.

    `agent_turns` replaces `current_step`/`retry_count`: there is no more
    per-step index to track (the agent decides its own sequence of tool
    calls), just a turn counter so `agent.py` can enforce
    `settings.max_agent_turns` and force a halt if the loop runs away.
    """

    thread_id: str
    approval_version: int
    charity_type: Literal["A", "B"]        # A = donation-fed, B = budget-funded

    state_of_world: Annotated[dict[str, Any], _merge_dicts]
    degraded_services: list[str]

    diagnosis: dict[str, Any] | None
    agent_turns: int
    attempts: Annotated[list[dict[str, Any]], operator.add]   # append, don't overwrite
    staged: Annotated[list[dict[str, Any]], operator.add]     # append, don't overwrite

    approval: Literal["pending", "approved", "rejected"] | None
    approved_steps: list[int] | None        # step indexes the human approved
    outcome: dict[str, Any] | None

    token_ledger: dict[str, Any]
    halt_reason: str | None


def new_state(thread_id: str, charity_type: str = "B") -> AgentState:
    return AgentState(
        messages=[],
        thread_id=thread_id,
        approval_version=APPROVAL_VERSION,
        charity_type=charity_type,  # type: ignore[arg-type]
        state_of_world={},
        degraded_services=[],
        diagnosis=None,
        agent_turns=0,
        attempts=[],
        staged=[],
        approval=None,
        approved_steps=None,
        outcome=None,
        token_ledger={},
        halt_reason=None,
    )
