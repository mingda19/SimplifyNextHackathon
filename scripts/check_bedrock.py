#!/usr/bin/env python
"""
Verify the AWS session and the Bedrock path the orchestrator actually uses.

IMPORTANT: the orchestrator uses the **Mantle** client, which talks to
    https://bedrock-mantle.<region>.api.aws/anthropic
and keeps the Messages API shape (model in the body, Anthropic-style ID).

That is a DIFFERENT control plane from `bedrock-runtime`. So `ListFoundationModels`
is NOT evidence about what Mantle serves — its IDs (anthropic.claude-haiku-4-5-
20251001-v1:0, global.anthropic.*) belong to the legacy InvokeModel path only.
Mantle wants the clean id: anthropic.claude-haiku-4-5

    make check-bedrock          # free: identity + endpoint reachability
    make check-bedrock-live     # ONE tiny real call (~$0.00002) to settle it
"""
from __future__ import annotations

import argparse
import os
import socket
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
REGIONS = ["ap-southeast-1", "us-east-1", "us-west-2"]
CONFIGURED = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION", "ap-southeast-1")
MODEL = os.getenv("MODEL_PREDICT", "anthropic.claude-haiku-4-5")

G, R, Y, X = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="make ONE real 1-token call to confirm the model id")
    args = ap.parse_args()

    # 1 — identity
    try:
        session = boto3.Session(profile_name=PROFILE)
        ident = session.client("sts", region_name=CONFIGURED).get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        print(f"\n  {R}No valid AWS session{X} ({type(exc).__name__})")
        print("  Run:  make aws-login\n")
        return 1
    print(f"\n  account {ident['Account']}")
    print(f"  role    {ident['Arn'].split('/')[-2] if '/' in ident['Arn'] else ident['Arn']}\n")

    # 2 — Mantle endpoint reachability (the plane we actually use)
    print("  Mantle endpoints (the plane the orchestrator uses):")
    for region in REGIONS:
        host = f"bedrock-mantle.{region}.api.aws"
        mark = " <- BEDROCK_REGION" if region == CONFIGURED else ""
        try:
            socket.getaddrinfo(host, 443)
            print(f"    {G}{region:16}{X} {host} reachable{mark}")
        except socket.gaierror:
            print(f"    {R}{region:16}{X} {host} NO DNS{mark}")

    print(f"\n  configured model: {MODEL}")
    if not args.live:
        print(f"  {Y}Endpoint reachability does not prove the model id or IAM "
              f"permission.{X}")
        print("  To settle both:  make check-bedrock-live   (~$0.00002)\n")
        return 0

    # 3 — one real, minimal call
    from anthropic import AnthropicBedrockMantle
    print(f"\n  calling {MODEL} in {CONFIGURED} with max_tokens=64 ...")
    try:
        client = AnthropicBedrockMantle(aws_profile=PROFILE, aws_region=CONFIGURED)
        resp = client.messages.create(
            model=MODEL, max_tokens=64,
            messages=[{"role": "user", "content": "what is aws bedrock?"}],
        )
        u = resp.usage
        print(f"  {G}OK{X} — in {u.input_tokens} / out {u.output_tokens} tokens\n")
        print(f"  {MODEL} works in {CONFIGURED}. Config is correct.\n")
        return 0
    except Exception as exc:                       # noqa: BLE001
        print(f"  {R}FAILED{X} {type(exc).__name__}: {exc}\n")
        print("  If this is a model-id error, try in order:")
        print("    anthropic.claude-haiku-4-5")
        print("    anthropic.claude-haiku-4-5-20251001-v1:0")
        print("    global.anthropic.claude-haiku-4-5-20251001-v1:0")
        print("  If it is AccessDenied, the sandbox permission set may not allow")
        print("  bedrock-mantle — fall back to AnthropicBedrock (legacy InvokeModel)")
        print("  with an inference-profile id.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
