-- Orchestrator API's run-state read model. The LangGraph SqliteSaver
-- checkpointer remains the source of truth for RESUMING a paused graph;
-- this table is what the Agent Actions dashboard lists/polls from.
-- Reverse-engineered from services/orchestrator/api.py's queries -- no
-- schema file existed for this table before (found while standing up the
-- full stack for a demo rehearsal; api.py's own /health was reporting
-- "degraded: relation agent.runs does not exist").

CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS agent.runs (
    thread_id       TEXT PRIMARY KEY,
    charity_type    TEXT NOT NULL CHECK (charity_type IN ('A', 'B')),
    status          TEXT NOT NULL CHECK (status IN
                        ('running', 'pending_approval', 'approved', 'rejected', 'failed')),
    summary         JSONB,
    outcome         JSONB,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent.runs (status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent.runs (created_at);
