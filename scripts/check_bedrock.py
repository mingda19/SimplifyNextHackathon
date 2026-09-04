#!/usr/bin/env python
"""
Probe which region actually serves Claude on this account.

The hackathon deck says Bedrock must be us-east-1; the SSO/STS region is
ap-southeast-1. `ListFoundationModels` is a free control-plane call, so this
resolves the question empirically without spending anything.

    make check-bedrock
"""
from __future__ import annotations

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
REGIONS = ["ap-southeast-1", "us-east-1", "us-west-2"]
WANT = [os.getenv("MODEL_PREDICT", "anthropic.claude-haiku-4-5"),
        os.getenv("MODEL_ADAPT", "anthropic.claude-haiku-4-5")]


def main() -> int:
    try:
        session = boto3.Session(profile_name=PROFILE)
        ident = session.client("sts", region_name="ap-southeast-1").get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        print(f"\n  No valid AWS session ({type(exc).__name__}).")
        print("  Run:  make aws-login\n")
        return 1

    print(f"\n  account {ident['Account']}  arn {ident['Arn']}\n")
    ok_regions = []
    for region in REGIONS:
        try:
            models = session.client("bedrock", region_name=region).list_foundation_models()
            ids = {m["modelId"].split(":")[0] for m in models["modelSummaries"]}
            claude = sorted(i for i in ids if "claude" in i.lower())
            print(f"  \033[32m{region:16}\033[0m {len(ids)} models, "
                  f"{len(claude)} Claude")
            for w in WANT:
                bare = w.split(":")[0]
                mark = "✓" if any(bare in c or c in bare for c in claude) else "✗"
                print(f"      {mark} {w}")
            ok_regions.append(region)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "?")
            print(f"  \033[31m{region:16}\033[0m {code}")
        except BotoCoreError as exc:
            print(f"  \033[31m{region:16}\033[0m {type(exc).__name__}")

    print()
    if ok_regions:
        print(f"  Set BEDROCK_REGION in .env to one of: {', '.join(ok_regions)}\n")
    else:
        print("  No region worked. Check the lease is approved and re-run make aws-login.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
