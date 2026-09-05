#!/usr/bin/env python
"""WS2 Phase 2 Part A: verify the real Bedrock path app/extract.py uses.

Makes ONE minimal call through the exact same client-construction pattern
as app/extract.py's _client() (which mirrors services/orchestrator/llm.py's
_client() -- see that module's docstring for why: same AnthropicBedrockMantle
pattern, same SSO/credential resolution, so both services share one AWS
setup). No DB, no FastAPI -- this isolates an auth/config problem from a
service problem.

Usage (from services/feedback/):
    .venv/Scripts/python.exe scripts/check_bedrock.py            # free: identity + reachability
    .venv/Scripts/python.exe scripts/check_bedrock.py --live      # ~$0.00002: one real token
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]        # services/feedback
REPO_ROOT = ROOT.parents[1]                        # repo root
os.environ.setdefault("AWS_CONFIG_FILE", str(REPO_ROOT / "aws" / "config"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

import boto3  # noqa: E402
from botocore.exceptions import BotoCoreError, ClientError  # noqa: E402

PROFILE = os.getenv("AWS_PROFILE", "hackathon")
REGIONS = ["ap-southeast-1", "us-east-1", "us-west-2"]
CONFIGURED = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION", "ap-southeast-1")
MODEL = os.getenv("MODEL_EXTRACT", "anthropic.claude-haiku-4-5")

G, R, Y, X = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="make ONE real 1-token call")
    args = ap.parse_args()

    using_static_keys = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    print(f"\n  credential mode: {'static sandbox-lease keys (AWS_ACCESS_KEY_ID set)' if using_static_keys else f'SSO profile ({PROFILE})'}")

    # 1 -- identity. boto3.Session with no explicit keys falls through to its
    # default chain (env vars checked before profile-based SSO), so this
    # works whether AWS_ACCESS_KEY_ID is set or not -- don't pass profile_name
    # explicitly here, unlike the app client, so a static-key session isn't
    # forced to also resolve (and fail on) the "hackathon" SSO profile.
    try:
        session = boto3.Session()
        ident = session.client("sts", region_name=CONFIGURED).get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        print(f"\n  {R}No valid AWS session{X} ({type(exc).__name__}): {exc}")
        if using_static_keys:
            print("  Static keys are set but invalid/expired -- get fresh ones from the")
            print("  Access Portal (Accounts -> expand sandbox -> Access keys) and update .env.\n")
        else:
            print("  Run:  make aws-login\n")
        return 1
    print(f"  account {ident['Account']}")
    print(f"  role    {ident['Arn'].split('/')[-2] if '/' in ident['Arn'] else ident['Arn']}\n")

    # 2 -- Mantle endpoint reachability
    print("  Mantle endpoints:")
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
        print(f"  {Y}Endpoint reachability does not prove the model id or IAM permission.{X}")
        print("  To settle both:  .venv/Scripts/python.exe scripts/check_bedrock.py --live\n")
        return 0

    # 3 -- one real, minimal call through the SAME client-construction path
    # app/extract.py's _client() uses.
    from anthropic import AnthropicBedrockMantle

    print(f"\n  calling {MODEL} in {CONFIGURED} with max_tokens=64 ...")
    try:
        # No aws_profile passed when static keys are present -- matches the
        # fix needed in app/extract.py/_client() (see Phase 2 findings):
        # passing aws_profile explicitly forces boto3.Session(profile_name=...),
        # which is unnecessary here since env-var credentials already resolve
        # correctly on their own, and this keeps this check independent of app
        # code, so it isolates an auth problem from a service problem as the
        # docstring promises.
        kwargs = {"aws_region": CONFIGURED}
        if not using_static_keys:
            kwargs["aws_profile"] = PROFILE
        client = AnthropicBedrockMantle(**kwargs)
        resp = client.messages.create(
            model=MODEL, max_tokens=64,
            messages=[{"role": "user", "content": "what is aws bedrock?"}],
        )
        u = resp.usage
        print(f"  {G}OK{X} -- in {u.input_tokens} / out {u.output_tokens} tokens\n")
        print(f"  {MODEL} works in {CONFIGURED}. Config is correct.\n")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  {R}FAILED{X} {type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
