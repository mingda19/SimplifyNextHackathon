VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: install run run-a demo test ledger reset-ledger creds clean

install:
	python3 -m venv $(VENV) && $(PY) -m pip install -q -U pip -r requirements.txt

run:            ## interactive approval, fake mode, $0
	$(PY) -m orchestrator

demo:           ## the scripted scenario, auto-approved, $0
	$(PY) -m orchestrator --approve -v

run-a:          ## donation-fed charity (Type A)
	$(PY) -m orchestrator --type A --approve

test:
	$(PY) -m pytest orchestrator/tests/ -q

ledger:
	$(PY) -m orchestrator --ledger

reset-ledger:
	$(PY) -m orchestrator --reset-ledger

creds:          ## how to refresh the 12-hour AWS keys
	@echo "1. https://d-9667b91afb.awsapps.com/start  ->  Accounts tab"
	@echo "2. Expand SandboxAccount001  ->  'Access keys'"
	@echo "3. Copy Option 1 (env vars) into orchestrator/.env"
	@echo "   ALL THREE: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN"
	@echo "4. Region must be us-east-1"

clean:
	rm -f orchestrator/checkpoints.db orchestrator/spend.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
