.PHONY: setup test lint format

setup:
	python -m pip install --upgrade pip
	python -m pip install -e "apps/core-api[test]" -e "apps/agent-worker[test]" -e "packages/protocol[test]"
	pnpm install

test:
	python -m pytest
	pnpm -r test

lint:
	python -m ruff check .
	pnpm -r lint

format:
	python -m ruff format .
	pnpm -r format
