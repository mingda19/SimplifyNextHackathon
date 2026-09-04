"""Configuration and baselines. Single source of truth for both."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]          # services/orchestrator -> services -> repo
AWS_DIR = REPO_ROOT / "aws"

# One global .env at the repo root. There is no per-service .env any more.
load_dotenv(REPO_ROOT / ".env")

# Point the AWS SDKs at the project-local config so every teammate resolves the
# same SSO profile, and a personal ~/.aws/config can't silently shadow it.
# Credentials themselves are never stored here — boto3 pulls them from the SSO
# token cache in ~/.aws/sso/cache/ and refreshes them on its own.
os.environ.setdefault("AWS_CONFIG_FILE", str(AWS_DIR / "config"))
os.environ.setdefault("AWS_SHARED_CREDENTIALS_FILE", str(AWS_DIR / "credentials"))


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings. Read once at import."""

    # --- cost controls (see plan.md §7) -----------------------------------
    # FAKE_LLM=1 is the default ON PURPOSE. Turning it off spends real money.
    fake_llm: bool = _flag("FAKE_LLM", "1")
    fake_services: bool = _flag("FAKE_SERVICES", "1")
    # Per-service overrides, each defaulting to FAKE_SERVICES. Lets workstreams
    # be integrated one at a time as they land instead of all-or-nothing.
    fake_inventory: bool = _flag("FAKE_INVENTORY", os.getenv("FAKE_SERVICES", "1"))
    fake_feedback: bool = _flag("FAKE_FEEDBACK", os.getenv("FAKE_SERVICES", "1"))
    fake_pricing: bool = _flag("FAKE_PRICING", os.getenv("FAKE_SERVICES", "1"))
    max_session_spend_usd: float = float(os.getenv("MAX_SESSION_SPEND_USD", "2.00"))
    ledger_path: Path = ROOT / "spend.json"
    aws_dir: Path = AWS_DIR

    # --- aws / bedrock ----------------------------------------------------
    # No keys. `aws_profile` resolves an SSO profile that boto3 auto-refreshes.
    aws_profile: str | None = os.getenv("AWS_PROFILE") or None
    aws_region: str = os.getenv("AWS_REGION", "ap-southeast-1")
    # Inference region may differ from the SSO region — see `make check-bedrock`.
    bedrock_region: str = os.getenv("BEDROCK_REGION") or os.getenv(
        "AWS_REGION", "ap-southeast-1")
    # Bedrock IDs take the `anthropic.` prefix. NOT the 2024 id in the AWS deck.
    model_predict: str = os.getenv("MODEL_PREDICT", "anthropic.claude-haiku-4-5")
    model_adapt: str = os.getenv("MODEL_ADAPT", "anthropic.claude-haiku-4-5")
    max_tokens_predict: int = int(os.getenv("MAX_TOKENS_PREDICT", "4096"))
    max_tokens_adapt: int = int(os.getenv("MAX_TOKENS_ADAPT", "2048"))

    # --- upstream services (workstreams 1/2/3) ----------------------------
    inventory_url: str = os.getenv("INVENTORY_URL", "http://localhost:8001")
    feedback_url: str = os.getenv("FEEDBACK_URL", "http://localhost:8002")
    pricing_url: str = os.getenv("PRICING_URL", "http://localhost:8003")
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "5.0"))

    # --- graph ------------------------------------------------------------
    max_retries: int = int(os.getenv("MAX_ADAPT_RETRIES", "3"))
    checkpoint_path: Path = ROOT / "checkpoints.db"


settings = Settings()

# Baselines live in code, not in prompt prose — the approval node reads these
# back to the human, so there must be exactly one source of truth.
BASELINES: dict[str, float] = {
    "min_days_cover": 10,
    "monthly_budget_sgd": 5_000,
    "max_single_order_sgd": 1_500,   # above this -> mandatory human approval
    "expiry_buffer_days": 14,
}
