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

if aws sts get-caller-identity --profile "$PROFILE" >/dev/null 2>&1; then
  echo "SSO session already valid."
else
  echo "Opening browser for SSO login (profile: $PROFILE)..."
  if ! aws sso login --profile "$PROFILE"; then
    cat <<'HINT'

Login failed. The usual cause is a wrong sso_account_id or sso_role_name in
aws/config. Rediscover them interactively — it lists the accounts and roles
your login can actually see:

    AWS_CONFIG_FILE=./aws/config aws configure sso --profile hackathon

Use these when prompted:
    SSO start URL  : https://d-9667b91afb.awsapps.com/start
    SSO region     : ap-southeast-1
HINT
    exit 1
  fi
fi

echo
aws sts get-caller-identity --profile "$PROFILE" --output table
