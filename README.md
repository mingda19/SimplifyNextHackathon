# Problem statement
hange is everywhere - in how we live, learn and relate to one another. Transformation takes time, effort, and the right support at the right moment.

This is your chance to build something that helps. We envision a solution that plans, acts, and adapts over time.

Your team will choose a problem and decide who it serves. You will design a solution that thinks ahead, takes action, and leaves people genuienly better off.


# Workflow
THE UNIVERSAL 4-STEP AGENTIC FLOW
PHASE 1: SENSE (THE INGESTION NODE) Goal: Continuously read external state and
detect changes before they become crises. Trigger: The agent is woken up either
by a scheduled timer (e.g., every hour), an incoming webhook (e.g., an alert
from a system), or a user prompt. Tool Call 1 (Primary Data): The agent reads
the "live" system status via API (e.g., current inventory, current wait times,
current bank balance). Tool Call 2 (Context Data): The agent reads external
variables that affect the system (e.g., weather API, traffic API, market price
API, news API). Output: The agent compiles a unified "State of the World" JSON
payload.
PHASE 2: PREDICT (THE REASONING NODE) Goal: Use LLM reasoning to identify
upcoming friction and formulate a mitigation plan. Analysis: The AI (Claude 4.5)
compares the "State of the World" against predefined baseline rules (e.g., "SLA
is 24 hours," "Budget limit is $500," "Minimum stock is 10"). Forecasting: The
AI projects the timeline. ("Based on X changing, Y will fail in Z hours.")
Planning: The AI generates a multi-step strategy to prevent the failure. It
selects which internal Tools it needs to use to fix the problem. Output: A
structured plan (Action A, Action B, Action C) stored in the LangGraph memory
state.
PHASE 3: ACT & ADAPT (THE EXECUTION LOOP) Goal: Execute the plan, hit a
roadblock, and dynamically adapt without crashing. Tool Call 3 (Attempt Action):
The agent attempts step 1 of its plan (e.g., booking a resource, querying a
backup system, shifting data). The Check (Validation): Did the API return a 200
OK success, or a 400 Error? The Adaptation (The Agentic Loop): a) If Success,
move to the next step of the plan. b) If Error (e.g., "Resource unavailable,"
"Permission denied"), the agent does not quit. It reads the error message, feeds
it back into its reasoning engine, and selects an alternative tool or parameter
(e.g., choosing a different date, a different vendor, or a secondary system).
Output: A staged "Draft Resolution" that has been technically validated by the
backend systems, waiting in a holding pattern.
PHASE 4: HUMAN APPROVAL (THE GUARDRAIL NODE) Goal: Ensure safety, budget
control, and high-fidelity decision-making. The Breakpoint: The LangGraph
workflow hits an interrupt. Execution is paused. The UI Handoff: The agent
surfaces a clean, natural-language summary to a frontend dashboard. It explains:
1.  What it sensed.
2.  What it predicted would go wrong.
3.  The exact actions it has queued up to fix it (and any adaptations it had to
    make). Human Input: The human clicks [Approve] or [Reject/Modify]. Final
    Execution: Upon approval, the agent resumes the graph, commits the final API
    calls (e.g., sending the actual email, moving the actual money), and closes
    the ticket.