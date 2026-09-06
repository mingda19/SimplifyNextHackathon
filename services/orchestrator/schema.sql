-- Create the schema for the agent
CREATE SCHEMA IF NOT EXISTS agent;

-- Create the runs table based on the Python API requirements
CREATE TABLE IF NOT EXISTS agent.runs (
    thread_id VARCHAR(255) PRIMARY KEY,
    charity_type VARCHAR(255),
    status VARCHAR(50),
    summary TEXT,
    outcome TEXT,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP WITH TIME ZONE,
    decided_by VARCHAR(255)
);