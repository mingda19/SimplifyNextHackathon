"""
The only module that talks to Bedrock.

Two functions, one per reasoning node. Both short-circuit to fixtures when
FAKE_LLM=1, which is how ~80% of development runs cost nothing (plan.md §7.1).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from . import fixtures, ledger
from .config import BASELINES, settings
from .state import Adaptation, Plan

log = logging.getLogger(__name__)

# Stable prefix. Anything volatile (timestamps, per-run ids) must go in the
# user turn instead, or it silently invalidates the cache.
PREDICT_SYSTEM = """You are the planning node of an autonomous supply-chain agent \
operating for a charity that distributes food to beneficiaries.

You receive a State of the World describing current stock, alerts, aggregated \
beneficiary feedback, and a commodity price forecast. Compare it against the \
operating baselines, identify what will fail and when, and emit a plan that \
prevents it.

Rules:
- Only use the four permitted actions. Never invent an action.
- A need that maps to no existing SKU must become a `flag_for_human` step.
- Prefer the vendor whose lead time beats the projected stockout date.
- If the price forecast says BUY_NOW, do not defer an order to a later cycle.
- If an input service was unavailable, reason without it and say so in `reasoning`.
- `reasoning` is shown to a human approver. Write it for them, not for a log."""

ADAPT_SYSTEM = """You are the adaptation node of an autonomous supply-chain agent.

A planned step failed against the backend. You receive the step, the error, and \
the alternatives the backend offered. Produce a revised step that resolves the \
failure.

Rules:
- Prefer an option from `alternatives` over one you invent.
- Change the minimum necessary to clear the error.
- If the alternatives make a different vendor cheaper or faster, switching is correct.
- `what_changed` is shown verbatim to a human approver. One sentence, plain English."""


@lru_cache(maxsize=1)
def _client():
    """Bedrock client, built once. Mantle — not the legacy InvokeModel path."""
    from anthropic import AnthropicBedrockMantle

    # No static keys. boto3 resolves the SSO profile and refreshes the session
    # token itself, so a 12-hour expiry is transparent for as long as the SSO
    # login is alive. `make aws-login` renews it.
    return AnthropicBedrockMantle(
        aws_profile=settings.aws_profile,
        aws_region=settings.bedrock_region,
    )


def _call(model: str, max_tokens: int, system: str, user: str, schema: type):
    """One structured Bedrock request, budget-checked and ledgered."""
    ledger.check_budget()          # refuses rather than overspending
    resp = _client().messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    led = ledger.record(model, resp.usage)
    log.info("bedrock %s -> %s", model, ledger.summary())
    return resp.parsed_output, led


def predict_plan(state_of_world: dict[str, Any],
                 degraded: list[str],
                 charity_type: str) -> tuple[Plan, dict[str, Any] | None]:
    """PHASE 2. Returns (plan, ledger_snapshot | None)."""
    if settings.fake_llm:
        log.info("FAKE_LLM=1 — returning canned plan (no Bedrock call)")
        return Plan.model_validate(fixtures.FAKE_PLAN), None

    payload = {
        "charity_type": charity_type,
        "baselines": BASELINES,
        "state_of_world": state_of_world,
        "unavailable_services": degraded,
    }
    # sort_keys is not cosmetic — unsorted JSON is a silent cache invalidator.
    user = json.dumps(payload, sort_keys=True, indent=2, default=str)
    return _call(settings.model_predict, settings.max_tokens_predict,
                 PREDICT_SYSTEM, user, Plan)


def adapt_step(step: dict[str, Any],
               error: dict[str, Any],
               attempt_no: int) -> tuple[Adaptation, dict[str, Any] | None]:
    """PHASE 3 adaptation. Returns (adaptation, ledger_snapshot | None)."""
    if settings.fake_llm:
        log.info("FAKE_LLM=1 — returning canned adaptation (no Bedrock call)")
        return Adaptation.model_validate(fixtures.fake_adaptation(step, error)), None

    payload = {"failed_step": step, "error": error, "attempt_number": attempt_no}
    user = json.dumps(payload, sort_keys=True, indent=2, default=str)
    return _call(settings.model_adapt, settings.max_tokens_adapt,
                 ADAPT_SYSTEM, user, Adaptation)
