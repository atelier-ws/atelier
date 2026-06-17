.DEFAULT_GOAL := help

PY_PATHS := src benchmarks tests scripts integrations
MYPY_PATHS := src/atelier
ATELIER_STORE ?= $(HOME)/.atelier
ATELIER_CMD ?= uv run atelier
TEST_PRINT_TIME ?= 0
# Coverage floor for the full slow-inclusive suite (make test-full / nightly-coverage.yml).
# Conservative provisional floor pending first-CI calibration (see 22-01-SUMMARY.md):
# local measurement could not complete the full suite (slow-service + xdist tree-sitter
# limitations); a partial subset run measured 68% (a strict lower bound). Calibrate to
# ~2 points below the first nightly run's reported total.
COV_FAIL_UNDER ?= 66
FORCE_ARG := $(if $(f),--force,)
EXTERNAL_PERIODS ?= today week month
.PHONY: help install uninstall dev build release/build prod status start restart build-host-skills sync-agent-context \
	check-agent-context docs-check worktree-env runtime-evidence \
	test test-fast test-cov test-full lint format-check format typecheck launch-gate verify pre-commit \
	proof-cost-quality demo import clean \
	_ensure_hooks

# --------------------------------------------------------------------------- #
# Lifecycle                                                                   #
# --------------------------------------------------------------------------- #

#    * To do a clean development install (editable mode):
#         make dev
#    * To build and install a local production binary:
#         make prod

dev: ## Install Atelier in editable/dev mode
	bash scripts/local.sh

build: ## Build and package for production distribution
	bash scripts/build.sh

release/build: build ## Alias for build release jobs

# Dirs stripped from the public mirror (private/dev-only content).
MIRROR_STRIP ?= docs-internal internal .planning .lessons .agent .knowledge .ruler reports

mirror: ## Mirror current tag to public atelier repo (strips private dirs)
	@TAG=$$(git describe --tags --exact-match 2>/dev/null) \
	  || { echo "Error: not on an exact tag. Run: git tag vX.Y.Z && make mirror"; exit 1; }
	@echo "Mirroring $$TAG → atelier-ws/atelier (stripping private dirs)..."
	@TMPDIR=$$(mktemp -d) && trap "rm -rf $$TMPDIR" EXIT && \
	  git archive HEAD | tar -x -C $$TMPDIR && \
	  for d in $(MIRROR_STRIP); do rm -rf "$$TMPDIR/$$d"; done && \
	  cd $$TMPDIR && \
	  git init -b main >/dev/null && \
	  git add -A && \
	  git commit -q -m "Release $$TAG" && \
	  git tag $$TAG && \
	  git remote add origin https://github.com/atelier-ws/atelier.git && \
	  git push origin main --force -q && \
	  git push origin $$TAG --force -q && \
	  echo "✓ Mirrored $$TAG to atelier-ws/atelier"

prod: ## Build and install from local production build (includes mypyc compilation; expects ~2-3 min build time)
	bash scripts/build.sh
	# Run the local installer: copies bundle/ → ~/.local/ and sets up host integrations,
	# exactly mirroring the remote path (download → extract → bundle.sh).
	bash scripts/install.sh --local

uninstall: ## Remove all Atelier agent-host integrations, hooks, and bin wrappers
	@bash scripts/uninstall.sh $${ARGS:-}

status: ## Show Atelier installation status
	@bash scripts/status.sh

start: ## Start the service and frontend natively
	@if [ -f .env.worktree ]; then set -a; . ./.env.worktree; set +a; fi; \
	$(ATELIER_CMD) --root "$${ATELIER_STACK_ROOT:-$(ATELIER_STORE)}" stack start
	@if [ -f .env.worktree ]; then set -a; . ./.env.worktree; set +a; fi; \
	$(ATELIER_CMD) --root "$${ATELIER_STACK_ROOT:-$(ATELIER_STORE)}" stack logs -f
restart: ## Restart the service and frontend natively
	@if [ -f .env.worktree ]; then set -a; . ./.env.worktree; set +a; fi; \
	$(ATELIER_CMD) --root "$${ATELIER_STACK_ROOT:-$(ATELIER_STORE)}" stack stop --force || true
	@if [ -f .env.worktree ]; then set -a; . ./.env.worktree; set +a; fi; \
	$(ATELIER_CMD) --root "$${ATELIER_STACK_ROOT:-$(ATELIER_STORE)}" stack start
	@if [ -f .env.worktree ]; then set -a; . ./.env.worktree; set +a; fi; \
	$(ATELIER_CMD) --root "$${ATELIER_STACK_ROOT:-$(ATELIER_STORE)}" stack logs -f

# --------------------------------------------------------------------------- #
# Development                                                                 #
# --------------------------------------------------------------------------- #

build-host-skills: ## Generate Codex/Gemini skill bundles from integrations/skills (set ATELIER_DEV_MODE=1 to include dev-only skills)
	@bash scripts/build_host_skills.sh --host all $$( [ "$${ATELIER_DEV_MODE:-0}" = "1" ] && echo --include-dev )

sync-agent-context: ## Regenerate host instruction surfaces from integrations/shared/
	uv run python scripts/sync_agent_context.py

check-agent-context: ## Verify generated host instruction surfaces are up to date
	uv run python scripts/sync_agent_context.py --check

docs-check: check-agent-context ## Run docs and repo-governance checks
	uv run pytest tests/gateway/test_docs.py tests/gateway/test_generated_agent_contexts.py -q

worktree-env: ## Write a per-worktree .env file for local stack bootstraps
	uv run python scripts/worktree_env.py --env-file .env.worktree --json

runtime-evidence: ## Capture runtime evidence from a local Atelier stack
	uv run python scripts/runtime_evidence.py

# Auto-configure git hooks path so .githooks/pre-commit runs on every commit.
# Developers never need to run `git config core.hooksPath .githooks` by hand.
_ensure_hooks:
	@current=$$(git config core.hooksPath 2>/dev/null || echo ""); \
	if [ "$$current" != ".githooks" ]; then \
		git config core.hooksPath .githooks; \
		echo "  → Configured git hooks path → .githooks"; \
	fi

test: | _ensure_hooks ## Run all tests
ifeq ($(TEST_PRINT_TIME),1)
	@time bash -lc 'if uv run python -c "import xdist" >/dev/null 2>&1; then uv run pytest -q -ra --durations=0 -n auto --dist=worksteal; else uv run pytest -q -ra --durations=0; fi'
else
	@bash -lc 'if uv run python -c "import xdist" >/dev/null 2>&1; then uv run pytest -q -ra --durations=0 -n auto --dist=worksteal; else uv run pytest -q -ra --durations=0; fi'
endif

test-fast: | _ensure_hooks ## Run fast tests: stop on first failure, skip slow/Postgres-gated tests
	@bash -lc 'if uv run python -c "import xdist" >/dev/null 2>&1; then uv run pytest -q -x -n auto --dist=worksteal --ignore=tests/test_postgres_store.py --ignore=tests/test_worker_jobs.py -m "not slow"; else uv run pytest -q -x --ignore=tests/test_postgres_store.py --ignore=tests/test_worker_jobs.py -m "not slow"; fi'

test-cov: ## Run tests with terminal and HTML coverage reports
	uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html

test-full: ## Run the FULL suite (incl. slow) with measured coverage floor
	uv run pytest -m "" --timeout=300 --cov=atelier --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER)

lint: | _ensure_hooks ## Run ruff lint checks
	uv run ruff check $(PY_PATHS)

format-check: ## Check Python formatting without rewriting files
	uv run black --check src tests

format: | _ensure_hooks ## Format all code: Python (ruff+black) and frontend (prettier if available)
	uv run ruff check --fix $(PY_PATHS)
	uv run black src tests
	@if [ -d "frontend" ]; then \
		if [ -f "frontend/package.json" ] && grep -q "prettier" frontend/package.json 2>/dev/null; then \
			cd frontend && npx prettier --write "src/**/*.{ts,tsx,js,jsx,json,css,md}" 2>/dev/null || true; \
		fi; \
	fi

typecheck: | _ensure_hooks ## Run mypy strict type-checking
	uv run mypy --explicit-package-bases $(MYPY_PATHS)

launch-gate: ## Run pre-launch policy gate (set mode with LAUNCH_GATE_MODE=shadow|suggest|enforce)
	bash scripts/launch_gate.sh --mode $${LAUNCH_GATE_MODE:-enforce}

verify: | _ensure_hooks lint format-check typecheck docs-check test ## Verify code, docs, runtime smoke tests, and agent integrations
	bash scripts/verify_atelier_service.sh
	bash scripts/verify_atelier_postgres.sh
	bash scripts/verify_agent_clis.sh

proof-cost-quality: ## Run cost-quality proof gate tests and write proof-report.json
	LOCAL=1 uv run pytest tests/core/test_cost_quality_proof_gate.py tests/gateway/test_cli_proof_gate.py -v
	LOCAL=1 uv run atelier proof run --session-id wp32-proof --context-reduction-pct 60 --json
	@test -s $(ATELIER_STORE)/proof/proof-report.json

# --------------------------------------------------------------------------- #
# Utilities                                                                   #
# --------------------------------------------------------------------------- #

import: ## Import sessions and external tool snapshots: make import [f=1]
	LOCAL=1 $(ATELIER_CMD) --root "$(ATELIER_STORE)" import $(FORCE_ARG)
	@for period in $(EXTERNAL_PERIODS); do \
		LOCAL=1 $(ATELIER_CMD) --root "$(ATELIER_STORE)" external-report --tool all --period "$$period" --persist || true; \
	done

flow-dump: ## Extract chat from a .flow file or directory: make flow-dump path=/path/to/file_or_dir
	@if [ -z "$(path)" ]; then \
		echo "Error: 'path' argument is required. Usage: make flow-dump path=/path/to/file_or_dir"; \
		exit 1; \
	fi
	uv run --project benchmarks python scripts/extract_flow.py $(path)

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
