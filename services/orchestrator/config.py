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
    # No FAKE_LLM toggle: the agent node always calls real Bedrock. The
    # session-spend cap below (checked before every single call, never just
    # once at loop start) is the safety net instead of a fake-mode fallback.
    fake_services: bool = _flag("FAKE_SERVICES", "0")
    # Per-service overrides, each defaulting to FAKE_SERVICES. Lets workstreams
    # be integrated one at a time as they land instead of all-or-nothing.
    fake_inventory: bool = _flag("FAKE_INVENTORY", os.getenv("FAKE_SERVICES", "0"))
    fake_feedback: bool = _flag("FAKE_FEEDBACK", os.getenv("FAKE_SERVICES", "0"))
    fake_pricing: bool = _flag("FAKE_PRICING", os.getenv("FAKE_SERVICES", "0"))
    max_session_spend_usd: float = float(os.getenv("MAX_SESSION_SPEND_USD", "2.00"))
    ledger_path: Path = Path(os.getenv("LEDGER_PATH", str(ROOT / "spend.json")))
    aws_dir: Path = AWS_DIR

    # --- aws / bedrock ----------------------------------------------------
    # No keys. `aws_profile` resolves an SSO profile that boto3 auto-refreshes.
    aws_profile: str | None = os.getenv("AWS_PROFILE") or None
    aws_region: str = os.getenv("AWS_REGION", "ap-southeast-1")
    # Inference region may differ from the SSO region — see `make check-bedrock`.
    bedrock_region: str = os.getenv("BEDROCK_REGION") or "us-east-1"
    # bedrock-runtime InvokeModel needs the INFERENCE PROFILE id (us. prefix).
    # Claude Haiku 4.5 is INFERENCE_PROFILE-only in us-east-1, so the bare
    # `anthropic.claude-haiku-4-5` id is rejected on this path.
    model_predict: str = os.getenv("MODEL_PREDICT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    model_adapt: str = os.getenv("MODEL_ADAPT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    max_tokens_predict: int = int(os.getenv("MAX_TOKENS_PREDICT", "4096"))
    max_tokens_adapt: int = int(os.getenv("MAX_TOKENS_ADAPT", "2048"))

    # --- upstream services (workstreams 1/2/3) ----------------------------
    inventory_url: str = os.getenv("INVENTORY_URL", "http://localhost:8000")
    feedback_url: str = os.getenv("FEEDBACK_URL", "http://localhost:8002")
    pricing_url: str = os.getenv("PRICING_URL", "http://localhost:8004")
    http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "5.0"))

    # --- graph ------------------------------------------------------------
    # Caps LLM turns in the agent node. Every tool-call round needs one
    # preceding LLM turn, so this alone bounds total tool executions too --
    # the old per-step `max_retries` (adapt.py) no longer applies since there
    # is no separate adapt node; this is its replacement, sized for a full
    # sense->diagnose->act(->retry)*->done loop rather than just retries.
    max_agent_turns: int = max(1, int(os.getenv("MAX_AGENT_TURNS", "10")))
    checkpoint_path: Path = Path(os.getenv("CHECKPOINT_PATH", str(ROOT / "checkpoints.db")))

    # --- watch mode (event-driven runs, see watch.py) ----------------------
    # How often the background poller checks whether enough has changed to
    # justify a run. 1 minute matches the product spec directly.
    watch_poll_seconds: float = float(os.getenv("WATCH_POLL_SECONDS", "60"))
    # Trigger A: this many NEW feedback rows since the last check.
    watch_feedback_trigger: int = int(os.getenv("WATCH_FEEDBACK_TRIGGER", "10"))
    # Trigger B: inventory "shifts by a lot" -- this many MORE SKUs newly in
    # `below_reorder`/`expiring_soon` since the last check (a delta, not an
    # absolute count, so a persistently-high-but-unchanged alert count does
    # not re-trigger every cycle).
    watch_inventory_trigger: int = int(os.getenv("WATCH_INVENTORY_TRIGGER", "3"))
    # Auto-deactivate after this many consecutive idle polls (no trigger, no
    # run in flight) -- an activated watch that never sees anything worth
    # acting on should not poll forever.
    watch_quiet_cycles_limit: int = int(os.getenv("WATCH_QUIET_CYCLES_LIMIT", "2"))


settings = Settings()

# Baselines live in code, not in prompt prose — the approval node reads these
# back to the human, so there must be exactly one source of truth.
from pantry_common.baselines import BASELINES
