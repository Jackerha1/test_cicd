# AI-CICD operations interface — Karpathy: one tool, predictable verbs.
#
# `make help` shows everything. Don't add a subcommand here without also
# documenting it in the runbook.

SHELL := /bin/bash
COMPOSE := docker compose
PIPELINE := ai-cicd-pipeline
GATEWAY := ai-cicd-gateway

.PHONY: help up down restart build rebuild logs logs-pipeline logs-gateway \
        ps ready run eval compare cost trifecta-audit memory audit \
        shell-pipeline shell-gateway clean-state nuke

help:                ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- lifecycle -----------------------------------------------------

up:                  ## build (if needed) and start the full stack
	$(COMPOSE) up -d --build
	@echo
	@$(MAKE) ready

down:                ## stop and remove containers (state preserved)
	$(COMPOSE) down

restart:             ## restart both services
	$(COMPOSE) restart

build:               ## build images (no start)
	$(COMPOSE) build

rebuild:             ## force-rebuild images from scratch
	$(COMPOSE) build --no-cache

ps:                  ## list service status
	$(COMPOSE) ps

# ---------- observability -------------------------------------------------

logs:                ## tail logs from both services (Ctrl-C to exit)
	$(COMPOSE) logs -f --tail=100

logs-pipeline:       ## tail pipeline logs only
	$(COMPOSE) logs -f --tail=100 pipeline

logs-gateway:        ## tail gateway logs only
	$(COMPOSE) logs -f --tail=100 gateway

ready:               ## check both healthchecks; non-zero exit if any unhealthy
	@curl -fsS http://localhost:8200/readyz   | sed 's/^/gateway:  /'
	@curl -fsS http://localhost:8000/readyz   | sed 's/^/pipeline: /'

# ---------- pipeline operations ------------------------------------------

EVENT ?= examples/pr_docs_only.json
run:                 ## run the pipeline against EVENT=examples/X.json (default: pr_docs_only)
	$(COMPOSE) exec pipeline ai-cicd run $(EVENT)

eval:                ## run the eval harness inside the pipeline container
	$(COMPOSE) exec pipeline ai-cicd eval

compare:             ## run eval across providers (PROVIDERS=claude,gemini)
	$(COMPOSE) exec pipeline ai-cicd compare --providers $${PROVIDERS:-claude,gemini}

cost:                ## cost breakdown for a pipeline run (PIPELINE_ID=...)
	@if [ -z "$$PIPELINE_ID" ]; then echo "Set PIPELINE_ID=pipe-..."; exit 2; fi
	$(COMPOSE) exec pipeline ai-cicd cost $$PIPELINE_ID

audit:               ## audit trail for a pipeline run (PIPELINE_ID=...)
	@if [ -z "$$PIPELINE_ID" ]; then echo "Set PIPELINE_ID=pipe-..."; exit 2; fi
	$(COMPOSE) exec pipeline ai-cicd audit $$PIPELINE_ID

trifecta-audit:      ## static check of approval matrix vs lethal-trifecta rule
	$(COMPOSE) exec pipeline ai-cicd trifecta-audit

memory:              ## show learned memory for REPO=owner/repo
	@if [ -z "$$REPO" ]; then echo "Set REPO=owner/repo"; exit 2; fi
	$(COMPOSE) exec pipeline ai-cicd memory $$REPO

# ---------- debugging -----------------------------------------------------

shell-pipeline:      ## open a shell in the pipeline container
	$(COMPOSE) exec pipeline /bin/bash

shell-gateway:       ## open a shell in the gateway container
	$(COMPOSE) exec gateway /bin/bash

# ---------- destructive (require confirmation) ----------------------------

clean-state:         ## delete artifacts/, logs/, data/, memory/ (NOT containers)
	@read -p "Delete all per-pipeline state? [y/N] " ans && [ "$$ans" = "y" ]
	rm -rf artifacts/* logs/* data/* memory/*

nuke:                ## down + delete state + delete volumes (cannot be undone)
	@read -p "FULL TEARDOWN: delete containers + state? [y/N] " ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v
	rm -rf artifacts/* logs/* data/* memory/*
