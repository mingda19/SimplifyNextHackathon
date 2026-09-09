"""
PHASE 2 — the reasoning node.  One Bedrock call per turn.

Invoked repeatedly by the graph loop (`agent -> tools -> agent -> ...`) until
the model stops calling tools (`tools_condition` then routes to `finalize`),
or one of two hard stops fires first: `settings.max_agent_turns` (an
uncapped loop calling Bedrock forever is the one bug in this design that can
actually drain the budget while nobody is watching -- same concern the old
`adapt.py`'s retry cap existed for, just generalized from "retries" to "any
turn"), or `ledger.check_budget()` inside `llm.agent_step()` (checked before
every single call, not once at loop start).

Both hard stops return an `AIMessage` with no tool calls, so `tools_condition`
routes to `finalize` exactly the way it would if the model had simply decided
it was done -- the run still reaches a human, it just carries a `halt_reason`
explaining why it stopped early.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from .. import llm
from ..config import settings
from ..ledger import BudgetExceeded
from ..state import AgentState
from ..tools import TOOLS

log = logging.getLogger(__name__)


def agent(state: AgentState) -> dict[str, Any]:
    turn = state.get("agent_turns", 0) + 1

    if turn > settings.max_agent_turns:
        log.warning("agent: turn cap (%d) reached — forcing halt",
                   settings.max_agent_turns)
        return {
            "halt_reason": (f"turn limit ({settings.max_agent_turns}) reached "
                            "before the agent finished"),
            "messages": [AIMessage(content="Turn limit reached — "
                                   "handing off for human review.")],
            "attempts": [{"node": "agent", "ok": False, "turn": turn,
                          "error": "max_agent_turns exceeded"}],
        }

    try:
        ai_msg, led = llm.agent_step(state["messages"], TOOLS)
    except BudgetExceeded as exc:
        log.error("agent: %s", exc)
        return {
            "halt_reason": str(exc),
            "messages": [AIMessage(content="Budget cap reached — "
                                   "handing off for human review.")],
            "attempts": [{"node": "agent", "ok": False, "turn": turn,
                          "error": str(exc)}],
        }
    except Exception as exc:                      # noqa: BLE001
        log.exception("agent: model call failed")
        return {
            "halt_reason": f"agent failed: {exc}",
            "messages": [AIMessage(content=f"Internal error: {exc}. "
                                   "Handing off for human review.")],
            "attempts": [{"node": "agent", "ok": False, "turn": turn,
                          "error": str(exc)}],
        }

    return {
        "messages": [ai_msg],
        "agent_turns": turn,
        "token_ledger": led or state.get("token_ledger", {}),
        "attempts": [{"node": "agent", "ok": True, "turn": turn,
                      "tool_calls": [tc["name"] for tc in (ai_msg.tool_calls or [])]}],
    }
