"""Typed graph state and the models the LLM nodes are constrained to."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

# Actions `act` can actually dispatch. Constraining the model to this Literal
# means a hallucinated verb becomes a validation error, not a crash mid-demo.
Action = Literal["request_quote", "place_order", "reallocate_lot", "flag_for_human"]

# Actions that move money or stock. These are staged, never executed before
# human approval.
COMMITTING_ACTIONS: frozenset[str] = frozenset({"place_order"})


class PlanStep(BaseModel):
    action: Action
    sku: str
    qty: int = 0
    vendor_id: str | None = None
    rationale: str = ""


class Plan(BaseModel):
    """Output contract for the `predict` node."""

    stockout_sku: str
    days_until_failure: int
    reasoning: str
    steps: list[PlanStep] = Field(default_factory=list)


class Adaptation(BaseModel):
    """Output contract for the `adapt` node."""

    revised_step: PlanStep
    what_changed: str          # human-readable -> goes straight to the dashboard
    confidence: float = 0.5


class AgentState(TypedDict, total=False):
    """
    Graph state.

    Pydantic models are stored as plain dicts so the SQLite checkpointer can
    round-trip them without a custom serializer. Hydrate at the edges with
    `Plan.model_validate(state["plan"])`.
    """

    thread_id: str
    charity_type: Literal["A", "B"]        # A = donation-fed, B = budget-funded

    # PHASE 1
    state_of_world: dict[str, Any]
    degraded_services: list[str]

    # PHASE 2
    plan: dict[str, Any] | None

    # PHASE 3
    current_step: int
    last_error: dict[str, Any] | None
    retry_count: int
    attempts: Annotated[list[dict[str, Any]], operator.add]   # append, don't overwrite
    staged: list[dict[str, Any]]

    # PHASE 4
    approval: Literal["pending", "approved", "rejected"] | None
    outcome: dict[str, Any] | None

    # ops
    token_ledger: dict[str, Any]
    halt_reason: str | None


def new_state(thread_id: str, charity_type: str = "B") -> AgentState:
    return AgentState(
        thread_id=thread_id,
        charity_type=charity_type,  # type: ignore[arg-type]
        state_of_world={},
        degraded_services=[],
        plan=None,
        current_step=0,
        last_error=None,
        retry_count=0,
        attempts=[],
        staged=[],
        approval=None,
        outcome=None,
        token_ledger={},
        halt_reason=None,
    )
