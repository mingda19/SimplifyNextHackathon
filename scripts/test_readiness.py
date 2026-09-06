"""Run readiness tests with a disposable PostgreSQL container.

Install tests/readiness/requirements.txt, start Docker, then run this script.
Does not use .env credentials, existing volumes, or paid model APIs.
Returns pytest's exit status and always stops its own test container.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Docker must be installed and available on PATH")
    name = "pantry-readiness-" + uuid.uuid4().hex[:10]
    output = ROOT / ".qa"
    output.mkdir(exist_ok=True)
    try:
        subprocess.run([docker, "run", "--detach", "--rm", "--name", name,
                        "--publish", "127.0.0.1::5432", "--env", "POSTGRES_DB=pantry_qa",
                        "--env", "POSTGRES_USER=pantry_qa", "--env", "POSTGRES_PASSWORD=pantry_qa",
                        "postgres:16-alpine"], check=True)
        for _ in range(30):
            ready = subprocess.run([docker, "exec", name, "pg_isready", "-U", "pantry_qa", "-d", "pantry_qa"],
                                   capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise SystemExit("Disposable PostgreSQL did not become ready")
        port = subprocess.check_output([docker, "port", name, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
        env = {**os.environ, "QA_DATABASE_URL": f"postgresql://pantry_qa:pantry_qa@127.0.0.1:{port}/pantry_qa",
               "FAKE_LLM": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("QA_BROWSER_PORTS", None)
        with (output / "readiness.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, "-m", "pytest", "tests/readiness", "-q", "--tb=short",
                                     "--junitxml=.qa/readiness.xml"], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
            try:
                for line in proc.stdout:
                    print(line, end="")
                    log.write(line)
                return proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=15)
    finally:
        subprocess.run([docker, "stop", name], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
