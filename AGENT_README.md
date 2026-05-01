# Atelier — Agent Reasoning Runtime

**For agents by agents.** This document is structured for automated consumption, not human reading.

---

## ⚡ AGENT QUICK-START

**DECISION TREE: Which agent are you?**

```
Are you editing code?
├─ YES → Use atelier:code
│        First: call atelier_get_reasoning_context
│        Then: draft plan
│        Then: call atelier_check_plan (MUST PASS before editing)
│        Then: edit code
│        Then: if 2+ failures → call atelier_rescue_failure
│        Finally: call atelier_record_trace
│
├─ NO, just reading/exploring?
│  └─ Use atelier:explore
│     - Call atelier_get_reasoning_context only
│     - Read files, grep, search
│     - Never edit, never mutate
│
├─ NO, I'm reviewing a patch?
│  └─ Use atelier:review
│     - Call atelier_get_reasoning_context
│     - Call atelier_check_plan on the patch
│     - Call atelier_run_rubric_gate for high-risk domains
│     - Report verdict: pass | warn | block
│
└─ NO, same error failed 2+ times?
   └─ Use atelier:repair
      - Call atelier_get_run_ledger
      - Call atelier_rescue_failure
      - Apply patch
      - Re-run test
      - Call atelier_record_trace
```

---

## 🎯 AGENT WORKFLOWS (Copy-Paste Ready)

### atelier:code (Main Coding Agent)

```
1. call atelier_get_reasoning_context({
     task: "one-sentence task",
     domain: "beseam.shopify.publish" | null,
     files: ["src/..."],
     errors: []
   })
   → Read returned ReasonBlocks

2. Draft plan: 3-8 imperative steps

3. call atelier_check_plan({
     task: same,
     plan: [...],
     domain: same,
     files: [...],
     tools: [...]
   })
   → IF status == "blocked": use suggested_plan, re-check
   → IF status == "warn": address warnings
   → IF status == "ok": proceed

4. Edit code (aligned with validated plan)

5. IF test/command fails same way twice:
   call atelier_rescue_failure({
     task: same,
     error: "error message (redacted)",
     files: [...],
     recent_actions: ["tried X", "tried Y"]
   })
   → Apply rescue before retrying

6. IF domain in [beseam.shopify.publish, beseam.pdp.schema, 
                 beseam.catalog.fix, beseam.tracker.classification]:
   call atelier_run_rubric_gate({
     rubric_id: "rubric_shopify_publish" | ...,
     checks: {
       "check_name_1": true,
       "check_name_2": false,
       "check_name_3": null
     }
   })
   → MUST have status != "blocked"

7. call atelier_record_trace({
     agent: "atelier:code",
     domain: same | null,
     task: same,
     status: "success" | "failed" | "partial",
     files_touched: [...],
     tools_called: [{name, count}, ...],
     commands_run: [...],
     errors_seen: [...],
     diff_summary: "one sentence",
     output_summary: "one sentence",
     validation_results: [{name, passed, detail}, ...]
   })
```

### atelier:explore (Read-Only Investigator)

```
1. call atelier_get_reasoning_context({
     task: "...",
     domain: "...",
     files: ["..."],
     errors: []
   })

2. Read files, grep, glob

3. DO NOT:
   - Edit files
   - Run mutations (git commit, rm, npm install)
   - Call record_trace or extract_reasonblock

4. Return tight summary (~30 lines):
   - Matched ReasonBlock ids
   - File/line citations
   - Key findings
```

### atelier:review (Verifier/Gatekeeper)

```
1. call atelier_get_reasoning_context({
     task: "review patch for X",
     files: [changed_files],
     domain: "beseam.shopify.publish" | ...
   })

2. Identify dead-end overlaps

3. call atelier_check_plan({
     task: "implement the diff",
     plan: [implied_steps_from_diff],
     domain: same,
     files: [changed_files]
   })
   → IF blocked: STOP, report verdict: block

4. IF high-risk domain:
   call atelier_run_rubric_gate({
     rubric_id: ...,
     checks: {...}
   })
   → IF status == "blocked": STOP, report verdict: block

5. Return verdict:
   {
     verdict: "pass" | "warn" | "block",
     findings: [...],
     required_actions: [...]
   }

DO NOT:
  - Edit code
  - Call record_trace
  - Approve "block" verdicts
```

### atelier:repair (Repair Specialist)

```
1. call atelier_get_run_ledger({run_id: "" | "specific_id"})
   → Extract: current_plan, verified_facts, hypotheses_tried, 
              hypotheses_rejected, errors

2. Form ONE new hypothesis not in hypotheses_tried or rejected

3. call atelier_rescue_failure({
     task: same,
     error: "error signature (redacted)",
     files: [...],
     recent_actions: [...]
   })
   → Read matched ReasonBlocks

4. Apply smallest patch addressing rescue

5. Re-run failing test/command

6. IF still fails same way:
   call atelier_update_run_ledger({
     run_id: same,
     add_hypothesis: {
       hypothesis: "...",
       rejected: true,
       reason: "..."
     }
   })
   → STOP after 2 rejections

7. call atelier_record_trace({
     agent: "atelier:repair",
     domain: same,
     task: same,
     status: "success" | "failed" | "partial",
     files_touched: [...],
     ...
   })

DO NOT:
  - Call record_trace without observable facts
  - Propose same hypothesis twice
  - Loop more than 2 times
  - Skip get_run_ledger
```

---

## 🔧 MCP TOOLS (Machine-Readable Reference)

### CORE WORKFLOW (5 Tools)

```json
{
  "core_tools": [
    {
      "name": "atelier_get_reasoning_context",
      "input": {
        "task": "string (required)",
        "domain": "string (optional)",
        "files": ["string"],
        "errors": ["string"],
        "tools": ["string"],
        "max_blocks": "integer (default: 5)"
      },
      "output": {
        "context": "markdown ReasonBlocks"
      },
      "use_when": "Starting any task, before planning"
    },
    {
      "name": "atelier_check_plan",
      "input": {
        "task": "string (required)",
        "plan": ["string"] (required, 3-8 steps)",
        "domain": "string (optional)",
        "files": ["string"],
        "tools": ["string"],
        "errors": ["string"]
      },
      "output": {
        "status": "ok | warn | blocked",
        "matched_blocks": ["block_id"],
        "suggested_plan": ["string"],
        "warnings": ["string"]
      },
      "exit_codes": {
        "0": "status ok or warn",
        "2": "status blocked — DO NOT PROCEED"
      },
      "use_when": "Before editing code, after drafting plan"
    },
    {
      "name": "atelier_rescue_failure",
      "input": {
        "task": "string (required)",
        "error": "string (required, redacted)",
        "files": ["string"],
        "domain": "string (optional)",
        "recent_actions": ["string"]
      },
      "output": {
        "rescue": "procedure string",
        "matched_blocks": ["block_id"]
      },
      "use_when": "Same error fails 2+ times"
    },
    {
      "name": "atelier_record_trace",
      "input": {
        "agent": "string (required: atelier:code|explore|review|repair)",
        "domain": "string (optional)",
        "task": "string (required)",
        "status": "string (required: success|failed|partial)",
        "files_touched": ["string"],
        "tools_called": [{"name": "string", "count": "int"}],
        "commands_run": ["string"],
        "errors_seen": ["string (redacted)"],
        "diff_summary": "string",
        "output_summary": "string",
        "validation_results": [
          {"name": "string", "passed": "bool", "detail": "string"}
        ]
      },
      "output": {
        "id": "trace_id",
        "run_id": "run_id"
      },
      "use_when": "Task complete, failed, or partial"
    },
    {
      "name": "atelier_run_rubric_gate",
      "input": {
        "rubric_id": "string (required)",
        "checks": {
          "check_name_1": true,
          "check_name_2": false,
          "check_name_3": null
        }
      },
      "output": {
        "status": "pass | fail | blocked",
        "failures": ["check_name"]
      },
      "exit_codes": {
        "0": "status pass",
        "1": "status fail",
        "2": "status blocked"
      },
      "use_when": "Before marking success on high-risk domains"
    }
  ]
}
```

### EXTENDED TOOLS (9 Tools)

```json
{
  "extended_tools": [
    {
      "name": "atelier_get_run_ledger",
      "input": {"run_id": "string (optional)"},
      "output": {"ledger": {"run_id", "task", "plan", "verified_facts", "hypotheses_tried", "hypotheses_rejected", "blockers", "errors"}}
    },
    {
      "name": "atelier_update_run_ledger",
      "input": {
        "run_id": "string",
        "set_plan": ["string"],
        "add_hypothesis": {"hypothesis": "string", "rejected": "bool", "reason": "string"},
        "record_test": {"name": "string", "passed": "bool", "output": "string"},
        "set_blocker": "string"
      },
      "output": {"updated": "bool"}
    },
    {
      "name": "atelier_extract_reasonblock",
      "input": {"trace_id": "string"},
      "output": {"candidate": {"id", "title", "domain", "procedures", "dead_ends"}}
    },
    {
      "name": "atelier_monitor_event",
      "input": {
        "event_type": "SecondGuessing|Thrashing|BudgetExhaustion|RepeatedFailure|WrongDirection",
        "severity": "low|medium|high",
        "message": "string"
      },
      "output": {"recorded": "bool"}
    },
    {
      "name": "atelier_compress_context",
      "input": {"run_id": "string"},
      "output": {"summary": "string"}
    },
    {
      "name": "atelier_get_environment_context",
      "input": {"domain": "string"},
      "output": {
        "environment": {"id", "title", "domain_match", "required_validations", "forbidden_phrases", "top_procedures"}
      }
    },
    {
      "name": "atelier_smart_read",
      "input": {"file_path": "string"},
      "output": {"content": "string", "cache_hit": "bool", "tokens_saved": "int"}
    },
    {
      "name": "atelier_smart_search",
      "input": {"query": "string", "path": "string"},
      "output": {"results": ["string"], "cache_hit": "bool", "calls_avoided": "int"}
    },
    {
      "name": "atelier_cached_grep",
      "input": {"pattern": "string", "path": "string"},
      "output": {"matches": ["string"], "cache_hit": "bool"}
    }
  ]
}
```

---

## 🚫 ERROR HANDLING (Decision Trees)

### When atelier_check_plan returns status="blocked"

```
IF status == "blocked":
  ├─ STOP editing code
  ├─ Read suggested_plan from response
  ├─ Replace your plan with suggested_plan
  ├─ Call atelier_check_plan again with new plan
  └─ Repeat until status != "blocked"
```

### When atelier_run_rubric_gate returns status="blocked"

```
IF status == "blocked":
  ├─ DO NOT mark task success
  ├─ Read failures list
  ├─ Fix each failed check in code
  ├─ Call atelier_run_rubric_gate again
  └─ Repeat until status="pass"
```

### When same command/test fails 2+ times

```
IF count_failures >= 2 AND same_error_signature:
  ├─ Call atelier_rescue_failure
  ├─ Read matched ReasonBlocks
  ├─ Apply rescue procedure
  ├─ Re-run test/command
  ├─ IF still fails same way:
  │  └─ Call atelier_rescue_failure again (max 3 times total)
  └─ IF 3rd attempt still fails:
     └─ STOP and ask human for help
```

### When atelier_get_reasoning_context returns empty

```
IF context is empty:
  ├─ Verify domain is correct
  ├─ Verify files exist
  ├─ Try without domain filter
  └─ IF still empty: domain has no ReasonBlocks yet (normal)
```

---

## 📊 HIGH-RISK DOMAINS (Require Rubric Gate)

```json
{
  "high_risk_domains": [
    {
      "domain": "beseam.shopify.publish",
      "rubric_id": "rubric_shopify_publish",
      "required_checks": 5,
      "description": "Publishing product data to Shopify"
    },
    {
      "domain": "beseam.pdp.schema",
      "rubric_id": "rubric_pdp_schema",
      "required_checks": 4,
      "description": "Changing PDP schema or indexes"
    },
    {
      "domain": "beseam.catalog.fix",
      "rubric_id": "rubric_catalog_fix",
      "required_checks": 3,
      "description": "Fixing catalog data integrity"
    },
    {
      "domain": "beseam.tracker.classification",
      "rubric_id": "rubric_ai_referral_classification",
      "required_checks": 4,
      "description": "AI referral classification changes"
    }
  ]
}
```

**Rule:** If domain is in high_risk_domains, MUST call atelier_run_rubric_gate before marking task success.

---

## ⚠️ HARD RULES (Never Break)

```
1. DO NOT skip atelier_check_plan before editing code in high-risk domains
2. DO NOT ignore status="blocked" from check_plan or run_rubric_gate
3. DO NOT propose same hypothesis twice in repair loop
4. DO NOT call record_trace without observable facts
5. DO NOT store secrets, API keys, tokens, or PII in traces
6. DO NOT edit code after review agent reports verdict="block"
7. DO NOT loop more than 2 times on rescue_failure
8. DO NOT skip get_run_ledger when in repair agent
9. DO NOT call record_trace during exploration (explore agent only reads)
10. DO NOT mark task success if rubric_gate status != "pass"
```

---

## 🔍 HOW TO GET HELP

```
# See all available commands:
uv run atelier -h

# Get help on specific command:
uv run atelier COMMAND -h

# Examples:
uv run atelier check-plan -h
uv run atelier context -h
uv run atelier list-blocks -h
uv run atelier record-trace -h
uv run atelier rescue -h
uv run atelier run-rubric -h
```

---

## 📁 DIRECTORY STRUCTURE

- `src/atelier/` — Core engine (models, store, runtime, CLI, MCP, service)
- `tests/` — Test suite (214 passing)
- `docs/` — Human-readable documentation
- `integrations/` — Host adapter configs (Claude, Codex, opencode, Copilot, Gemini)
- `frontend/` — React dashboard
- `.atelier/` — Runtime data (gitignored)

---

## 🔗 LINKS FOR HUMANS (Not for agents)

- **Quick reference card:** [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- **Architecture:** [atelier/docs/](docs/)
- **Installation:** [atelier/README.md](README.md)
