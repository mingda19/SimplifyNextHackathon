"""Shared helper for tools that merge a result into the `state_of_world`
scratchpad rather than owning a dedicated state field.

`state_of_world` is populated once, in `seed`, with inventory/alerts/inbound
(deterministic, $0). `price_forecaster` and `feedback_extraction` then merge
their own results into the SAME dict as the agent calls them mid-loop, via
`InjectedState` read + `Command(update={"state_of_world": {...}})` -- so
`finalize`'s dashboard summary keeps reading one dict shape regardless of
whether a given key was populated by `seed` or three turns later by a tool.
`Command.update` on a non-reducer field overwrites, it does not merge, so the
merge has to happen here, in Python, before the value goes back in the
Command.
"""
from __future__ import annotations

from typing import Any


def merge_state_of_world(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge `patch` into the current `state_of_world`, key by key."""
    current = dict(state.get("state_of_world") or {})
    current.update(patch)
    return current
