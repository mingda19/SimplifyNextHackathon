-- Create the schema for the agent
CREATE SCHEMA IF NOT EXISTS agent;

-- Create the runs table based on the Python API requirements
CREATE TABLE IF NOT EXISTS agent.runs (
    thread_id VARCHAR(255) PRIMARY KEY,
    charity_type VARCHAR(255),
    status VARCHAR(50),
    summary JSONB,
    outcome JSONB,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP WITH TIME ZONE,
    decided_by VARCHAR(255)
);

-- Idempotent upgrade for existing installations, including inventory-only volumes.
ALTER TABLE agent.runs ALTER COLUMN summary TYPE JSONB USING summary::jsonb;
ALTER TABLE agent.runs ALTER COLUMN outcome TYPE JSONB USING outcome::jsonb;
ALTER TABLE agent.runs ADD COLUMN IF NOT EXISTS decision VARCHAR(20);
ALTER TABLE agent.runs ADD COLUMN IF NOT EXISTS decided_by_id TEXT;

-- A pre-existing volume can carry a status CHECK constraint from before the
-- API's 'committing' status existed (this table's status is not otherwise
-- constrained in code -- see services/orchestrator/api.py). Drop it rather
-- than widen it, so a future status value never needs another migration.
ALTER TABLE agent.runs DROP CONSTRAINT IF EXISTS runs_status_check;
