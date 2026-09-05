"""Configuration. Mirrors services/orchestrator/config.py's pattern so the
whole team resolves the same SSO profile and cost-control flags from one
place — there is no per-service .env any more.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[2]          # services/feedback/app -> services/feedback -> services -> repo
AWS_DIR = REPO_ROOT / "aws"

load_dotenv(REPO_ROOT / ".env")

# Same project-local AWS config every other service points at, so a personal
# ~/.aws/config can't silently shadow the team's shared SSO profile.
os.environ.setdefault("AWS_CONFIG_FILE", str(AWS_DIR / "config"))
os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", str(AWS_DIR / "credentials"))


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # FAKE_LLM=1 is the shared default across the whole repo -- turning it off
    # spends real money. Lets this service be smoke-tested for $0 before AWS
    # SSO is even set up.
    fake_llm: bool = _flag("FAKE_LLM", "1")

    aws_profile: str | None = os.getenv("AWS_PROFILE") or None
    bedrock_region: str = os.getenv("BEDROCK_REGION") or os.getenv(
        "AWS_REGION", "ap-southeast-1")
    # Same model the orchestrator already has confirmed working on this
    # account's Bedrock access -- not guessing at a different one blind.
    model_extract: str = os.getenv("MODEL_EXTRACT", "anthropic.claude-haiku-4-5")
    max_tokens_extract: int = int(os.getenv("MAX_TOKENS_EXTRACT", "2048"))

    database_url: str = os.getenv("DATABASE_URL", "")
    feedback_service_port: int = int(os.getenv("FEEDBACK_SERVICE_PORT", "8002"))
    matcher_llm_adjudication: bool = _flag("MATCHER_LLM_ADJUDICATION", "false")


settings = Settings()
