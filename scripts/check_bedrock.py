#!/usr/bin/env python
"""
Verify the AWS session and the exact Bedrock path the orchestrator uses.

WHICH PATH
----------
`AnthropicBedrock` (legacy) -> POST bedrock-runtime.<region>.amazonaws.com
                               /model/<id>/invoke

NOT `AnthropicBedrockMantle`. Mantle is blocked on this account by an EXPLICIT
DENY in the org Service Control Policy on `bedrock-mantle:CreateInference`
(policy p-1sclicmp). An SCP explicit deny cannot be overridden by IAM and is not
region-specific — verified 6 Sep 2026.

MODEL ID
--------
Claude Haiku 4.5 is INFERENCE_PROFILE-only in us-east-1, so InvokeModel needs the
profile id (`us.` prefix), not the bare model id.

    make check-bedrock          # free: identity + model-id discovery
    make check-bedrock-live     # ONE 1-token real call (~$0.00002)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("AWS_CONFIG_FILE", str(ROOT / "aws" / "config"))
sys.path.insert(0, str(ROOT / "services"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import boto3  # noqa: E402
from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

PROFILE = os.getenv("AWS_PROFILE", "hackathon")
REGION = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION", "us-east-1")
MODEL = os.getenv("MODEL_PREDICT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

G, R, Y, X = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="make ONE real 1-token call to confirm end to end")
    args = ap.parse_args()

    try:
        session = boto3.Session(profile_name=PROFILE)
        ident = session.client("sts", region_name=REGION).get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        print(f"\n  {R}No valid AWS session{X} ({type(exc).__name__})")
        print("  Run:  make aws-login\n")
        return 1

    print(f"\n  account {ident['Account']}   region {REGION}")
    print(f"  configured model: {MODEL}\n")

    # Which Haiku inference profiles exist here? (free control-plane call)
    try:
        b = session.client("bedrock", region_name=REGION)
        ids, tok = [], None
        while True:
            kw = {"maxResults": 100}
            if tok:
                kw["nextToken"] = tok
            r = b.list_inference_profiles(**kw)
            ids += [p["inferenceProfileId"] for p in r["inferenceProfileSummaries"]]
            tok = r.get("nextToken")
            if not tok:
                break
        haiku = sorted(i for i in ids if "haiku-4-5" in i)
        print("  Claude Haiku 4.5 inference profiles available:")
        for i in haiku:
            mark = f" {G}<- configured{X}" if i == MODEL else ""
            print(f"    {i}{mark}")
        if MODEL not in ids:
            print(f"\n  {Y}WARNING: {MODEL} is not in this region's profile list.{X}")
    except ClientError as exc:
        print(f"  {Y}could not list inference profiles: "
              f"{exc.response['Error']['Code']}{X}")

    if not args.live:
        print(f"\n  {Y}Discovery only — this does not prove InvokeModel is permitted.{X}")
        print("  To confirm end to end:  make check-bedrock-live   (~$0.00002)\n")
        return 0

    from anthropic import AnthropicBedrock
    print(f"\n  calling {MODEL} with max_tokens=1 ...")
    try:
        client = AnthropicBedrock(aws_profile=PROFILE, aws_region=REGION)
        resp = client.messages.create(model=MODEL, max_tokens=1,
                                      messages=[{"role": "user", "content": "hi"}])
        u = resp.usage
        print(f"  {G}OK{X} — in {u.input_tokens} / out {u.output_tokens} tokens")
        print(f"  {MODEL} works in {REGION}.\n")
        return 0
    except Exception as exc:                       # noqa: BLE001
        msg = str(exc)
        print(f"  {R}FAILED{X} {type(exc).__name__}: {msg[:220]}\n")
        if "service control policy" in msg or "explicit deny" in msg:
            print("  An SCP explicit deny cannot be worked around from inside the")
            print("  sandbox. If this names bedrock-mantle, confirm llm.py uses")
            print("  AnthropicBedrock (legacy), not AnthropicBedrockMantle.")
        else:
            print("  If this is a model-id error, try the other profile ids listed above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
