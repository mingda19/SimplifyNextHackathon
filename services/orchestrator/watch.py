"""
Event-driven watch mode: poll every `settings.watch_poll_seconds` while
active, and start a new agent run when enough has changed since the agent
last looked -- instead of a run only ever starting from a manual button.

Two trigger conditions, either sufficient:
- `settings.watch_feedback_trigger` (default 10) or more NEW feedback rows
  have landed since the last checkpoint.
- `settings.watch_inventory_trigger` (default 3) or more ADDITIONAL SKUs
  have crossed into `below_reorder`/`expiring_soon` since the last
  checkpoint -- "inventory shifts by a lot". A delta, not an absolute count,
  so a persistently-high-but-unchanged alert count does not re-trigger every
  cycle.

Never triggers a second run while one is already `running` / `pending_approval`
/ `committing` -- that cycle is skipped entirely (busy, not idle) rather than
counted toward the auto-shutdown below.

Auto-deactivates after `settings.watch_quiet_cycles_limit` (default 2)
consecutive idle polls with neither trigger met -- an activated watch that
never sees anything worth acting on should not poll forever.

State is a single, process-wide, in-memory dict -- consistent with the
existing `_COMMITTED` idempotency set and `_GRAPH` singleton in `api.py`, and
with the same caveat: it does not survive an orchestrator restart. Given
activating it again is one click, that's an accepted tradeoff here, not an
oversight.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import services
from .config import settings

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None

_STATE: dict[str, Any] = {
    "active": False,
    "charity_type": "B",
    "activated_at": None,
    "last_poll_at": None,
    "last_trigger_at": None,
    "quiet_cycles": 0,
    "feedback_baseline": 0,
    "alert_baseline": 0,
    "last_run_thread_id": None,
    "last_check_error": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot() -> dict[str, Any]:
    return dict(_STATE)


def _alert_count() -> int:
    alerts = services.get_alerts()
    return len(alerts.get("below_reorder") or []) + len(alerts.get("expiring_soon") or [])


def _poll_loop(start_run: Callable[[str], str], has_run_in_flight: Callable[[], bool]) -> None:
    while True:
        time.sleep(settings.watch_poll_seconds)
        if not _STATE["active"]:
            return
        _STATE["last_poll_at"] = _now()

        try:
            if has_run_in_flight():
                # Already running / pending_approval / committing -- don't
                # pile on another run, and don't count this cycle toward
                # auto-shutdown either: the agent is busy, not idle-and-
                # seeing-nothing.
                continue

            feedback_count = services.count_feedback()
            alert_count = _alert_count()
            _STATE["last_check_error"] = None
        except Exception as exc:                      # noqa: BLE001
            log.warning("watch: poll check failed: %s", exc)
            _STATE["last_check_error"] = str(exc)
            continue

        new_feedback = feedback_count - _STATE["feedback_baseline"]
        new_alerts = alert_count - _STATE["alert_baseline"]
        triggered = (new_feedback >= settings.watch_feedback_trigger
                    or new_alerts >= settings.watch_inventory_trigger)

        if triggered:
            log.info("watch: triggering a run (new_feedback=%d new_alerts=%d)",
                     new_feedback, new_alerts)
            thread_id = start_run(_STATE["charity_type"])
            _STATE["last_run_thread_id"] = thread_id
            _STATE["last_trigger_at"] = _now()
            _STATE["feedback_baseline"] = feedback_count
            _STATE["alert_baseline"] = alert_count
            _STATE["quiet_cycles"] = 0
        else:
            _STATE["quiet_cycles"] += 1
            if _STATE["quiet_cycles"] >= settings.watch_quiet_cycles_limit:
                log.info("watch: %d quiet cycle(s) with nothing to act on — "
                         "auto-deactivating", _STATE["quiet_cycles"])
                _STATE["active"] = False
                return


def activate(charity_type: str, start_run: Callable[[str], str],
             has_run_in_flight: Callable[[], bool]) -> dict[str, Any]:
    """Turn watch mode on. No-op (returns current state) if already active."""
    global _THREAD
    with _LOCK:
        if _STATE["active"]:
            return dict(_STATE)

        try:
            feedback_baseline = services.count_feedback()
            alert_baseline = _alert_count()
        except Exception as exc:                      # noqa: BLE001
            log.warning("watch: could not baseline on activation: %s", exc)
            feedback_baseline = alert_baseline = 0

        _STATE.update({
            "active": True,
            "charity_type": charity_type,
            "activated_at": _now(),
            "last_poll_at": None,
            "last_trigger_at": None,
            "quiet_cycles": 0,
            "feedback_baseline": feedback_baseline,
            "alert_baseline": alert_baseline,
            "last_check_error": None,
        })
        _THREAD = threading.Thread(target=_poll_loop, args=(start_run, has_run_in_flight),
                                   daemon=True)
        _THREAD.start()
        return dict(_STATE)


def deactivate() -> dict[str, Any]:
    """Turn watch mode off. Safe to call whether or not it's active."""
    with _LOCK:
        _STATE["active"] = False
        return dict(_STATE)
