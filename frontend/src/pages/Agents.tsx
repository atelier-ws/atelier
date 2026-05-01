import { useState } from "react";

interface AgentDef {
  id: string;
  label: string;
  icon: string;
  color: string;
  description: string;
  tools: string[];
  mode: string;
  file: string;
  rules: string[];
}

const AGENTS: AgentDef[] = [
  {
    id: "code",
    label: "atelier:code",
    icon: "💜",
    color: "purple",
    description: "Main coding agent. Edits, refactors, fixes bugs, and ships features. MUST use the Atelier reasoning loop on every task.",
    tools: ["* (all tools)"],
    mode: "Plan → Validate → Implement → Rescue → Rubric → Trace",
    file: "integrations/claude/plugin/agents/code.md",
    rules: [
      "Retrieve context before drafting any plan (get_reasoning_context)",
      "Validate plan with check_plan — never skip when blocked",
      "Rescue repeated failures (same error 2+ times) before retrying",
      "Run rubric gate on high-risk domains before declaring success",
      "Record trace at completion with observable summary only",
    ],
  },
  {
    id: "explore",
    label: "atelier:explore",
    icon: "🔍",
    color: "yellow",
    description: "Read-only repo exploration. Retrieves ReasonBlocks, reads files, runs grep/search. Never edits, never runs migrations, never executes destructive commands.",
    tools: ["Read", "Grep", "Glob", "WebFetch", "atelier_get_reasoning_context"],
    mode: "Read-only investigation & summarization",
    file: "integrations/claude/plugin/agents/explore.md",
    rules: [
      "Call atelier_get_reasoning_context to fetch matched ReasonBlocks",
      "Read files, run grep/glob searches — never edit",
      "Return tight summary with ReasonBlock IDs and file/line citations",
      "Never call atelier write tools (record_trace, extract_reasonblock)",
    ],
  },
  {
    id: "review",
    label: "atelier:review",
    icon: "✅",
    color: "green",
    description: "Verifier agent. Reviews finished or in-progress patches against Atelier ReasonBlocks and rubrics. Blocks known dead ends. Uses check_plan and run_rubric_gate but never edits code.",
    tools: ["Read", "Grep", "Glob", "atelier_get_reasoning_context", "atelier_check_plan", "atelier_run_rubric_gate"],
    mode: "Verify patch → check_plan → rubric_gate → verdict",
    file: "integrations/claude/plugin/agents/review.md",
    rules: [
      "Call get_reasoning_context with task and changed files",
      "Identify ReasonBlocks whose dead_ends overlap with the patch",
      "Call check_plan against the plan implied by the diff",
      "For high-risk domains, call run_rubric_gate and require status != blocked",
      "Produce verdict: pass | warn | blocked (never approve blocked)",
    ],
  },
  {
    id: "repair",
    label: "atelier:repair",
    icon: "🔧",
    color: "orange",
    description: "Repair specialist. Activated when a test/command/tool keeps failing the same way. Loads the RunLedger, asks for rescue, applies smallest patch, verifies, and records postmortem trace.",
    tools: ["* (all tools)"],
    mode: "Ledger → Hypothesize → Rescue → Patch → Verify → Postmortem",
    file: "integrations/claude/plugin/agents/repair.md",
    rules: [
      "Inspect RunLedger first (get_run_ledger) — never re-derive what's already recorded",
      "Form single hypothesis not in hypotheses_tried or hypotheses_rejected",
      "Ask for rescue (rescue_failure) with task, error, files, recent_actions",
      "Compress context if ledger reports high token usage",
      "Apply smallest patch, verify deterministically, stop after 2 failed attempts",
    ],
  },
];

const MONITOR_ALERTS = [
  { name: "SecondGuessing", desc: "Agent is re-deriving what the ledger already records" },
  { name: "Thrashing", desc: "Rapid tool/vacillation without progress" },
  { name: "BudgetExhaustion", desc: "Approaching token/cost limit" },
  { name: "RepeatedFailure", desc: "Same error signature seen 2+ times" },
  { name: "WrongDirection", desc: "Agent heading toward a known dead end" },
];

export default function Agents() {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div className="space-y-8 text-sm">
      {/* Header */}
      <section className="border border-neutral-800 p-5 bg-neutral-900/30">
        <h1 className="text-lg font-mono font-bold text-neutral-200">Agent Definitions</h1>
        <p className="text-xs text-neutral-400 mt-2 font-mono">
          4 agents shipped inside the Claude Code plugin. Each has its own system prompt, toolset, and rules.
        </p>
        <div className="flex gap-2 mt-4 flex-wrap">
          {AGENTS.map((a) => (
            <a
              key={a.id}
              href={`#agent-${a.id}`}
              className="text-[10px] px-2.5 py-1 border border-neutral-700 hover:border-neutral-500 bg-neutral-900/50 transition font-mono"
            >
              {a.icon} {a.label}
            </a>
          ))}
        </div>
      </section>

      {/* Agent Cards */}
      <section className="space-y-3">
        {AGENTS.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            expanded={expandedId === agent.id}
            onToggle={() => setExpandedId(expandedId === agent.id ? null : agent.id)}
          />
        ))}
      </section>

      {/* Monitor Alerts */}
      <section>
        <h2 className="text-xs uppercase tracking-widest text-neutral-500 mb-4 font-mono">
          Monitor Alert Types (repair agent triggers)
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {MONITOR_ALERTS.map((m) => (
            <div key={m.name} className="border border-neutral-800 p-3 bg-neutral-900/30">
              <div className="text-xs font-bold text-amber-400 font-mono">{m.name}</div>
              <div className="text-[11px] text-neutral-400 mt-1">{m.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Standing Loop */}
      <section className="border border-neutral-800 p-5 bg-neutral-900/30">
        <h2 className="text-xs uppercase tracking-widest text-neutral-500 mb-4 font-mono">The Standing Loop (atelier:code)</h2>
        <div className="space-y-2">
          {[
            "1. Retrieve context — get_reasoning_context with task, files, domain, errors",
            "2. Draft plan — 3–8 imperative steps",
            "3. Validate plan — check_plan (exit 2 = blocked → use suggested_plan)",
            "4. Implement — keep edits aligned with validated plan",
            "5. Rescue repeated failures — rescue_failure after 2 same errors",
            "6. Rubric gate — run_rubric_gate on high-risk domains",
            "7. Record trace — record_trace with observable summary",
          ].map((step, i) => (
            <div key={i} className="flex items-start gap-3 text-xs text-neutral-300 font-mono">
              <span className="text-[10px] px-1.5 bg-neutral-800 text-neutral-400 shrink-0 mt-0.5">{i + 1}</span>
              <span className="leading-relaxed">{step}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function AgentCard({
  agent,
  expanded,
  onToggle,
}: {
  agent: AgentDef;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div id={`agent-${agent.id}`} className="border border-neutral-800 bg-neutral-900/50 overflow-hidden transition-all">
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start justify-between"
      >
        <div className="flex-1 flex items-start gap-4 min-w-0">
          {/* Icon */}
          <div className="text-2xl flex-shrink-0 mt-0.5">{agent.icon}</div>

          {/* Title & Details */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1 flex-wrap">
              {/* Expandable indicator */}
              <span
                className={`text-amber-400 font-mono text-xs transition-transform ${
                  expanded ? "rotate-90" : ""
                }`}
              >
                ❯
              </span>
              <h3 className="font-mono font-bold text-neutral-200 text-sm">
                {agent.label}
              </h3>
            </div>
            <p className="text-xs text-neutral-400">{agent.description}</p>
          </div>
        </div>
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-4">
          {/* Tools */}
          <div>
            <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
              <span>❯</span> tools
            </div>
            <div className="flex flex-wrap gap-1">
              {agent.tools.map((t) => (
                <code key={t} className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-300 font-mono border border-neutral-700">
                  {t}
                </code>
              ))}
            </div>
          </div>

          {/* Rules */}
          <div>
            <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
              <span>❯</span> rules
            </div>
            <ul className="space-y-1">
              {agent.rules.map((r, i) => (
                <li key={i} className="text-xs text-neutral-300 leading-relaxed">
                  {r}
                </li>
              ))}
            </ul>
          </div>

          {/* Mode */}
          <div>
            <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
              <span>❯</span> mode
            </div>
            <code className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-300 font-mono border border-neutral-700 block">
              {agent.mode}
            </code>
          </div>

          {/* Source */}
          <div className="pt-2 border-t border-neutral-800">
            <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">Source</div>
            <code className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-500 font-mono border border-neutral-700 block break-all">
              {agent.file}
            </code>
          </div>
        </div>
      )}
    </div>
  );
}
