.DEFAULT_GOAL := help

PY_PATHS := src tests
ATELIER_STORE ?= $(CURDIR)/.atelier
FORCE_ARG := $(if $(f),--force,)

.PHONY: help install uninstall status start service worker mcp init-runtime \
	test test-fast test-cov security-test lint format-check format typecheck verify pre-commit \
	benchmark bench-savings proof-cost-quality demo import-sessions clean

# --------------------------------------------------------------------------- #
# Lifecycle                                                                   #
# --------------------------------------------------------------------------- #

install: ## Install deps, agent CLI integrations, status helper, and runtime store
	uv sync --all-extras
	bash scripts/install_agent_clis.sh
	@mkdir -p "$(HOME)/.local/bin"
	@ln -sf "$(CURDIR)/bin/atelier-status" "$(HOME)/.local/bin/atelier-status"
	uv run atelier init || true
	@echo "[atelier] Installation complete. Run 'make status' to verify."

uninstall: ## Remove generated agent CLI integrations and status helper
	@rm -f "$(HOME)/.local/bin/atelier-status"
	@for host in claude codex opencode copilot gemini; do \
		script="scripts/uninstall_$${host}.sh"; \
		[ -f "$$script" ] && bash "$$script" || true; \
	done
	@echo "[atelier] Uninstall complete."

status: ## Show Atelier installation status
	@bash scripts/status.sh

init-runtime: ## Initialize the local Atelier store
	uv run atelier init

start: ## Start the service and frontend with Docker Compose
	docker compose up --build service frontend

service: ## Start the HTTP service on localhost:8787
	ATELIER_REQUIRE_AUTH=false uv run atelier service start

worker: ## Start background workers
	uv run atelier worker start

mcp: ## Start the MCP server over stdio JSON-RPC
	uv run atelier-mcp

# --------------------------------------------------------------------------- #
# Development                                                                 #
# --------------------------------------------------------------------------- #

test: ## Run all tests
	uv run pytest -q

test-fast: ## Run fast tests: stop on first failure, skip slow/Postgres-gated tests
	uv run pytest -q -x --ignore=tests/test_postgres_store.py --ignore=tests/test_worker_jobs.py -m "not slow"

test-cov: ## Run tests with terminal and HTML coverage reports
	uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html

security-test: ## Run security-focused test cases
	uv run pytest tests/gateway/test_security.py -v

lint: ## Run ruff lint checks
	uv run ruff check $(PY_PATHS)

format-check: ## Check black formatting
	uv run black --check $(PY_PATHS)

format: ## Auto-fix ruff issues and apply black formatting
	uv run ruff check --fix $(PY_PATHS)
	uv run black $(PY_PATHS)

typecheck: ## Run mypy strict type-checking
	uv run mypy --strict $(PY_PATHS)

verify: lint format-check typecheck test ## Verify code, runtime smoke tests, and agent integrations
	bash scripts/verify_atelier_mcp_stdio.sh
	bash scripts/verify_atelier_service.sh
	bash scripts/verify_atelier_postgres.sh
	bash scripts/verify_agent_clis.sh

pre-commit: format lint typecheck test ## Format, lint, typecheck, and test

# --------------------------------------------------------------------------- #
# Benchmarks and demos                                                        #
# --------------------------------------------------------------------------- #

benchmark: ## Run the full benchmark suite
	LOCAL=1 uv run atelier --root .atelier benchmark-full --json

bench-savings: ## Run the context-savings benchmark
	LOCAL=1 uv run python -m benchmarks.swe.savings_bench --json

proof-cost-quality: ## Run cost-quality proof gate tests and write proof-report.json
	LOCAL=1 uv run pytest tests/core/test_cost_quality_proof_gate.py tests/gateway/test_cli_proof_gate.py -v
	LOCAL=1 uv run atelier --root .atelier proof run --run-id wp32-proof --json
	@test -s .atelier/proof/proof-report.json

demo: ## Run a small blocked-plan demo in a temporary store
	@DEMO_ROOT=$$(mktemp -d); \
	uv run atelier --root "$$DEMO_ROOT" init --seed; \
	uv run atelier --root "$$DEMO_ROOT" check-plan \
		--task "Update Shopify product description" \
		--domain "beseam.shopify.publish" \
		--step "Parse product handle from the PDP URL" \
		--step "Look up product by handle" \
		--step "Update description" \
		--step "Publish" \
		--json; \
	EXIT=$$?; rm -rf "$$DEMO_ROOT"; \
	echo "exit code: $$EXIT (2=blocked, 0=pass)"; test $$EXIT -eq 2

# --------------------------------------------------------------------------- #
# Utilities                                                                   #
# --------------------------------------------------------------------------- #

import-sessions: ## Import sessions from all supported hosts: make import-sessions [f=1]
	@for host in copilot claude codex opencode; do \
		LOCAL=1 uv run atelier --root "$(ATELIER_STORE)" "$$host" import $(FORCE_ARG); \
	done

clean: ## Remove build artifacts, caches, and coverage data
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

help: ## Show this help message
	@echo "Atelier - AI reasoning/procedure/runtime layer"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@printf "%-20s %s\n" "Target" "Description"
	@printf "%-20s %s\n" "------" "-----------"
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		sed 's/:.*## /\t/' | \
		awk -F'\t' '{ printf "  %-18s %s\n", $$1, $$2 }'
