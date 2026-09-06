"""Real HTTP/SQL readiness tests, isolated from the developer's database.

Requires QA_DATABASE_URL pointing to a disposable database named pantry_qa*.
Services run from a temporary copy so caches/checkpoints cannot change source.
Only model inference is fake; API calls and PostgreSQL operations are real.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid
from urllib.parse import urlparse

import httpx
import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    dsn = os.getenv("QA_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Set QA_DATABASE_URL to a disposable pantry_qa database")
    parsed = urlparse(dsn)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.path.startswith("/pantry_qa"):
        pytest.fail("Readiness tests require a local, disposable pantry_qa* database")

    runtime = tmp_path_factory.mktemp("pantry-readiness")
    shutil.copytree(ROOT / "services", runtime / "services", ignore=shutil.ignore_patterns(
        "__pycache__", "*.db", "*.db-wal", "*.db-shm", ".venv", ".pytest_cache", "spend.json"))
    fixed = {"inventory": 8000, "auth": 8001, "feedback": 8002, "pricing": 8004, "agent": 8003}
    urls = {name: f"http://127.0.0.1:{fixed[name] if os.getenv('QA_BROWSER_PORTS') == '1' else free_port()}"
            for name in fixed}
    env = {**os.environ, "DATABASE_URL": dsn, "FAKE_LLM": "1", "FAKE_SERVICES": "0",
           "FAKE_INVENTORY": "0", "FAKE_FEEDBACK": "0", "FAKE_PRICING": "0",
           "INVENTORY_URL": urls["inventory"], "FEEDBACK_URL": urls["feedback"],
           "PRICING_URL": urls["pricing"], "AUTH_URL": urls["auth"],
           "SERVICE_AUTH_TOKEN": "readiness-internal-token-at-least-32-bytes", "AUTH_JWT_SECRET": "readiness-tests-only-secret-at-least-32-bytes",
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "OMP_NUM_THREADS": "1",
           "PYTHONIOENCODING": "utf-8"}
    env["PYTHONPATH"] = str(runtime / "services")
    services = runtime / "services"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def sql(query, params=()):
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall() if cur.description else None

    for name in ("auth", "feedback", "orchestrator"):
        sql((services / name / "schema.sql").read_text(encoding="utf-8"))
    for args in (["-m", "alembic", "upgrade", "head"], ["-m", "app.seed"]):
        subprocess.run([sys.executable, *args], cwd=services / "inventory", env=env,
                       check=True, capture_output=True, creationflags=creationflags)

    specs = {"inventory": ("inventory", "app.main:app"), "auth": ("auth", "app.main:app"),
             "feedback": ("feedback", "app.main:app"), "pricing": ("price_forecaster", "app:app"),
             "agent": ("", "orchestrator.api:app")}
    processes, logs = [], []
    client = httpx.Client(timeout=30, trust_env=False)
    try:
        for name, (folder, module) in specs.items():
            log_path = runtime / f"{name}.log"
            log = log_path.open("w", encoding="utf-8")
            logs.append(log)
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1",
                                     "--port", str(urlparse(urls[name]).port)],
                                    cwd=services / folder, env=env, stdout=log, stderr=log,
                                    creationflags=creationflags)
            processes.append(proc)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    pytest.fail(f"{name} exited: {log_path.read_text(encoding='utf-8')}")
                try:
                    response = client.get(urls[name] + "/health")
                    if response.status_code == 200 and response.json().get("status") == "ok":
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                pytest.fail(f"{name} did not become healthy: {log_path.read_text(encoding='utf-8')}")
        response = client.post(urls["auth"] + "/auth/signup", json={
            "email": f"stack-{uuid.uuid4().hex}@example.org", "password": "ReadinessTest123",
            "display_name": "Readiness operator"})
        assert response.status_code == 201, response.text
        yield {"urls": urls, "client": client, "sql": sql, "runtime": runtime, "env": env,
               "headers": {"Authorization": "Bearer " + response.json()["token"]}}
    finally:
        client.close()
        for proc in reversed(processes):
            proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for log in logs:
            log.close()


@pytest.fixture
def api(stack):
    def request(service, method, path, authenticated=True, **kwargs):
        headers = dict(stack["headers"]) if authenticated else {}
        headers.update(kwargs.pop("headers", {}))
        return stack["client"].request(method, stack["urls"][service] + path, headers=headers, **kwargs)
    return request
