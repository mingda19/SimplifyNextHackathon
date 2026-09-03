"""Graph assembly and routing.

    sense -> predict -> act -> [approval] -> commit -> END
                         ^      |
                         └ adapt ┘        max 3 retries per step, then escalate
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .config import settings
from .nodes import act, adapt, approval, commit, predict, sense
from .state import AgentState

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ routing --
def route_after_predict(state: AgentState) -> str:
    if state.get("halt_reason"):
        return END
    plan = state.get("plan")
    if not plan or not plan.get("steps"):
        log.info("route: no actionable steps — ending")
        return END
    return "act"


def route_after_act(state: AgentState) -> str:
    if state.get("halt_reason"):
        return "approval"
    if state.get("last_error"):
        return "adapt"
    plan = state.get("plan") or {}
    if state.get("current_step", 0) < len(plan.get("steps", [])):
        return "act"          # more steps to work through
    return "approval"


def route_after_adapt(state: AgentState) -> str:
    # halt_reason here means the retry cap was hit or the budget ran out.
    # Either way a human needs to see it — escalate, never loop.
    if state.get("halt_reason"):
        return "approval"
    return "act"


def route_after_approval(state: AgentState) -> str:
    return "commit" if state.get("approval") == "approved" else END


# ------------------------------------------------------------------- build --
def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("sense", sense)
    g.add_node("predict", predict)
    g.add_node("act", act)
    g.add_node("adapt", adapt)
    g.add_node("approval", approval)
    g.add_node("commit", commit)

    g.add_edge(START, "sense")
    g.add_edge("sense", "predict")
    g.add_conditional_edges("predict", route_after_predict, {"act": "act", END: END})
    g.add_conditional_edges("act", route_after_act,
                            {"act": "act", "adapt": "adapt", "approval": "approval"})
    g.add_conditional_edges("adapt", route_after_adapt,
                            {"act": "act", "approval": "approval"})
    g.add_conditional_edges("approval", route_after_approval,
                            {"commit": "commit", END: END})
    g.add_edge("commit", END)
    return g


def make_checkpointer(path: str | None = None) -> SqliteSaver:
    """
    SqliteSaver, never MemorySaver — a pending approval must survive a restart.

    Built from a raw connection rather than `from_conn_string`, which is a
    context manager and would close the saver on exit.
    """
    target = path or str(settings.checkpoint_path)
    conn = sqlite3.connect(target, check_same_thread=False)
    return SqliteSaver(conn)


def compile_graph(checkpointer: Any | None = None):
    return build_graph().compile(checkpointer=checkpointer or make_checkpointer())
