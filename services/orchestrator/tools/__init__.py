"""The four tools the agent can call, plus `submit_diagnosis` (a fifth,
zero-cost pseudo-tool needed so `finalize`'s dashboard summary has a
structured diagnosis to read -- see `action_generator.py`'s docstring).

`TOOLS` is consumed two ways: `langgraph.prebuilt.ToolNode(TOOLS)` executes
them, and `nodes/agent.py` converts them into Bedrock's `tools=[...]` schema
via `llm._to_tool_param()`.
"""
from __future__ import annotations

from .action_generator import action_generator, submit_diagnosis
from .feedback_extraction import feedback_extraction
from .price_forecaster import price_forecaster
from .sku_matching import sku_matching

TOOLS = [price_forecaster, feedback_extraction, sku_matching,
         action_generator, submit_diagnosis]

__all__ = ["TOOLS", "price_forecaster", "feedback_extraction", "sku_matching",
           "action_generator", "submit_diagnosis"]
