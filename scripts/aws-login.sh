#!/usr/bin/env bash
# Refresh the AWS SSO session. Nothing is copied or pasted.
#
# After this, boto3 renews the underlying 12-hour session token by itself for
# as long as the SSO login stays valid — so the orchestrator keeps working
# without further intervention.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_CONFIG_FILE="$ROOT/aws/config"
export AWS_SHARED_CREDENTIALS_FILE="$ROOT/aws/credentials"
PROFILE="${AWS_PROFILE:-hackathon}"

command -v aws >/dev/null || { echo "AWS CLI not installed: brew install awscli"; exit 1; }

if ! aws configure list-profiles 2>/dev/null | grep -qx "$PROFILE"; then
  echo "Profile '$PROFILE' is not in $AWS_CONFIG_FILE."
  echo "Run:  aws configure sso --profile $PROFILE"
  exit 1
fi

PYBIN="$ROOT/.venv/bin/python"; [ -x "$PYBIN" ] || PYBIN=python3

if aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
  echo "SSO session already valid."
else
  # Log in against the sso-session, NOT the profile. This still works when the
  # profile's account/role are wrong, which is what lets us self-heal below.
  echo "Opening browser for SSO login..."
  aws sso login --sso-session hackathon || {
    echo "SSO login itself failed — check the start URL in aws/config."; exit 1; }

  # The token is now valid but the profile may still name a role that does not
  # exist on this Identity Center instance (the deck's screenshot shows a
  # different one). That surfaces as GetRoleCredentials AccessDenied / exit 254.
  if ! aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
    echo
    echo "Token is valid but the profile's account/role is wrong. Repairing..."
    "$PYBIN" "$ROOT/scripts/aws_discover.py" || exit 1
  fi
fi

echo
aws sts get-caller-identity --profile "$PROFILE" --output table
