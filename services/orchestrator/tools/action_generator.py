"""Tools: `action_generator` (stage one action) and `submit_diagnosis`.

`action_generator` is the direct successor of the old `act.py` dispatch
logic: it prices/validates ONE action against the live backend and STAGES
it, never commits it. `place_order` still only ever calls `vendor_quote()`,
never `vendor_order()` -- real money is spent exactly once, in `finalize`,
and only for steps a human has approved. This invariant is unchanged from
the old design; only the calling convention (a tool the agent chooses to
invoke, as many times as it wants, instead of one entry in a pre-built list)
is new.

On a domain refusal (`VendorError`, e.g. `MOQ_NOT_MET` with an
`alternatives` array) or a schema violation (bad args), the tool returns the
error as `ToolMessage` content instead of raising. The agent sees it on its
next turn and can retry `action_generator` with corrected args -- this is
what replaces the old dedicated `adapt` node/LLM call. See `AGENT_SYSTEM` in
`../llm.py` for the retry guidance carried forward from `ADAPT_SYSTEM`.

`submit_diagnosis` has no backend call and costs nothing beyond the turn
that calls it -- it exists purely so `finalize`'s dashboard summary has a
structured `stockout_sku`/`days_until_failure`/`reasoning` to read, the way
it used to read `Plan.stockout_sku` etc. from the old upfront `predict` call.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command
from pydantic import ValidationError

from .. import services
from ..state import Action, PlanStep

log = logging.getLogger(__name__)

_STAGED_TYPE = {"place_order": "order", "request_quote": "quote",
                "reallocate_lot": "allocation"}


@tool
def action_generator(
    action: Action,
    sku: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    qty: int = 0,
    vendor_id: str | None = None,
    lot_id: str | None = None,
    rationale: str = "",
) -> Command:
    """Stage one action against a SKU. Never commits -- a human approves
    before anything real happens.

    `action` is one of: `request_quote` (price a purchase without staging an
    order), `place_order` (stage an order for later commit -- requires
    `vendor_id`, `qty` >= 1), `reallocate_lot` (move stock between uses --
    requires `lot_id`, `qty` >= 1), `flag_for_human` (no backend call, `qty`
    may be 0 -- use this when you are not confident enough to act, e.g. no
    SKU exists for a need, or a fuzzy SKU match needs a human's judgement).
    Call this once per action you want to take; call it again with corrected
    arguments if a previous call came back with an error.
    """
    try:
        step = PlanStep(action=action, sku=sku, qty=qty, vendor_id=vendor_id,
                        lot_id=lot_id, rationale=rationale)
    except ValidationError as exc:
        errors = "; ".join(f"{e['loc']}: {e['msg']}" for e in exc.errors())
        log.info("action_generator: invalid args for %s/%s: %s", action, sku, errors)
        return Command(update={"messages": [ToolMessage(
            content=f"Invalid action: {errors}. Correct the arguments and retry.",
            tool_call_id=tool_call_id,
        )]})

    step_dict = step.model_dump()

    if step.action == "flag_for_human":
        return Command(update={
            "staged": [{"type": "flag", "step": step_dict}],
            "messages": [ToolMessage(
                content=f"Flagged for human review: {sku} -- {rationale}",
                tool_call_id=tool_call_id,
            )],
        })

    try:
        if step.action in ("place_order", "request_quote"):
            result = services.vendor_quote(step.vendor_id, step.sku, step.qty)
        else:  # reallocate_lot
            result = services.allocate_lot(step.sku, step.lot_id, step.qty,
                                           validate_only=True)
    except services.VendorError as exc:
        log.info("action_generator: %s/%s failed %s", step.action, step.sku,
                 exc.body["code"])
        return Command(update={"messages": [ToolMessage(
            content=str(exc.body), tool_call_id=tool_call_id,
        )]})
    except services.ServiceError as exc:
        return Command(update={"messages": [ToolMessage(
            content=str({"code": "TRANSPORT", "message": str(exc),
                        "remedy_hint": "retry or use a different vendor",
                        "alternatives": []}),
            tool_call_id=tool_call_id,
        )]})

    return Command(update={
        "staged": [{"type": _STAGED_TYPE[step.action], "step": step_dict,
                    "result": result}],
        "messages": [ToolMessage(content=str(result), tool_call_id=tool_call_id)],
    })


@tool
def submit_diagnosis(
    stockout_sku: str,
    days_until_failure: int,
    reasoning: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Record your diagnosis: which SKU fails first, in how many days, and
    why. Call this once, early -- before staging actions -- so the human
    approver sees your reasoning, not just a list of orders. `reasoning` is
    shown to them verbatim; write it for a person, not a log line.
    """
    diagnosis = {"stockout_sku": stockout_sku,
                 "days_until_failure": days_until_failure,
                 "reasoning": reasoning}
    return Command(update={
        "diagnosis": diagnosis,
        "messages": [ToolMessage(content="diagnosis recorded",
                                 tool_call_id=tool_call_id)],
    })
