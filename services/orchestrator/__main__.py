"""
CLI runner.

    python -m orchestrator                     # interactive approval prompt
    python -m orchestrator --approve           # auto-approve (CI / smoke test)
    python -m orchestrator --reject
    python -m orchestrator --type A            # donation-fed charity
    python -m orchestrator --ledger            # show spend and exit
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid

from langgraph.types import Command

from . import ledger
from .config import settings
from .graph import compile_graph
from .state import new_state


def _banner() -> None:
    mode = []
    mode.append("FAKE_LLM" if settings.fake_llm else "REAL BEDROCK")
    mode.append("FAKE_SERVICES" if settings.fake_services else "REAL SERVICES")
    print(f"\n\033[1mPantry orchestrator\033[0m  [{' · '.join(mode)}]")
    if not settings.fake_llm:
        print(f"  \033[33m! spending real money on {settings.model_predict} "
              f"in {settings.aws_region}\033[0m")
    print(f"  ledger: {ledger.summary()}\n")


def _show(summary: dict) -> None:
    s, p, q, a = (summary["sensed"], summary["predicted"],
                  summary["queued"], summary["adaptations"])
    print("\033[1m── SENSED ─────────────────────────────────────────\033[0m")
    print(f"  below reorder : {', '.join(s['below_reorder']) or '—'}")
    print(f"  expiring soon : {len(s['expiring_soon'])} lot(s)")
    for n in s["top_unmet_needs"]:
        gap = "  \033[31m[NO MATCHING SKU]\033[0m" if n.get("gap") else ""
        print(f"  need          : {n['need']} (x{n['frequency']}, "
              f"urgency {n['urgency']}){gap}")
    ps = s["price_signal"]
    print(f"  price         : {ps.get('series')} {ps.get('direction')} "
          f"{ps.get('pct_change_3m')}% -> {ps.get('recommendation')} "
          f"(data lag {ps.get('data_lag_months')}mo)")
    if s["unavailable_services"]:
        print(f"  \033[33mdegraded      : {', '.join(s['unavailable_services'])}\033[0m")

    print("\033[1m── PREDICTED ──────────────────────────────────────\033[0m")
    print(f"  {p['stockout_sku']} fails in {p['days_until_failure']} days")
    print(f"  {p['reasoning']}")

    print("\033[1m── QUEUED ─────────────────────────────────────────\033[0m")
    for st in q["steps"]:
        v = f" via {st['vendor_id']}" if st.get("vendor_id") else ""
        print(f"  {st['action']:16} {st['sku']:14} qty {st['qty']}{v}")
    print(f"  total: S${q['total_sgd']:.2f}")

    print("\033[1m── ADAPTATIONS ────────────────────────────────────\033[0m")
    if not a:
        print("  (none — plan executed first try)")
    for ad in a:
        print(f"  \033[36mattempt {ad['attempt']} after {ad['error_code']}:\033[0m "
              f"{ad['what_changed']}")
    g = summary["guardrails"]
    if g.get("halt_reason"):
        print(f"  \033[31mhalted: {g['halt_reason']}\033[0m")
    if g.get("exceeds_single_order_cap"):
        print(f"  \033[33mexceeds single-order cap of "
              f"S${g['baselines']['max_single_order_sgd']}\033[0m")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(prog="orchestrator")
    ap.add_argument("--approve", action="store_true", help="auto-approve")
    ap.add_argument("--reject", action="store_true", help="auto-reject")
    ap.add_argument("--type", choices=["A", "B"], default="B",
                    help="A=donation-fed, B=budget-funded")
    ap.add_argument("--thread", default=None, help="resume an existing thread")
    ap.add_argument("--ledger", action="store_true", help="print spend and exit")
    ap.add_argument("--reset-ledger", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="  \033[90m%(levelname)-7s %(name)s: %(message)s\033[0m")

    if args.reset_ledger:
        ledger.reset()
        print("ledger reset")
        return 0
    if args.ledger:
        print(ledger.summary())
        return 0

    _banner()

    thread_id = args.thread or f"run-{uuid.uuid4().hex[:8]}"
    cfg = {"configurable": {"thread_id": thread_id}}
    graph = compile_graph()

    result = graph.invoke(new_state(thread_id, args.type), cfg)

    # ---- the interrupt round-trip ---------------------------------------
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        _show(payload)

        if args.approve:
            decision = "approved"
        elif args.reject:
            decision = "rejected"
        elif sys.stdin.isatty():
            decision = ("approved" if input("  Approve? [y/N] ").strip().lower()
                        in {"y", "yes"} else "rejected")
        else:
            decision = "rejected"
        print(f"  -> \033[1m{decision}\033[0m\n")

        result = graph.invoke(Command(resume={"decision": decision}), cfg)

    outcome = result.get("outcome")
    if outcome:
        print("\033[1m── OUTCOME ────────────────────────────────────────\033[0m")
        print(json.dumps(outcome, indent=2)[:1400])
    elif result.get("halt_reason"):
        print(f"\033[31mhalted: {result['halt_reason']}\033[0m")
    else:
        print("  (rejected — nothing committed)")

    print(f"\n  thread: {thread_id}")
    print(f"  ledger: {ledger.summary()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
