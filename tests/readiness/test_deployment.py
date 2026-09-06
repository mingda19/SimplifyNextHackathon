"""Deployment prerequisites for connecting real workstreams."""
import importlib.util
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_pricing_proxy_is_not_routed_to_orchestrator():
    vite = (ROOT / "frontend/app/vite.config.js").read_text(encoding="utf-8")
    def target(prefix):
        return re.search(r'"' + re.escape(prefix) + r'":\s*\{\s*target:\s*"([^"]+)"', vite).group(1)
    assert target("/api/pricing") != target("/api/agent"), "Pricing is a separate service, not an orchestrator route"


def test_compose_includes_a_price_forecaster_service():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert any("price" in str(service.get("build", "")) for service in compose["services"].values())


def test_compose_persists_orchestrator_checkpoints():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert compose["services"]["orchestrator"].get("volumes"), "SQLite checkpoints are stored only in the container layer"


def test_compose_connects_orchestrator_to_real_services():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    env = compose["services"]["orchestrator"].get("environment", {})
    for name in ("INVENTORY_URL", "FEEDBACK_URL", "PRICING_URL"):
        assert name in env and "localhost" not in env[name], f"Missing container service address: {name}"
    assert "FAKE_SERVICES" in env, "Graph silently defaults to fixtures instead of sensing running services"


def test_bedrock_signing_dependencies_are_installed():
    for name in ("boto3", "botocore"):
        assert importlib.util.find_spec(name) is not None, f"{name} is needed by AnthropicBedrock request signing"
