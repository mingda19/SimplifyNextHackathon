"""Tool: read the current ranked list of unmet beneficiary needs.

Wraps the existing `services.get_unmet_needs()` HTTP client -- no new backend
work for the read itself. Named "feedback_extraction" because it is the
agent's window onto already-extracted, already-aggregated feedback
(`GET /feedback/unmet-needs` in the feedback service), not a live LLM
extraction of raw text run on demand -- that would spend money the
orchestrator's own token ledger cannot see or budget against. Zero LLM cost
here either way.

`POST /feedback` now queues extraction in the background by default (fast
response for the beneficiary, no waiting on Bedrock at submission time), so a
message posted moments ago may still be `pending`/`failed` by the time the
agent looks. This tool sweeps those up first, via
`services.extract_pending_feedback()`, so the read stays fresh without
pushing that latency onto the beneficiary's own request.
"""
from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from .. import services
from ._util import merge_state_of_world

log = logging.getLogger(__name__)

# Kept small: this runs inline in the agent's turn, and each row can take a
# few seconds of real Bedrock latency inside the feedback service. A bounded
# sweep keeps one tool call from stalling the whole turn; anything left over
# is picked up again next time the tool is called.
_SWEEP_LIMIT = 10


@tool
def feedback_extraction(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the current ranked list of unmet beneficiary needs.

    Each entry has `need`, `frequency`, `urgency`, `score`, `mentioned_skus`,
    and `gap` (true = no stocked SKU currently covers this need -- a strong
    signal for `flag_for_human` rather than guessing a SKU). Call this once,
    early, before deciding what to act on; the result does not change within
    a single run so there is no reason to call it more than once.
    """
    swept = services.extract_pending_feedback(limit=_SWEEP_LIMIT)
    if swept.get("attempted"):
        log.info("feedback_extraction: swept %d pending row(s), %d done, %d failed",
                 swept["attempted"], swept.get("done", 0), swept.get("failed", 0))

    try:
        unmet_needs = services.get_unmet_needs()
    except services.ServiceError as exc:
        log.info("feedback_extraction: unavailable: %s", exc)
        degraded = list(dict.fromkeys([*state.get("degraded_services", []),
                                       "unmet_needs"]))
        return Command(update={
            "degraded_services": degraded,
            "messages": [ToolMessage(
                content=f"Unmet-needs feed unavailable: {exc}",
                tool_call_id=tool_call_id,
            )],
        })

    sow = merge_state_of_world(state, {"unmet_needs": unmet_needs})
    ranked = unmet_needs.get("ranked", [])
    summary = {
        "totals": unmet_needs.get("totals"),
        "top_needs": [
            {k: n.get(k) for k in
             ("need", "frequency", "urgency", "score", "mentioned_skus", "gap")}
            for n in ranked[:12]
        ],
    }
    return Command(update={
        "state_of_world": sow,
        "messages": [ToolMessage(content=str(summary), tool_call_id=tool_call_id)],
    })
