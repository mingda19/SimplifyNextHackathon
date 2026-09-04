VENV := .venv
# the orchestrator package lives under services/
PY   := PYTHONPATH=services $(VENV)/bin/python

.PHONY: check-bedrock-live aws-login aws-whoami aws-export check-bedrock install run run-a demo test ledger reset-ledger creds clean

install:
	python3 -m venv $(VENV) && $(VENV)/bin/python -m pip install -q -U pip -r requirements.txt

run:            ## interactive approval, fake mode, $0
	$(PY) -m orchestrator

demo:           ## the scripted scenario, auto-approved, $0
	$(PY) -m orchestrator --approve -v

run-a:          ## donation-fed charity (Type A)
	$(PY) -m orchestrator --type A --approve

test:
	$(PY) -m pytest services/orchestrator/tests/ -q

ledger:
	$(PY) -m orchestrator --ledger

reset-ledger:
	$(PY) -m orchestrator --reset-ledger

creds:          ## deprecated -> use `make aws-login`
	@echo "Credentials are handled by SSO now. Run: make aws-login"

clean:
	rm -f services/orchestrator/checkpoints.db services/orchestrator/spend.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---- AWS SSO ---------------------------------------------------------------
aws-login:      ## browser SSO login; refreshes the session (~12h)
	@./scripts/aws-login.sh

aws-whoami:     ## who am I, and is the session still valid
	@AWS_CONFIG_FILE=./aws/config aws sts get-caller-identity \
		--profile $${AWS_PROFILE:-hackathon} --output table

check-bedrock:  ## identity + Mantle endpoint reachability (free)
	@$(PY) scripts/check_bedrock.py

check-bedrock-live: ## ONE 1-token real call to confirm the model id (~$$0.00002)
	@$(PY) scripts/check_bedrock.py --live

aws-export:     ## write short-lived static keys to aws/credentials (rarely needed)
	@./scripts/aws-export-credentials.sh
