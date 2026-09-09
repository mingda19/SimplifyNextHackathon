"""Graph assembly and routing.

    seed -> agent <-> tools (ToolNode)
             |
             `-- tools_condition: no tool call -> finalize -> END

All hand-written routing from the old fixed-step design is gone: `agent`'s
last message either carries tool calls (`tools_condition` returns "tools",
`ToolNode` executes them, loops back to `agent`) or it doesn't (routes to
`finalize`, which builds the approval summary, blocks on `interrupt()`, and
commits on resume).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .config import settings
from .nodes import agent, finalize, seed
from .state import AgentState
from .tools import TOOLS


# ------------------------------------------------------------------- build --
def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("seed", seed)
    g.add_node("agent", agent)
    g.add_node("tools", ToolNode(TOOLS))
    g.add_node("finalize", finalize)

    g.add_edge(START, "seed")
    g.add_edge("seed", "agent")
    g.add_conditional_edges("agent", tools_condition,
                            {"tools": "tools", END: "finalize"})
    g.add_edge("tools", "agent")
    g.add_edge("finalize", END)
    return g


def make_checkpointer(path: str | None = None) -> SqliteSaver:
    """
    SqliteSaver, never MemorySaver — a pending approval must survive a restart.

    Built from a raw connection rather than `from_conn_string`, which is a
    context manager and would close the saver on exit.
    """
    target = path or str(settings.checkpoint_path)
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    return SqliteSaver(conn)


def compile_graph(checkpointer: Any | None = None):
    return build_graph().compile(checkpointer=checkpointer or make_checkpointer())
