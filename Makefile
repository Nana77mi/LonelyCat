# LonelyCat Makefile (Linux/WSL/macOS)
# - venv-first (avoids PEP 668 system pip restrictions)
# - WSL/Linux 使用 .venv-dev，与 Windows 主环境 .venv 分离，避免冲突
# - monorepo-friendly: do NOT pip install -e at repo root
# - install python libs from ./packages/*
# - run core-api as an app via --app-dir and PYTHONPATH

SHELL := /bin/bash

VENV := .venv-dev
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

PID_DIR := .pids
API_PID := $(PID_DIR)/core-api.pid
WORKER_PID := $(PID_DIR)/agent-worker.pid

CORE_API_DIR := apps/core-api
AGENT_WORKER_DIR := apps/agent-worker
WEB_CONSOLE_DIR := apps/web-console

API_HOST := 127.0.0.1
API_PORT := 5173
WEB_PORT := 8000

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
	@echo "  make test           - run python + web tests"
	@echo "  make test-py        - run core-api + agent-worker python tests"
	@echo "  make test-core-api  - run core-api tests (needs fastapi/httpx via setup-py)"
	@echo "  make test-agent-worker - run agent-worker tests"
	@echo "  make test-web       - run web tests"
	@echo "  make logs       - tail core-api logs"
	@echo "  make clean      - remove venv + pids + caches"
	@echo ""
	@echo "After 'make up':"
	@echo "  core-api:     http://localhost:$(API_PORT)/docs"
	@echo "  web-console:  http://localhost:$(WEB_PORT)"
	@echo ""
	@echo "Agent worker LLM examples:"
	@echo "  LLM_PROVIDER=stub python -m agent_worker.chat \"hi\""
	@echo "  LLM_PROVIDER=openai OPENAI_API_KEY=... python -m agent_worker.chat \"hi\""
	@echo "  LLM_PROVIDER=qwen QWEN_API_KEY=... python -m agent_worker.chat \"hi\""
	@echo "  LLM_PROVIDER=ollama OLLAMA_BASE_URL=... python -m agent_worker.chat \"hi\""

# -------------------------
# Setup
# -------------------------
.PHONY: setup
setup: setup-py setup-web

.PHONY: setup-py
setup-py:
	@if [ -d $(VENV) ] && [ ! -x $(VENV)/bin/python ]; then \
		echo "Removing Windows-style or broken $(VENV) (no bin/python), recreating..."; \
		rm -rf $(VENV); \
	fi; \
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PIP) install setuptools wheel
	# Install python libraries in editable mode (monorepo packages)
	@if [ -f packages/memory/pyproject.toml ]; then $(PIP) install -e packages/memory; fi
	@if [ -f packages/runtime/pyproject.toml ]; then $(PIP) install -e packages/runtime; fi
	@if [ -f packages/mcp/pyproject.toml ]; then $(PIP) install -e packages/mcp; fi
	@if [ -f packages/protocol/pyproject.toml ]; then $(PIP) install -e packages/protocol; fi
	@if [ -f packages/kb/pyproject.toml ]; then $(PIP) install -e packages/kb; fi
	@if [ -f apps/agent-worker/pyproject.toml ]; then $(PIP) install --no-build-isolation -e apps/agent-worker[test]; fi
	@if [ -f apps/core-api/pyproject.toml ]; then $(PIP) install -e apps/core-api[test]; fi
	@mkdir -p $(PID_DIR)

.PHONY: setup-web
setup-web:
	@cd $(WEB_CONSOLE_DIR) && corepack enable && \
	if [ -d node_modules ] && [ ! -w node_modules/@testing-library 2>/dev/null ]; then \
		echo "Fixing permissions on node_modules..."; \
		chmod -R u+w node_modules 2>/dev/null || true; \
	fi && \
	pnpm install --no-frozen-lockfile

# -------------------------
# Run
# -------------------------
.PHONY: up
up: up-api up-worker
	@echo ""
	@echo "=========================================="
	@echo "  LonelyCat 服务启动中..."
	@echo "=========================================="
	@echo ""
	@echo "✓ 核心 API 已启动: http://localhost:$(API_PORT)"
	@echo "  - API 文档: http://localhost:$(API_PORT)/docs"
	@echo "  - 健康检查: http://localhost:$(API_PORT)/health"
	@echo ""
	@echo "正在启动用户界面..."
	@echo ""
	@$(MAKE) up-web

.PHONY: up-api
up-api: setup-py
	@mkdir -p $(PID_DIR)
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
		echo "⚠️  core-api 已在运行 (pid=$$(cat $(API_PID)))"; \
		echo "   访问地址: http://localhost:$(API_PORT)"; \
	else \
		echo "🚀 启动核心 API (端口 $(API_PORT))..."; \
		nohup env PYTHONPATH=$(PYTHONPATH) $(PY) -m uvicorn app.main:app \
			--reload \
			--host $(API_HOST) \
			--port $(API_PORT) \
			--app-dir $(CORE_API_DIR) \
			> $(PID_DIR)/core-api.log 2>&1 & \
		echo $$! > $(API_PID); \
		sleep 2; \
		if kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
			echo "✓ core-api 启动成功 (pid=$$(cat $(API_PID)))"; \
			echo "  日志文件: $(PID_DIR)/core-api.log"; \
		else \
			echo "✗ core-api 启动失败，请查看日志: $(PID_DIR)/core-api.log"; \
			exit 1; \
		fi; \
	fi

.PHONY: up-worker
up-worker: setup-py
	@mkdir -p $(PID_DIR)
	@if [ -f $(WORKER_PID) ] && kill -0 $$(cat $(WORKER_PID)) 2>/dev/null; then \
		echo "⚠️  agent-worker 已在运行 (pid=$$(cat $(WORKER_PID)))"; \
	else \
		echo "🚀 启动 agent-worker..."; \
		nohup env PYTHONPATH=$(PYTHONPATH):$(AGENT_WORKER_DIR) $(PY) -m worker.main \
			> $(PID_DIR)/agent-worker.log 2>&1 & \
		echo $$! > $(WORKER_PID); \
		sleep 1; \
		if kill -0 $$(cat $(WORKER_PID)) 2>/dev/null; then \
			echo "✓ agent-worker 启动成功 (pid=$$(cat $(WORKER_PID)))"; \
			echo "  日志文件: $(PID_DIR)/agent-worker.log"; \
		else \
			echo "✗ agent-worker 启动失败，请查看日志: $(PID_DIR)/agent-worker.log"; \
			exit 1; \
		fi; \
	fi

.PHONY: up-web
up-web: setup-web
	@echo "🚀 启动用户界面 (端口 $(WEB_PORT))..."
	@echo ""
	@echo "=========================================="
	@echo "  ✨ LonelyCat 已就绪！"
	@echo "=========================================="
	@echo ""
	@echo "📱 用户界面: http://localhost:$(WEB_PORT)"
	@echo "🔧 API 文档: http://localhost:$(API_PORT)/docs"
	@echo ""
	@echo "按 Ctrl+C 停止服务"
	@echo ""
	@cd $(WEB_CONSOLE_DIR) && CORE_API_PORT=$(API_PORT) pnpm dev --host 0.0.0.0 --port $(WEB_PORT)

# -------------------------
# Stop
# -------------------------
.PHONY: down
down:
	@echo "🛑 正在停止服务..."
	@if [ -f $(API_PID) ]; then \
		PID=$$(cat $(API_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "✓ 停止 core-api (pid=$$PID)"; \
			kill $$PID || true; \
		else \
			echo "⚠️  core-api 未运行 (pid 文件已过期)"; \
		fi; \
		rm -f $(API_PID); \
	else \
		echo "⚠️  未找到 core-api pid 文件"; \
	fi
	@if [ -f $(WORKER_PID) ]; then \
		PID=$$(cat $(WORKER_PID)); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "✓ 停止 agent-worker (pid=$$PID)"; \
			kill $$PID || true; \
		else \
			echo "⚠️  agent-worker 未运行 (pid 文件已过期)"; \
		fi; \
		rm -f $(WORKER_PID); \
	else \
		echo "⚠️  未找到 agent-worker pid 文件"; \
	fi
	@echo ""
	@echo "注意: web-console 在前台运行，请在运行它的终端中按 Ctrl+C 停止"

# -------------------------
# Tests
# -------------------------
.PHONY: test
test: test-py test-web

.PHONY: test-py
test-py: test-core-api test-agent-worker
	@echo "Python tests (core-api + agent-worker) done."

.PHONY: test-core-api
test-core-api: setup-py
	@echo "Running core-api tests..."
	@env PYTHONPATH=$(PYTHONPATH):$(CORE_API_DIR) $(PY) -m pytest $(CORE_API_DIR)/tests -q

.PHONY: test-agent-worker
test-agent-worker: setup-py
	@echo "Running agent-worker tests..."
	@env PYTHONPATH=$(PYTHONPATH):$(AGENT_WORKER_DIR) $(PY) -m pytest $(AGENT_WORKER_DIR)/tests -q

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
	@echo "Cleaning venv (.venv-dev), pids, caches..."
	@rm -rf $(VENV) $(PID_DIR) .pytest_cache
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} \; 2>/dev/null || true
