#!/usr/bin/env python
"""
Discover the real sso_account_id / sso_role_name from a live SSO token and
repair aws/config.

Exists because the role name is per-instance: the hackathon deck's screenshot
shows `myisb01_IsbUsersPS`, but this Identity Center issues `hack2026_IsbUsersPS`.
Guessing it produces an opaque `GetRoleCredentials` AccessDenied and CLI exit 254.
"""
from __future__ import annotations

import configparser
import glob
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "aws" / "config"


def cached_token() -> tuple[str, str] | None:
    best = None
    for f in glob.glob(str(Path.home() / ".aws/sso/cache/*.json")):
        try:
            d = json.load(open(f))
        except (OSError, json.JSONDecodeError):
            continue
        if d.get("accessToken") and d.get("startUrl"):
            best = (d["accessToken"], d.get("region", "ap-southeast-1"))
    return best


def main() -> int:
    tok = cached_token()
    if not tok:
        print("  No SSO access token cached. Run: aws sso login --sso-session hackathon")
        return 1
    access_token, region = tok

    sso = boto3.client("sso", region_name=region)
    try:
        accounts = sso.list_accounts(accessToken=access_token, maxResults=60)["accountList"]
    except ClientError as exc:
        print(f"  ListAccounts failed: {exc.response['Error']['Code']}")
        print("  The SSO token is probably expired. Run: make aws-login")
        return 1

    if not accounts:
        print("  No accounts assigned to this login yet.")
        print("  Has your team's sandbox lease been APPROVED? See the deck, slide 17.")
        return 1

    pairs: list[tuple[str, str, str]] = []
    for a in accounts:
        try:
            roles = sso.list_account_roles(
                accessToken=access_token, accountId=a["accountId"])["roleList"]
        except ClientError:
            roles = []
        for r in roles:
            pairs.append((a["accountId"], r["roleName"], a.get("accountName", "")))

    if not pairs:
        print("  Account visible but no roles assigned — lease may still be pending.")
        return 1

    print("  Available account/role pairs:")
    for acct, role, name in pairs:
        print(f"    {acct}  {role}  ({name})")

    acct, role, name = pairs[0]
    if len(pairs) > 1:
        print(f"\n  More than one pair found; using the first ({acct} / {role}).")
        print("  Edit aws/config by hand if that is the wrong one.")

    cp = configparser.ConfigParser()
    cp.read(CONFIG)
    section = "profile hackathon"
    if section not in cp:
        cp[section] = {"sso_session": "hackathon", "output": "json"}
    changed = (cp[section].get("sso_account_id") != acct
               or cp[section].get("sso_role_name") != role)
    cp[section]["sso_account_id"] = acct
    cp[section]["sso_role_name"] = role
    cp[section].setdefault("region", region)

    if changed:
        with open(CONFIG, "r") as fh:
            original = fh.read()
        header = original.split("[sso-session")[0]
        with open(CONFIG, "w") as fh:
            fh.write(header)
            for sec in cp.sections():
                fh.write(f"[{sec}]\n")
                for k, v in cp[sec].items():
                    fh.write(f"{k} = {v}\n")
                fh.write("\n")
        print(f"\n  Repaired aws/config -> account {acct}, role {role}")
    else:
        print(f"\n  aws/config already correct ({acct} / {role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
