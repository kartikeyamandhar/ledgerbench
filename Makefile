# LedgerBench developer tasks. `make check` is the single gate run locally and in CI.
.DEFAULT_GOAL := help

VENV := agentic_flow
PY   := $(VENV)/bin/python
PIP  := $(PY) -m pip

.PHONY: help venv install fmt fmt-check lint type test cov check demo smoke build clean

help: ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtual environment (Python 3.11).
	python3.11 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: ## Install the package with dev extras (editable).
	$(PIP) install -e ".[dev]"

fmt: ## Format code with ruff.
	$(PY) -m ruff format .

fmt-check: ## Check formatting without writing changes.
	$(PY) -m ruff format --check .

lint: ## Lint with ruff.
	$(PY) -m ruff check .

type: ## Type-check src with mypy (strict).
	$(PY) -m mypy

test: ## Run tests (no coverage gate).
	$(PY) -m pytest

cov: ## Run tests with coverage and enforce gates.
	$(PY) -m pytest --cov=ledgerbench --cov-branch --cov-report=term-missing

check: fmt-check lint type cov ## Format check + lint + type + tests with coverage. The merge gate.

demo: ## Full offline demo run (implemented in Phase 6).
	@echo "ledgerbench demo lands in Phase 6."

smoke: ## 10-item offline eval (implemented in Phase 4).
	@echo "ledgerbench smoke lands in Phase 4."

build: ## Build sdist + wheel.
	$(PY) -m build

clean: ## Remove build, cache, and coverage artifacts.
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -not -path './$(VENV)/*' -exec rm -rf {} +
