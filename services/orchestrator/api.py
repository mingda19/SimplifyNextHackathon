"""HTTP surface for the orchestrator — powers the Agent Actions tab.

The graph itself is unchanged: this wraps it so a browser can start a run, see
what the agent is waiting on, and approve or reject. The human-approval
interrupt is the whole point of the product, so it needs a real UI, not a CLI.

Run state lives in Postgres (`agent.runs`) rather than being re-derived from the
LangGraph checkpointer. The checkpointer remains the source of truth for
RESUMING a paused graph; this table is the read model the dashboard lists from.

Runs execute in a background thread: a full sense->predict->act pass takes tens
of seconds against live Bedrock and must not block the HTTP response.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Literal, Optional

import psycopg2
import psycopg2.extras
from fastapi import Body, Depends, FastAPI, HTTPException, Query
from pantry_common.security import require_charity
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from orchestrator.config import settings
from orchestrator.graph import compile_graph
from orchestrator.nodes.approval import build_summary
from orchestrator.state import APPROVAL_VERSION, new_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator.api")

app = FastAPI(title="Pantry Orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_DIALECT = re.compile(r"^postgresql\+\w+://")

# ONE compiled graph for the whole process.
#
# compile_graph() was previously called per request. Each call built a fresh
# SqliteSaver over a new sqlite3.connect() that was never closed — 14 leaked
# descriptors on one checkpoint file, with a background thread writing through
# WAL at the same time. That is what produced the intermittent
# "DatabaseError: file is not a database" on start_run and decide.
_GRAPH = None
_GRAPH_LOCK = threading.Lock()


def _graph():
    global _GRAPH
    if _GRAPH is None:
        with _GRAPH_LOCK:
            if _GRAPH is None:
                _GRAPH = compile_graph()
    return _GRAPH


@contextmanager
def _conn():
    dsn = _DIALECT.sub("postgresql://", os.getenv("DATABASE_URL", ""))
    conn = psycopg2.connect(dsn)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _sql(query: str, params: tuple = (), fetch: str | None = None):
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
    return None


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))


def _run_graph(thread_id: str, charity_type: str) -> None:
    """Execute until the approval interrupt, then park the summary."""
    graph = None
    try:
        graph = compile_graph()
        cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 256}
        result = graph.invoke(new_state(thread_id, charity_type), cfg)
        if "__interrupt__" in result:
            summary = _jsonable(result["__interrupt__"][0].value)
            _sql("""UPDATE agent.runs SET status='pending_approval', summary=%s
                    WHERE thread_id=%s""",
                 (psycopg2.extras.Json(summary), thread_id))
            logger.info("run %s paused for approval", thread_id)
        elif result.get("halt_reason"):
            _sql("UPDATE agent.runs SET status='failed', error=%s, summary=%s WHERE thread_id=%s",
                 (result["halt_reason"], psycopg2.extras.Json(_jsonable(build_summary(result))), thread_id))
        else:
            # No interrupt: the graph ended without anything to approve.
            _sql("""UPDATE agent.runs SET status='completed', summary=%s, outcome=%s,
                    decided_at=now(), decided_by='auto (nothing to approve)'
                    WHERE thread_id=%s""",
                 (psycopg2.extras.Json(_jsonable(build_summary(result))),
                  psycopg2.extras.Json(_jsonable(result.get("outcome"))), thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run %s failed", thread_id)
        _sql("UPDATE agent.runs SET status='failed', error=%s WHERE thread_id=%s",
             (f"{type(exc).__name__}: {exc}", thread_id))

    finally:
        if graph is not None:
            graph.checkpointer.conn.close()


@app.get("/health")
def health():
    try:
        n = _sql("SELECT count(*) AS n FROM agent.runs", fetch="one")["n"]
        return {"status": "ok", "runs": n, "fake_llm": settings.fake_llm,
                "model": settings.model_predict}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "detail": str(exc)}


class RunRequest(BaseModel):
    charity_type: Literal["A", "B"] = "B"


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]


@app.post("/agent/runs", status_code=202)
def start_run(payload: RunRequest = Body(default=RunRequest()), user: dict = Depends(require_charity)):
    charity_type = payload.charity_type
    if charity_type not in ("A", "B"):
        raise HTTPException(400, "charity_type must be 'A' or 'B'")
    thread_id = f"run-{uuid.uuid4().hex[:10]}"
    _sql("""INSERT INTO agent.runs (thread_id, charity_type, status)
            VALUES (%s,%s,'running')""", (thread_id, charity_type))
    threading.Thread(target=_run_graph, args=(thread_id, charity_type),
                     daemon=True).start()
    return {"thread_id": thread_id, "status": "running"}


@app.get("/agent/runs")
def list_runs(status: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
              user: dict = Depends(require_charity)):
    q = """SELECT thread_id, charity_type, status, summary, outcome, error,
                  created_at, decided_at, decided_by, decision
           FROM agent.runs {where} ORDER BY created_at DESC LIMIT %s"""
    if status:
        return _sql(q.format(where="WHERE status=%s"), (status, limit), fetch="all")
    return _sql(q.format(where=""), (limit,), fetch="all")


@app.get("/agent/runs/{thread_id}")
def get_run(thread_id: str, user: dict = Depends(require_charity)):
    row = _sql("""SELECT thread_id, charity_type, status, summary, outcome, error,
                         created_at, decided_at, decided_by, decision
                  FROM agent.runs WHERE thread_id=%s""", (thread_id,), fetch="one")
    if not row:
        raise HTTPException(404, "no such run")
    return row


@app.post("/agent/runs/{thread_id}/decision")
def decide(thread_id: str, payload: dict = Body(...)):
    """Approve or reject a queued plan. This is the guardrail node's other half."""
    
    # 1. Parse the Payload
    decision = str(payload.get("decision", "")).lower()
    approved_steps = payload.get("approved_steps")

    print("Decision payload:", payload)
    print("Approved steps:", approved_steps)

    if approved_steps is not None:
        # Per-line selection wins over the blanket decision.
        approved_steps = [int(i) for i in approved_steps]
        decision = "approved" if approved_steps else "rejected"
        
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected', or send approved_steps")
        
    who = payload.get("decided_by") or "unknown"

    # 2. Database Validation
    row = _sql("SELECT * FROM agent.runs WHERE thread_id=%s", (thread_id,), fetch="one")
    if not row:
        raise HTTPException(404, "no such run")
        
    retrying = row["status"] == "committing"
    if retrying:
        # Prevent a different admin from retrying someone else's decision
        if row.get("decision") != decision or row.get("decided_by") != who:
            raise HTTPException(409, "only the original approver can retry this decision")
    elif row["status"] != "pending_approval":
        raise HTTPException(409, f"run is '{row['status']}', not awaiting approval")

    # 3. Resume the LangGraph Agent
    graph = _graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    
    try:
        resume_data = {"decision": decision}
        if approved_steps is not None:
            resume_data["approved_steps"] = approved_steps
            
        # Send the decision into the paused graph using Command
        result = graph.invoke(Command(resume=resume_data), cfg)
        
    except Exception as exc:  # noqa: BLE001
        _sql("UPDATE agent.runs SET status='failed', error=%s WHERE thread_id=%s",
             (f"{type(exc).__name__}: {exc}", thread_id))
        raise HTTPException(500, f"resume failed: {exc}")

    # 4. Save Final Outcome to Database
    _sql("""UPDATE agent.runs 
            SET status=%s, outcome=%s, decided_at=now(), decided_by=%s 
            WHERE thread_id=%s""",
         (decision, psycopg2.extras.Json(_jsonable(result.get("outcome"))), who, thread_id))
         
    return {
        "thread_id": thread_id, 
        "status": decision,
        "approved_steps": approved_steps,
        "outcome": _jsonable(result.get("outcome"))
    }
