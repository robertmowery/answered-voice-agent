# The Always-On Agentic Front Office: one command per step.
#
# Set PROJECT once, for example:  export PROJECT=my-brightwater-test
# Every target names the project explicitly; nothing relies on gcloud's default.

PROJECT ?= $(GOOGLE_CLOUD_PROJECT)
REGION  ?= us-central1
PY      := .venv/bin/python

SERVICES := tools-api ticket-worker ucp-server commerce-agent
# Services whose tests run in the main .venv; the commerce agent pins its own ADK stack.
TESTED := tools-api ticket-worker ucp-server
# The UCP server is a public storefront endpoint; everything else requires an identity.
PUBLIC := ucp-server

.PHONY: help venv test test-commerce landing-zone services deploy smoke evals teardown check-project

help:
	@echo "make venv          create .venv and install requirements"
	@echo "make test          ruff, mypy and unit tests (no cloud calls)"
	@echo "make landing-zone  terraform apply in infra/terraform"
	@echo "make services      build and deploy the Cloud Run services (Part 2 on)"
	@echo "make deploy        deploy agent/ to CX Agent Studio"
	@echo "make smoke         run evals/part1_smoke.yaml (8 sessions, about \$$4)"
	@echo "make evals PART=2  run evals/partN_*.yaml conversations (one session each)"
	@echo "make teardown      delete the agent app and destroy the landing zone"

check-project:
	@test -n "$(PROJECT)" || (echo "Set PROJECT=your-project-id" && exit 1)

venv:
	python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt -r requirements-dev.txt

test:
	$(PY) -m ruff check .
	$(PY) -m mypy
	$(PY) -m pytest -q
	for s in $(TESTED); do (cd services/$$s && ../../$(PY) -m pytest -q) || exit 1; done

test-commerce:
	python3 -m venv .venv-commerce && .venv-commerce/bin/pip install -q -r services/commerce-agent/requirements.txt pytest pyyaml google-cloud-firestore fastapi
	cd services/commerce-agent && ../../.venv-commerce/bin/python -m pytest -q

landing-zone: check-project
	cd infra/terraform && terraform init -input=false && terraform apply

services: check-project
	for s in $(SERVICES); do \
	  auth=$$(echo " $(PUBLIC) " | grep -q " $$s " && echo --allow-unauthenticated || echo --no-allow-unauthenticated); \
	  gcloud run deploy $$s --source services/$$s --region $(REGION) --project $(PROJECT) $$auth --quiet || exit 1; \
	done

deploy: check-project
	TOOLS_API_URL=$$(cd infra/terraform && terraform output -raw tools_api_url) \
	COMMERCE_AGENT_URL=$$(cd infra/terraform && terraform output -raw commerce_agent_url) \
	DLP_INSPECT_TEMPLATE=$$(cd infra/terraform && terraform output -raw dlp_inspect_template) \
	DLP_DEIDENTIFY_TEMPLATE=$$(cd infra/terraform && terraform output -raw dlp_deidentify_template) \
	  $(PY) scripts/deploy_agent.py --project $(PROJECT) --label release

smoke: check-project
	$(PY) scripts/smoke.py --project $(PROJECT)

evals: check-project
	for f in evals/part$(PART)_*.yaml; do \
	  $(PY) scripts/run_evals.py --project $(PROJECT) --cases $$f --out results/part$(PART)/$$(basename $$f .yaml).json; \
	done

teardown: check-project
	$(PY) scripts/teardown_agent.py --project $(PROJECT)
	cd infra/terraform && terraform destroy
