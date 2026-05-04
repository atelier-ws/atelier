.PHONY: install uninstall status verify verify-install \
	test test-fast test-cov security-test \
	lint fmt format typecheck \
	verify verify-local verify-mcp \
	pre-commit \
	demo-bad-plan demo-rescue demo-rubric demo-savings demo-all \
	service worker \
	init-runtime mcp \
	swe-bench-lite-20 swe-bench-lite-100 swe-bench-verified-100 \
	swe-bench-report swe-bench-evaluate swe-bench-show-modes \
	bench-savings proof-cost-quality \
	benchmark-core benchmark-hosts benchmark-packs benchmark-full \
	clean \
	help
.PHONY: import-copilot import-claude import-codex import-opencode import-all-sessions

# --------------------------------------------------------------------------- #
# Installation                                                                #
# --------------------------------------------------------------------------- #

install: ## Install all dependencies + Atelier into agent CLIs + init runtime
	@echo "[atelier] Installing Python dependencies..."
	uv sync --all-extras
	@echo "[atelier] Installing into agent CLIs..."
	bash scripts/install_agent_clis.sh || true
	@echo "[atelier] Linking atelier-status CLI..."
	@mkdir -p $(HOME)/.local/bin
	@ln -sf $(CURDIR)/bin/atelier-status $(HOME)/.local/bin/atelier-status || true
	@echo "[atelier] Initializing runtime store..."
	uv run atelier init || true
	@echo "[atelier] Installation complete! Run 'atelier-status' to verify."

# --------------------------------------------------------------------------- #
# Testing                                                                     #
# --------------------------------------------------------------------------- #

test: ## Run all tests (pytest)
	uv run pytest -q

test-fast: ## Run tests fast: stop on first failure, skip Postgres-gated tests
	uv run pytest -q -x \
	  --ignore=tests/test_postgres_store.py \
	  --ignore=tests/test_worker_jobs.py \
	  -m "not slow"

test-cov: ## Run tests with coverage report (HTML + terminal)
	uv run pytest --cov=atelier --cov-report=term-missing --cov-report=html

security-test: ## Run security-focused test cases only
	uv run pytest tests/gateway/test_security.py -v

# --------------------------------------------------------------------------- #
# Lint / format / typecheck                                                   #
# --------------------------------------------------------------------------- #

lint: ## Run ruff linter (no auto-fix)
	uv run ruff check src tests

fmt: format ## Alias for format
format: ## Auto-fix ruff issues + apply black formatting
	uv run ruff check --fix src tests
	uv run black src tests

typecheck: ## Run mypy strict type-checking
	uv run mypy --strict src tests

# --------------------------------------------------------------------------- #
# Full verification gate                                                      #
# --------------------------------------------------------------------------- #

verify: lint format typecheck test ## Full gate: ruff + black --check + mypy strict + pytest (must pass before PR)

verify-local: ## Verify CLI against local SQLite store
	bash scripts/verify_atelier_local.sh

verify-mcp: ## Verify MCP server (stdio JSON-RPC tools/list)
	bash scripts/verify_atelier_mcp_stdio.sh

# --------------------------------------------------------------------------- #
# Agent CLI install / verify targets                                          #
# --------------------------------------------------------------------------- #

install-agent-clis: ## Install Atelier into all available agent CLIs
	bash scripts/install_agent_clis.sh

install-claude: ## Install Atelier into Claude Code (plugin + agents + skills + MCP)
	bash scripts/install_claude.sh

install-codex: ## Install Atelier into Codex CLI (skills + MCP config)
	bash scripts/install_codex.sh

install-opencode: ## Install Atelier into opencode (MCP config)
	bash scripts/install_opencode.sh

install-copilot: ## Install Atelier into VS Code Copilot (MCP + instructions)
	bash scripts/install_copilot.sh

install-gemini: ## Install Atelier into Gemini CLI (.gemini/settings.json)
	bash scripts/install_gemini.sh

verify-agent-clis: ## Verify Atelier installation across all available agent CLIs
	bash scripts/verify_agent_clis.sh

verify-claude: ## Verify Atelier installation in Claude Code (plugin list + MCP)
	bash scripts/verify_claude.sh

install-atelier-status: ## Symlink bin/atelier-status into ~/.local/bin
	@mkdir -p $(HOME)/.local/bin
	@ln -sf $(CURDIR)/bin/atelier-status $(HOME)/.local/bin/atelier-status
	@echo "[atelier] linked $(CURDIR)/bin/atelier-status → $(HOME)/.local/bin/atelier-status"
	@echo "[atelier] ensure ~/.local/bin is on your PATH, then run: atelier-status"

atelier-status: ## Run the universal Atelier status helper for the current workspace
	@bash $(CURDIR)/bin/atelier-status

uninstall: ## Uninstall Atelier from all agent CLIs and remove generated files
	@echo "[atelier] Removing symlink from ~/.local/bin..."
	@rm -f $(HOME)/.local/bin/atelier-status
	@echo "[atelier] Uninstalling from Claude Code..."
	@bash $(CURDIR)/scripts/uninstall_claude.sh || true
	@echo "[atelier] Uninstalling from Codex CLI..."
	@bash $(CURDIR)/scripts/uninstall_codex.sh || true
	@echo "[atelier] Uninstalling from opencode..."
	@bash $(CURDIR)/scripts/uninstall_opencode.sh || true
	@echo "[atelier] Uninstalling from VS Code Copilot..."
	@bash $(CURDIR)/scripts/uninstall_copilot.sh || true
	@echo "[atelier] Uninstalling from Gemini CLI..."
	@bash $(CURDIR)/scripts/uninstall_gemini.sh || true
	@echo "[atelier] Uninstall complete."

status: ## Show Atelier installation status across all agent CLIs
	@bash $(CURDIR)/scripts/status.sh

verify-install: ## Verify Atelier installation across all agent CLIs
	@echo "=== Verifying Atelier Installation ==="
	@echo ""
	@echo "Running verify-agent-clis..."
	@bash $(CURDIR)/scripts/verify_agent_clis.sh || true
	@echo ""
	@echo "Running verify-local..."
	@bash $(CURDIR)/scripts/verify_atelier_local.sh || true
	@echo ""
	@echo "Running verify-mcp..."
	@bash $(CURDIR)/scripts/verify_atelier_mcp_stdio.sh || true
	@echo ""
	@echo "=== Verification complete! ==="

# --------------------------------------------------------------------------- #
# Demo targets (use a throw-away tmp root to avoid polluting .atelier)        #
# --------------------------------------------------------------------------- #

demo-bad-plan: ## Demo: blocked plan detection
	@DEMO_ROOT=$$(mktemp -d) && \
	uv run atelier --root "$$DEMO_ROOT" init --seed && \
	uv run atelier --root "$$DEMO_ROOT" check-plan \
	  --task "Update Shopify product description" \
	  --domain "beseam.shopify.publish" \
	  --step "Parse product handle from the PDP URL" \
	  --step "Look up product by handle" \
	  --step "Update description" \
	  --step "Publish" \
	  --json; EXIT=$$?; rm -rf "$$DEMO_ROOT"; \
	echo "exit code: $$EXIT (2=blocked, 0=pass)"; test $$EXIT -eq 2

demo-rescue: ## Demo: rescue procedure for a failing pytest error
	@DEMO_ROOT=$$(mktemp -d) && \
	uv run atelier --root "$$DEMO_ROOT" init --seed && \
	uv run atelier --root "$$DEMO_ROOT" rescue \
	  --task "fix failing pytest" \
	  --error "AssertionError: expected 200 got 500" \
	  --domain "beseam.testing" \
	  --json && \
	rm -rf "$$DEMO_ROOT"

demo-rubric: ## Demo: rubric gate with all 8 Shopify publish checks passing
	@DEMO_ROOT=$$(mktemp -d) && \
	uv run atelier --root "$$DEMO_ROOT" init --seed && \
	echo '{"product_identity_uses_gid": true, "pre_publish_snapshot_exists": true, "write_result_checked": true, "post_publish_refetch_done": true, "post_publish_audit_passed": true, "rollback_available": true, "localized_url_test_passed": true, "changed_handle_test_passed": true}' | \
	uv run atelier --root "$$DEMO_ROOT" run-rubric rubric_shopify_publish --input - --json && \
	rm -rf "$$DEMO_ROOT"

demo-savings: ## Demo: token + call savings summary
	@DEMO_ROOT=$$(mktemp -d) && \
	uv run atelier --root "$$DEMO_ROOT" init && \
	uv run atelier --root "$$DEMO_ROOT" savings && \
	rm -rf "$$DEMO_ROOT"

demo-all: demo-bad-plan demo-rescue demo-rubric demo-savings ## Run all demos in sequence

# --------------------------------------------------------------------------- #
# SWE-bench harness                                                           #
# --------------------------------------------------------------------------- #

swe-bench-lite-20: ## Run the 20-task mock SWE-bench harness (offline, no API keys)
	uv run atelier-bench swe run --config benchmarks/swe/configs/lite_20.yaml

swe-bench-lite-100: ## Run the 100-task SWE-bench Lite harness
	uv run atelier-bench swe run --config benchmarks/swe/configs/lite_100.yaml

swe-bench-verified-100: ## Run the 100-task SWE-bench Verified harness
	uv run atelier-bench swe run --config benchmarks/swe/configs/verified_100.yaml

swe-bench-report: ## Re-render report from a run dir: make swe-bench-report DIR=<path>
	@if [ -z "$(DIR)" ]; then echo "usage: make swe-bench-report DIR=<run dir>"; exit 64; fi
	uv run atelier-bench swe report --run-dir "$(DIR)"

swe-bench-evaluate: ## Score predictions in a run dir: make swe-bench-evaluate DIR=<path> [MOCK=1]
	@if [ -z "$(DIR)" ]; then echo "usage: make swe-bench-evaluate DIR=<run dir> [MOCK=1]"; exit 64; fi
	uv run atelier-bench swe evaluate --run-dir "$(DIR)" $(if $(MOCK),--mock,)

swe-bench-show-modes: ## Print the harness mode matrix
	uv run atelier-bench swe show-modes

bench-savings: ## WP-19: run 11-prompt context-savings benchmark (must be ≥50%)
	@LOCAL=1 uv run python -m benchmarks.swe.savings_bench --json

proof-cost-quality: ## WP-32: run cost-quality proof gate tests and generate proof-report.json
	LOCAL=1 uv run pytest tests/core/test_cost_quality_proof_gate.py \
	                     tests/gateway/test_cli_proof_gate.py -v
	LOCAL=1 uv run atelier --root .atelier proof run --run-id wp32-proof --json
	@test -s .atelier/proof/proof-report.json && echo "[proof] proof-report.json written" || (echo "[proof] ERROR: proof-report.json is empty or missing" && exit 1)
	@LOCAL=1 uv run python -c "import json; r=json.load(open('.atelier/proof/proof-report.json')); assert r['status'] in ('pass', 'fail'), f'unexpected status: {r[\"status\"]}'; print(f'[proof] status={r[\"status\"]}')"

# --------------------------------------------------------------------------- #
# Phase T benchmark suite                                                     #
# --------------------------------------------------------------------------- #

benchmark-core: ## Phase T3 core benchmark (runtime baseline vs cached rounds)
	LOCAL=1 uv run atelier --root .atelier benchmark-core --json

benchmark-hosts: ## Phase T3 host benchmark/verification suite
	LOCAL=1 uv run atelier --root .atelier benchmark-hosts --json

benchmark-packs: ## Phase T3 pack benchmark suite
	LOCAL=1 uv run atelier --root .atelier benchmark-packs --json

benchmark-full: ## Phase T3 full benchmark suite (core + hosts + packs)
	LOCAL=1 uv run atelier --root .atelier benchmark-full --json

# --------------------------------------------------------------------------- #
# Service / worker                                                            #
# --------------------------------------------------------------------------- #

service: ## Start HTTP service on localhost:8787 (requires: ATELIER_REQUIRE_AUTH=false)
	ATELIER_REQUIRE_AUTH=false uv run atelier service start

worker: ## Start background workers
	uv run atelier worker start

# --------------------------------------------------------------------------- #
# Utilities                                                                   #
# --------------------------------------------------------------------------- #

init-runtime: ## Initialize Atelier store (uv run atelier init)
	uv run atelier init

mcp: ## Start MCP server (stdio JSON-RPC — used by agent hosts)
	uv run atelier-mcp

pre-commit: format lint typecheck test ## Pre-commit hook: format + lint + typecheck + test

clean: ## Remove all build artifacts, caches, and coverage data
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

# Atelier session importers
# Usage: make import-copilot              (use default ~/.copilot/session-state/)
#        make import-copilot p=<path>     (override source path)
#        make import-copilot f=1        (force re-import all sessions)
ATELIER_STORE ?= $(CURDIR)/.atelier
FRC ?= $(if $(f),--force,)

import-copilot:
	LOCAL=1 uv run atelier --root $(ATELIER_STORE) copilot import $(if $(p),--path $(p),) $(FRC)

import-claude:
	LOCAL=1 uv run atelier --root $(ATELIER_STORE) claude import $(if $(p),--path $(p),) $(FRC)

import-codex:
	LOCAL=1 uv run atelier --root $(ATELIER_STORE) codex import $(if $(p),--path $(p),) $(FRC)

import-opencode:
	LOCAL=1 uv run atelier --root $(ATELIER_STORE) opencode import $(if $(p),--path $(p),) $(FRC)

import-all-sessions:
	@$(MAKE) --no-print-directory import-copilot  $(if $(f),f=1,)
	@$(MAKE) --no-print-directory import-claude  $(if $(f),f=1,)
	@$(MAKE) --no-print-directory import-codex  $(if $(f),f=1,)
	@$(MAKE) --no-print-directory import-opencode  $(if $(f),f=1,)

help: ## Show this help message
	@echo "Atelier — AI reasoning/procedure/runtime layer"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@printf "%-28s %s\n" "Target" "Description"
	@printf "%-28s %s\n" "------" "-----------"
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		grep -v '^fmt:' | \
		sed 's/:.*## /\t/' | \
		awk -F'\t' '{ printf "  %-26s %s\n", $$1, $$2 }'
