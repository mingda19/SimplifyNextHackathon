"""
The only module that talks to Bedrock.

One function, `agent_step()`, called once per turn of the tool-calling loop
in `nodes/agent.py`. There is no FAKE_LLM short-circuit here -- every call is
real Bedrock, gated only by `ledger.check_budget()` (unconditional, before
every single call) and `settings.max_agent_turns` (enforced by the caller).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from . import ledger
from .config import settings

log = logging.getLogger(__name__)

# Stable prefix, cached via `cache_control` below. Anything volatile
# (timestamps, per-run ids, the actual state of the world) belongs in the
# first HumanMessage instead (built by `seed.py`), or it silently
# invalidates the cache on every run.
#
# Merges the old PREDICT_SYSTEM (single upfront Plan) and ADAPT_SYSTEM
# (single-purpose retry) into one prompt for the tool-calling loop. The
# ADAPT_SYSTEM rules are carried forward on purpose, not dropped: the
# MOQ_NOT_MET -> read alternatives -> raise qty -> reprice -> switch vendor
# beat is this project's scripted demo centerpiece, and a general-purpose
# autonomous loop needs the same explicit guidance a narrow single-call
# adapt() used to get, or it is not guaranteed to reproduce that reasoning
# zero-shot.
AGENT_SYSTEM = """You are the planning agent of an autonomous supply-chain \
agent operating for a charity that distributes food to beneficiaries.

You will be given a State of the World: current stock, alerts, and what is \
already on the way. You have four tools:

- `feedback_extraction` -- the current ranked list of unmet beneficiary needs.
  Call this once, early, if the State of the World doesn't already answer what
  beneficiaries are short of.
- `price_forecaster` -- a BUY_NOW / DEFER / NEUTRAL signal for one commodity
  (its `dspi_series`). Call it for SKUs you're actually considering acting on,
  not every SKU in inventory.
- `sku_matching` -- deterministic (never guessed) check for whether a term
  maps to a real, stocked SKU. Use it when an unmet need has no obvious SKU,
  or `mentioned_skus` is empty. A `fuzzy` result is a lead, not a fact.
- `action_generator` -- stage ONE action (`request_quote`, `place_order`,
  `reallocate_lot`, or `flag_for_human`) against a SKU. Never commits; a human
  approves everything you stage before anything real happens.

Work in this order: diagnose first, then act.

1. Identify what will fail and when. Call `submit_diagnosis` ONCE, early, with
   the SKU that fails first, the days until it does, and your reasoning --
   this is shown to the human approver, write it for them, not for a log.
2. Then call `action_generator` for each action you want to take.

Rules:
- Only the four actions `action_generator` accepts exist. Never invent one.
- CRITICAL: `request_quote`, `place_order` and `reallocate_lot` each MUST
  carry an integer `qty` of 1 or more. A qty of 0 is valid only on
  `flag_for_human`. If you are not confident of a quantity, or a need maps to
  no existing SKU, use `flag_for_human` instead of guessing.
- Prefer the vendor whose lead time beats the projected stockout date.
- If a price forecast says BUY_NOW, do not defer that order to a later cycle.
- The State of the World's `already_on_the_way` lists stock ALREADY ordered
  and not yet delivered. Do NOT propose another order for a SKU that has
  enough inbound to clear its shortfall -- say so in your diagnosis instead.
  Re-ordering what is already coming is the most expensive mistake you can
  make here.
- If `action_generator` returns an error (e.g. `MOQ_NOT_MET`), that error
  includes an `alternatives` array -- prefer an option from it over inventing
  one. Change the minimum necessary to clear the error. Only switch vendor if
  the alternatives make a different one genuinely cheaper or faster. Explain
  what changed and why in the `rationale` argument of your retry -- it is
  shown to the human approver alongside the original attempt.
- If an input was unavailable (a tool returned an error), reason without it
  and say so in your diagnosis.
- You have a limited number of turns. Stop calling tools once you have
  diagnosed the situation and staged everything you intend to -- that is what
  hands the run to a human for approval."""


@lru_cache(maxsize=1)
def _client():
    """Bedrock client, built once. Legacy InvokeModel — Mantle is SCP-denied."""
    from anthropic import AnthropicBedrock

    # NOT AnthropicBedrockMantle. The org SCP carries an EXPLICIT DENY on
    # bedrock-mantle:CreateInference (policy p-1sclicmp), which IAM cannot
    # override and which is not region-specific. The legacy client goes to
    # bedrock-runtime InvokeModel instead — an action the SCP permits.
    #
    # No static keys: boto3 resolves the SSO profile and refreshes the session
    # token itself, so the 12-hour expiry is transparent while the SSO login
    # is alive. `make aws-login` renews it.
    return AnthropicBedrock(
        aws_profile=settings.aws_profile,
        aws_region=settings.bedrock_region,
    )


def _to_tool_param(tool: Any) -> dict[str, Any]:
    """LangChain tool -> Anthropic `tools=[...]` entry.

    `tool.tool_call_schema` (not `tool.args_schema`) is the one that already
    excludes `InjectedState`/`InjectedToolCallId` params -- confirmed by
    direct inspection: `args_schema` for `price_forecaster` includes
    `state`/`tool_call_id`, `tool_call_schema` does not. The model must never
    see those; `ToolNode` fills them in at execution time.
    """
    schema = tool.tool_call_schema.model_json_schema()
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
    return {"name": tool.name, "description": tool.description, "input_schema": schema}


def _to_anthropic_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """LangChain message list -> Anthropic `messages=[...]`.

    Tool-call round-tripping is reconstructed purely from `AIMessage.tool_calls`
    (`{"name","args","id"}` maps 1:1 onto a `tool_use` block's
    `name`/`input`/`id`) -- nothing extra needs to be stashed on the message
    when it's first built in `_to_ai_message` below.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            blocks: list[dict[str, Any]] = []
            if m.content:
                text = m.content if isinstance(m.content, str) else str(m.content)
                blocks.append({"type": "text", "text": text})
            for tc in (m.tool_calls or []):
                blocks.append({"type": "tool_use", "id": tc["id"],
                               "name": tc["name"], "input": tc["args"]})
            out.append({"role": "assistant", "content": blocks})
        elif isinstance(m, ToolMessage):
            content = m.content if isinstance(m.content, str) else str(m.content)
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": m.tool_call_id,
                 "content": content},
            ]})
        # SystemMessage is intentionally skipped here -- the system prompt is
        # passed separately via `system=`, not as a message in the list.
    return out


def _to_ai_message(resp: Any) -> AIMessage:
    """Anthropic response -> `AIMessage` with `.tool_calls` populated.

    `ToolNode`/`tools_condition` read `.tool_calls`, not raw `content` -- this
    field is load-bearing, confirmed against the standalone mechanics test
    in Phase 0.
    """
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "args": block.input,
                               "id": block.id, "type": "tool_call"})
    return AIMessage(content="\n".join(text_parts), tool_calls=tool_calls)


def agent_step(messages: list[BaseMessage],
              tools: list[Any]) -> tuple[AIMessage, dict[str, Any] | None]:
    """One turn of the agent loop: budget-checked, ledgered, real Bedrock.

    Called once per turn from `nodes/agent.py`, which enforces
    `settings.max_agent_turns` around the loop this feeds -- `check_budget()`
    here only guards the per-call spend cap, not the turn count.
    """
    ledger.check_budget()          # refuses rather than overspending
    resp = _client().messages.create(
        model=settings.model_predict,
        max_tokens=settings.max_tokens_predict,
        system=[{"type": "text", "text": AGENT_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=_to_anthropic_messages(messages),
        tools=[_to_tool_param(t) for t in tools],
        tool_choice={"type": "auto"},
    )
    led = ledger.record(settings.model_predict, resp.usage)
    ai_msg = _to_ai_message(resp)
    log.info("bedrock %s -> %s (stop_reason=%s, %d tool call(s))",
             settings.model_predict, ledger.summary(), resp.stop_reason,
             len(ai_msg.tool_calls))
    return ai_msg, led
