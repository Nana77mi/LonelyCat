# LonelyCat Makefile (Linux/WSL/macOS)
# - venv-first (avoids PEP 668 system pip restrictions)
# - monorepo-friendly: do NOT pip install -e at repo root
# - install python libs from ./packages/*
# - run core-api as an app via --app-dir and PYTHONPATH

SHELL := /bin/bash

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

PID_DIR := .pids
API_PID := $(PID_DIR)/core-api.pid

CORE_API_DIR := apps/core/api
WEB_CONSOLE_DIR := apps/web-console

API_HOST := 127.0.0.1
API_PORT := 8000
WEB_PORT := 5173

export PYTHONPATH := packages

.PHONY: help
help:
	@echo "LonelyCat targets:"
	@echo "  make setup      - create venv, upgrade pip, install python libs + web deps"
	@echo "  make setup-py   - only python venv + libs"
	@echo "  make setup-web  - only web-console deps"
	@echo "  make up         - start core-api (bg) + web-console (fg)"
	@echo "  make up-api     - start core-api only (bg)"
	@echo "  make up-web     - start web-console only (fg)"
	@echo "  make down       - stop core-api (and best-effort stop web if running)"
	@echo "  make test       - run python + web tests"
	@echo "  make test-py    - run python tests"
	@echo "  make test-web   - run web tests"
	@echo "  make logs       - tail core-api logs"
	@echo "  make clean      - remove venv + pids + caches"
	@echo ""
	@echo "After 'make up':"
	@echo "  core-api:     http://localhost:$(API_PORT)/docs"
	@echo "  web-console:  http://localhost:$(WEB_PORT)/memory"

# -------------------------
# Setup
# -------------------------
.PHONY: setup
setup: setup-py setup-web

.PHONY: setup-py
setup-py:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	# Install python libraries in editable mode (monorepo packages)
	@if [ -f packages/memory/pyproject.toml ]; then $(PIP) install -e packages/memory; fi
	@if [ -f packages/runtime/pyproject.toml ]; then $(PIP) install -e packages/runtime; fi
	@if [ -f packages/mcp/pyproject.toml ]; then $(PIP) install -e packages/mcp; fi
	@if [ -f packages/protocol/pyproject.toml ]; then $(PIP) install -e packages/protocol; fi
	@if [ -f packages/kb/pyproject.toml ]; then $(PIP) install -e packages/kb; fi
	@if [ -f apps/agent-worker/pyproject.toml ]; then $(PIP) install --no-build-isolation -e apps/agent-worker[test]; fi
	@mkdir -p $(PID_DIR)

.PHONY: setup-web
setup-web:
	@cd $(WEB_CONSOLE_DIR) && corepack enable && pnpm install

# -------------------------
# Run
# -------------------------
.PHONY: up
up: up-api
	@$(MAKE) up-web

.PHONY: up-api
up-api: setup-py
	@mkdir -p $(PID_DIR)
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
		echo "core-api already running (pid=$$(cat $(API_PID)))"; \
	else \
		echo "Starting core-api on http://localhost:$(API_PORT) ..."; \
		nohup env PYTHONPATH=$(PYTHONPATH) $(PY) -m uvicorn app.main:app \
			--reload \
			--host $(API_HOST) \
			--port $(API_PORT) \
			--app-dir $(CORE_API_DIR) \
			> $(PID_DIR)/core-api.log 2>&1 & \
		echo $$! > $(API_PID); \
		echo "core-api pid=$$(cat $(API_PID)) (logs: $(PID_DIR)/core-api.log)"; \
	fi

.PHONY: up-web
up-web: setup-web
	@echo "Starting web-console on http://localhost:$(WEB_PORT) ..."
	@cd $(WEB_CONSOLE_DIR) && pnpm dev --host 0.0.0.0 --port $(WEB_PORT)

# -------------------------
# Stop
# -------------------------
.PHONY: down
down:
	@if [ -f $(API_PID) ]; then \
		PID=$$(cat $(API_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "Stopping core-api (pid=$$PID)"; \
			kill $$PID || true; \
		else \
			echo "core-api not running (stale pid file)"; \
		fi; \
		rm -f $(API_PID); \
	else \
		echo "No core-api pid file found."; \
	fi
	@echo "Note: web-console runs in foreground. Stop it with Ctrl+C in its terminal."

# -------------------------
# Tests
# -------------------------
.PHONY: test
test: test-py test-web

.PHONY: test-py
test-py: setup-py
	@echo "Running python tests..."
	@env PYTHONPATH=$(PYTHONPATH) $(PY) -m pytest apps/agent-worker/tests -q

.PHONY: test-web
test-web:
	@echo "Running web tests..."
	@cd $(WEB_CONSOLE_DIR) && pnpm test

# -------------------------
# Logs / Clean
# -------------------------
.PHONY: logs
logs:
	@tail -n 200 -f $(PID_DIR)/core-api.log

.PHONY: clean
clean:
	@echo "Cleaning venv, pids, caches..."
	@rm -rf $(VENV) $(PID_DIR) .pytest_cache
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} \; 2>/dev/null || true
