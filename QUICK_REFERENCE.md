# Atelier Quick Reference Card

**For developers.** Print this page. Keep it nearby while coding with Atelier.

*For agents/automation, see [AGENT_README.md](AGENT_README.md) instead.*

---

## 🎯 Quick Decisions

**What should I do right now?**

- **Starting a coding task?** → Use `/atelier:atelier-task` or pick `atelier:code` agent
- **Before editing code?** → Use `/atelier:atelier-check-plan` (must pass before you edit)
- **Same error failed 2+ times?** → Use `/atelier:atelier-rescue`
- **Done with the task?** → Use `/atelier:atelier-record-trace`
- **Just reading code?** → Use `atelier:explore` agent (read-only)
- **Reviewing someone's PR?** → Use `atelier:review` agent (no editing)

---

## 🚀 Skills (Claude Code `/atelier:` commands)

**What are skills?** Slash commands in Claude Code that invoke Atelier operations.

```
Core Loop
─────────────────────────────────────────────────
/atelier:atelier-task        Run full standing loop: context → plan → check → implement → rescue → rubric → record
/atelier:atelier-check-plan  Validate plan against dead-ends (blocks until ✅ ok)
/atelier:atelier-rescue      Get recovery when same error fails 2x
/atelier:atelier-record-trace Record outcome (files, commands, errors, results)

Intelligence
─────────────────────────────────────────────────
/atelier:status [run_id]     Show current run's plan, facts, blockers, alerts
/atelier:context <domain>    Show domain rules, forbidden phrases, procedures
/atelier:analyze-failures    Cluster repeated failures; propose new blocks/rubrics
/atelier:evals [list|run|promote] Manage test cases

Operations
─────────────────────────────────────────────────
/atelier:benchmark [--apply] Run eval suite (dry-run or apply)
/atelier:savings             Show cost/token savings
/atelier:settings [off|shadow|on] Control smart-tool mode
```

**The 11 skills, grouped by use case:**

### Core Skills (use in order)
- `/atelier:atelier-task` — Start here. Runs full loop: get context → plan → check → implement → rescue → verify → record
- `/atelier:atelier-check-plan` — Validate your plan BEFORE editing code (blocks until ✅ pass)
- `/atelier:atelier-rescue` — Stuck on same error? Get recovery procedure
- `/atelier:atelier-record-trace` — Done? Record what happened for learning

### Intelligence Skills (as needed)
- `/atelier:status [run_id]` — See your current run: plan, facts, blockers, alerts
- `/atelier:context <domain>` — Get domain rules, forbidden patterns, key procedures
- `/atelier:analyze-failures` — Find repeated failures, propose mitigations
- `/atelier:evals` — Manage test cases (list, run, promote)

### Operations Skills (occasional use)
- `/atelier:benchmark` — Run eval suite to measure your learning loop
- `/atelier:savings` — See cost/token savings from using Atelier
- `/atelier:settings` — Toggle smart-tool mode (off|shadow|on)

---

## 👥 Agents (Claude Code `/agents` panel)

**What are agents?** Pre-configured AI personas that follow Atelier workflows automatically.

```
atelier:code       Main coding agent
├─ Loop: get_context → plan → check_plan → implement → rescue → rubric → record
├─ Tools: All (editing + MCP + shell)
└─ Hard rules: No secrets, no skipping check_plan, no plan contradictions

atelier:explore    Read-only investigator
├─ Use: Find symbol usage, summarize modules, fetch blocks
├─ Tools: Read, Grep, Glob, get_reasoning_context
└─ Hard rules: Never edit, never mutate state

atelier:review     Verifier/gatekeeper
├─ Use: Review patches before merge, catch dead ends
├─ Tools: get_reasoning_context, check_plan, run_rubric_gate + read-only
└─ Hard rules: Never edit, never approve "block" verdicts

atelier:repair     Repair specialist (on repeated failures)
├─ Trigger: Same error fails 2x OR monitor alert
├─ Tools: All (code + MCP + shell)
└─ Hard rules: No repeated hypotheses, stop after 2 failures
```

## 🔧 MCP Tools (14 total)

```
CORE WORKFLOW (5)
─────────────────────────────────────────────────
get_reasoning_context      Fetch ReasonBlocks for task
check_plan                 Validate plan against dead-ends
rescue_failure             Get recovery procedure
record_trace               Save outcome for learning
run_rubric_gate            Verify high-risk domain before success

EXTENDED (9)
─────────────────────────────────────────────────
extract_reasonblock        Create candidate block from trace
get_run_ledger             Pull active run's full ledger
update_run_ledger          Update ledger with hypothesis/test/blocker
monitor_event              Record alert (Thrashing, SecondGuessing, etc.)
compress_context           Summarize ledger for long tasks
get_environment_context    Fetch domain rules + forbidden phrases
smart_read                 Cached file reading (shadow mode tracks savings)
smart_search               Memoized code search
cached_grep                Grep with smart caching
```

## 🎯 High-Risk Domains (require rubric gate)

```
Domain                              Rubric ID                      Example
──────────────────────────────────  ─────────────────────────────  ─────────────────────────
beseam.shopify.publish             rubric_shopify_publish         Publishing to Shopify
beseam.pdp.schema                  rubric_pdp_schema              Schema changes
beseam.catalog.fix                 rubric_catalog_fix             Catalog data fixes
beseam.tracker.classification      rubric_ai_referral_classification AI referral changes

RUBRIC CHECKS (examples)
─────────────────────────────────────────────────
shopify_publish:  auth ✓ product_gid ✓ idempotence ✓ variant_mapping ✓
pdp_schema:       migration ✓ backward_compat ✓ test_coverage ✓
catalog_fix:      data_integrity ✓ ingest_record ✓ pdp_consistency ✓
ai_referral:      accuracy ✓ event_routing ✓ schema ✓
```

## 📦 Seed ReasonBlocks (10 hand-written)

```
ID  Title                              Domain
──  ──────────────────────────────────  ──────────────────────────
01  Shopify Product GID Management      beseam.shopify.publish
02  Idempotent Publish Pattern          beseam.shopify.publish
03  Post-Publish Verification           beseam.shopify.publish
04  Service Change Audit                beseam.pdp.schema
05  AI Referral Classification          beseam.tracker.classification
06  Catalog Truth First                 beseam.catalog.fix
07  Transaction Rollback Safety         backend.*
08  Cache Invalidation Strategy         backend.*
09  Repeated Failure Recovery           (cross-domain)
10  Monitoring & Alerting               (cross-domain)
```

## 🎮 CLI Commands

```
atelier get-reasoning-context --task "..." --domain beseam.shopify.publish --files src/...
atelier check-plan --task "..." --plan "step 1" "step 2" --domain ...
atelier rescue-failure --task "..." --error "..." --files ... --recent-actions "tried X" "tried Y"
atelier record-trace --agent atelier:code --domain ... --status success --files-touched [...]
atelier run-rubric-gate --rubric-id rubric_shopify_publish --checks '{"check_1": true, ...}'
atelier list-reasonblocks --domain beseam.shopify.publish
atelier eval list
atelier eval run <case_id>
atelier benchmark --apply
atelier analyze-failures
atelier savings
atelier tool-mode set shadow
```

## 📊 Run Ledger (Session State)

```
.atelier/runs/<run_id>.json contains:
─────────────────────────────────────────────────
run_id                  Unique run identifier
agent                   "atelier:code" | "atelier:repair" | ...
task                    One-sentence task description
domain                  beseam.shopify.publish | ... | null
status                  in_progress | success | failed | partial
current_plan            Array of 3–8 imperative steps
verified_facts          Facts established during run
open_questions          Questions still unanswered
current_blockers        Blocking issues
hypotheses_tried        Tested theories (with results)
hypotheses_rejected     Theories that failed (with reasons)
active_reasonblocks     [block_id, ...] from matched ReasonBlocks
tool_calls              [{name, timestamp, result}, ...]
monitor_alerts          [{type, severity, message}, ...]
```

## 🧪 Testing & Validation

```
make verify                    # All: ruff + black + mypy + pytest
make verify-mcp                # MCP stdio smoke test (5 tools)
make verify-plugins            # Claude plugin JSON validation
make verify-claude             # Full Claude Code install check
make verify-service            # Service health + API
make verify-postgres           # Postgres storage (if DATABASE_URL set)
make verify-agent-clis         # All installed CLI hosts

uv run pytest tests/test_golden_fixtures.py -v    # Golden end-to-end cases
```

## 🔍 Smart Tool Modes

```
off         Native tools only; no metrics
shadow      Tools run normally; metrics recorded (calls_avoided, tokens_saved, cache_hits)
on          Tools may return cached results; token budget truncation applied

Toggle: /atelier:settings [off | shadow | on]
```

## 📈 Key Metrics (via `/atelier:savings`)

```
calls_avoided              Network calls saved by caching
tokens_saved               Tokens saved by truncation/memoization
bad_plans_blocked          Plans rejected by check_plan
rescue_events              Failures recovered via rescue_failure
rubric_failures_caught     Pre-success checks that failed
```

## 📚 Documentation Structure

```
AGENT_README.md (684 lines)
├─ Sections 1–10: Original Atelier design + workflows + installation
├─ Section 11: MCP Tools (14 total) + availability matrix
├─ Section 12: Atelier Skills (11 total) + invocation syntax
├─ Section 13: Agents (4) + roles + loops + hard rules
├─ Section 14: CLI Commands (30+)
├─ Section 15: Environment Contexts (domains + rubrics)
├─ Section 16: Seed ReasonBlocks (10 blocks)
├─ Section 17: Rubrics (6 gates)
├─ Section 18: Run Ledger (JSON schema)
├─ Section 19: Smart Tools (shadow mode)
├─ Section 20: Testing & Validation
└─ Section 21: Module Inventory (13 key files)

👉 Start here for ANY Atelier question!
```

## 🚨 Hard Rules (Never Break These)

```
DO NOT:
❌ Skip atelier_check_plan before editing code
❌ Ignore high-severity Atelier warnings
❌ Invent plan steps that contradict ReasonBlocks
❌ Store secrets, API keys, tokens in traces
❌ Call record_trace without observable facts
❌ Edit code after review agent reports "block"
❌ Approve a rubric_gate "block" verdict
❌ Re-propose same hypothesis twice in repair
❌ Loop more than 2 times on rescue failures
```

## 📞 Quick Decisions

```
Q: I'm starting a coding task
A: Use /atelier:atelier-task OR atelier:code agent

Q: My plan might be invalid
A: Use /atelier:atelier-check-plan (blocks until ✅ ok)

Q: Same error just failed twice
A: Use /atelier:atelier-rescue

Q: I'm done with the task
A: Use /atelier:atelier-record-trace

Q: I need to review someone's patch
A: Use atelier:review agent

Q: I need to investigate code without editing
A: Use atelier:explore agent

Q: My task keeps failing the same way
A: Activate atelier:repair agent

Q: I want to see the current run status
A: Use /atelier:status

Q: I want domain-specific rules
A: Use /atelier:context <domain>
```

---

**Last Updated:** 2026-05-01  
**Version:** Atelier v0.1.0 (MCP v2024-11-05)  
**File:** `/home/pankaj/Projects/leanchain/e-commerce/atelier/ATELIER_QUICK_REFERENCE.md`
