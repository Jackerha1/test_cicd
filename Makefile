# AI-CICD operations interface — Karpathy: one tool, predictable verbs.
#
# `make help` shows everything. Don't add a subcommand here without also
# documenting it in the runbook.
#
# Topology: claude-cli-api gateway runs on HOST (so OAuth tokens for
# claude/gemini CLIs actually work). Pipeline runs in a container that
# reaches the host via host.docker.internal:8200.

SHELL := /bin/bash
COMPOSE := docker compose

GATEWAY_DIR := claude-cli-api
GATEWAY_PORT := 8200
GATEWAY_PID := /tmp/ai-cicd-gateway.pid
GATEWAY_LOG := /tmp/ai-cicd-gateway.log

.PHONY: help up down restart build rebuild logs logs-pipeline \
        gateway gateway-stop gateway-logs gateway-ready ps ready \
        run eval compare cost trifecta-audit memory audit \
        shell-pipeline clean-state nuke

help:                ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- gateway (host-side) -------------------------------------------

gateway:             ## start claude-cli-api on the HOST (uses your OAuth tokens)
	@if [ -f $(GATEWAY_PID) ] && kill -0 $$(cat $(GATEWAY_PID)) 2>/dev/null; then \
	  echo "gateway already running (pid $$(cat $(GATEWAY_PID)))"; \
	else \
	  echo "starting gateway on :$(GATEWAY_PORT)"; \
	  cd $(GATEWAY_DIR) && \
	    source .venv/bin/activate && \
	    PORT=$(GATEWAY_PORT) PLANNER_BACKEND=auto \
	    nohup python main.py > $(GATEWAY_LOG) 2>&1 & echo $$! > $(GATEWAY_PID); \
	  echo "  pid: $$(cat $(GATEWAY_PID))  log: $(GATEWAY_LOG)"; \
	  for i in $$(seq 1 30); do \
	    curl -fsS http://localhost:$(GATEWAY_PORT)/healthz >/dev/null 2>&1 && \
	      echo "  healthy" && break; \
	    sleep 1; \
	  done; \
	fi

gateway-stop:        ## stop the host-side gateway
	@if [ -f $(GATEWAY_PID) ]; then \
	  pid=$$(cat $(GATEWAY_PID)); \
	  echo "stopping gateway (pid $$pid)"; \
	  kill $$pid 2>/dev/null || true; \
	  rm -f $(GATEWAY_PID); \
	else \
	  echo "no pidfile $(GATEWAY_PID)"; \
	fi

gateway-logs:        ## tail host-side gateway logs (Ctrl-C to exit)
	tail -f $(GATEWAY_LOG)

gateway-ready:       ## is the host-side gateway healthy?
	@curl -fsS http://localhost:$(GATEWAY_PORT)/readyz | sed 's/^/gateway:  /'

# ---------- pipeline lifecycle (containerized) ----------------------------

up:                  ## start gateway (host) + pipeline (container)
	@$(MAKE) gateway
	$(COMPOSE) up -d --build pipeline
	@echo
	@$(MAKE) ready

down:                ## stop the pipeline container (gateway stays up)
	$(COMPOSE) down

down-all:            ## stop pipeline AND host gateway
	$(COMPOSE) down
	@$(MAKE) gateway-stop

restart:             ## restart the pipeline container
	$(COMPOSE) restart pipeline

build:               ## build pipeline image (no start)
	$(COMPOSE) build pipeline

rebuild:             ## force-rebuild pipeline image from scratch
	$(COMPOSE) build --no-cache pipeline

ps:                  ## list pipeline container status + gateway pid
	@$(COMPOSE) ps
	@echo
	@if [ -f $(GATEWAY_PID) ] && kill -0 $$(cat $(GATEWAY_PID)) 2>/dev/null; then \
	  echo "gateway: running (pid $$(cat $(GATEWAY_PID)))"; \
	else \
	  echo "gateway: not running"; \
	fi

# ---------- observability -------------------------------------------------

logs:                ## tail pipeline logs (gateway: see gateway-logs)
	$(COMPOSE) logs -f --tail=100 pipeline

logs-pipeline:       ## alias of logs
	@$(MAKE) logs

ready:               ## check both healthchecks; non-zero if any unhealthy
	@$(MAKE) gateway-ready
	@curl -fsS http://localhost:8000/readyz | sed 's/^/pipeline: /'

# ---------- pipeline operations ------------------------------------------

EVENT ?= examples/pr_docs_only.json
run:                 ## run the pipeline against EVENT=examples/X.json
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

# ---------- destructive (require confirmation) ----------------------------

clean-state:         ## delete artifacts/, logs/, data/, memory/ (NOT containers)
	@read -p "Delete all per-pipeline state? [y/N] " ans && [ "$$ans" = "y" ]
	rm -rf artifacts/* logs/* data/* memory/*

nuke:                ## down + delete state + delete volumes (cannot be undone)
	@read -p "FULL TEARDOWN: delete containers + state? [y/N] " ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v
	@$(MAKE) gateway-stop
	rm -rf artifacts/* logs/* data/* memory/*
