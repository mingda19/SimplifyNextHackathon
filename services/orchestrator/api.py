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
from datetime import datetime
from typing import Any, Optional

import psycopg2
import psycopg2.extras
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command

from orchestrator.config import settings
from orchestrator.graph import compile_graph
from orchestrator.nodes.approval import build_summary
from orchestrator.state import new_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator.api")

app = FastAPI(title="Pantry Orchestrator")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

_DIALECT = re.compile(r"^postgresql\+\w+://")


def _conn():
    dsn = _DIALECT.sub("postgresql://", os.getenv("DATABASE_URL", ""))
    return psycopg2.connect(dsn)


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
    try:
        graph = compile_graph()
        cfg = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(new_state(thread_id, charity_type), cfg)
        if "__interrupt__" in result:
            summary = _jsonable(result["__interrupt__"][0].value)
            _sql("""UPDATE agent.runs SET status='pending_approval', summary=%s
                    WHERE thread_id=%s""",
                 (psycopg2.extras.Json(summary), thread_id))
            logger.info("run %s paused for approval", thread_id)
        else:
            # No interrupt: the graph ended without anything to approve.
            _sql("""UPDATE agent.runs SET status='approved', summary=%s, outcome=%s,
                    decided_at=now(), decided_by='auto (nothing to approve)'
                    WHERE thread_id=%s""",
                 (psycopg2.extras.Json(_jsonable(build_summary(result))),
                  psycopg2.extras.Json(_jsonable(result.get("outcome"))), thread_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("run %s failed", thread_id)
        _sql("UPDATE agent.runs SET status='failed', error=%s WHERE thread_id=%s",
             (f"{type(exc).__name__}: {exc}", thread_id))


@app.get("/health")
def health():
    try:
        n = _sql("SELECT count(*) AS n FROM agent.runs", fetch="one")["n"]
        return {"status": "ok", "runs": n, "fake_llm": settings.fake_llm,
                "model": settings.model_predict}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "detail": str(exc)}


@app.post("/agent/runs", status_code=202)
def start_run(payload: dict = Body(default={})):
    charity_type = (payload or {}).get("charity_type", "B")
    if charity_type not in ("A", "B"):
        raise HTTPException(400, "charity_type must be 'A' or 'B'")
    thread_id = f"run-{uuid.uuid4().hex[:10]}"
    _sql("""INSERT INTO agent.runs (thread_id, charity_type, status)
            VALUES (%s,%s,'running')""", (thread_id, charity_type))
    threading.Thread(target=_run_graph, args=(thread_id, charity_type),
                     daemon=True).start()
    return {"thread_id": thread_id, "status": "running"}


@app.get("/agent/runs")
def list_runs(status: Optional[str] = None, limit: int = 50):
    q = """SELECT thread_id, charity_type, status, summary, outcome, error,
                  created_at, decided_at, decided_by
           FROM agent.runs {where} ORDER BY created_at DESC LIMIT %s"""
    if status:
        return _sql(q.format(where="WHERE status=%s"), (status, limit), fetch="all")
    return _sql(q.format(where=""), (limit,), fetch="all")


@app.get("/agent/runs/{thread_id}")
def get_run(thread_id: str):
    row = _sql("""SELECT thread_id, charity_type, status, summary, outcome, error,
                         created_at, decided_at, decided_by
                  FROM agent.runs WHERE thread_id=%s""", (thread_id,), fetch="one")
    if not row:
        raise HTTPException(404, "no such run")
    return row


@app.post("/agent/runs/{thread_id}/decision")
def decide(thread_id: str, payload: dict = Body(...)):
    """Approve or reject a queued plan. This is the guardrail node's other half."""
    decision = str(payload.get("decision", "")).lower()
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")
    who = payload.get("decided_by") or "unknown"

    row = _sql("SELECT status FROM agent.runs WHERE thread_id=%s",
               (thread_id,), fetch="one")
    if not row:
        raise HTTPException(404, "no such run")
    if row["status"] != "pending_approval":
        raise HTTPException(409, f"run is '{row['status']}', not awaiting approval")

    graph = compile_graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    try:
        result = graph.invoke(Command(resume={"decision": decision}), cfg)
    except Exception as exc:  # noqa: BLE001
        _sql("UPDATE agent.runs SET status='failed', error=%s WHERE thread_id=%s",
             (f"{type(exc).__name__}: {exc}", thread_id))
        raise HTTPException(500, f"resume failed: {exc}")

    _sql("""UPDATE agent.runs SET status=%s, outcome=%s, decided_at=now(),
            decided_by=%s WHERE thread_id=%s""",
         (decision, psycopg2.extras.Json(_jsonable(result.get("outcome"))),
          who, thread_id))
    return {"thread_id": thread_id, "status": decision,
            "outcome": _jsonable(result.get("outcome"))}
