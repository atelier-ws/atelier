import { useEffect, useState } from "react";
import type { OverviewStats } from "../api";
import { api } from "../api";
const fmt = new Intl.NumberFormat();
const usd = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
  }).format(n);

interface FeatureCard {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  status: "stable" | "beta" | "alpha";
  what: string;
  why: string;
  how: string[];
  usage: string;
  benefits: string[];
  docs?: string;
  cliCommands?: string[];
  mcpTools?: string[];
}

const FEATURES: FeatureCard[] = [
  {
    id: "reasonblocks",
    icon: "🧠",
    title: "ReasonBlocks",
    subtitle: "Reusable Reasoning Procedures",
    status: "stable",
    what: "Stored, reviewable procedures (not memory) that tell agents how to do things safely in a specific domain. Blocks are injected into agent context before execution via get_reasoning_context. They live in SQLite and are mirrored to .atelier/blocks/*.md for PR reviewability.",
    why: "Eliminates repeated dead-end exploration. When an agent solves something non-obvious, capture it as a ReasonBlock so future runs skip the same mistakes. 7%+ per-call token savings from day one.",
    how: [
      "10 pre-seeded blocks: shopify-product-identity, post-publish-verification, repeated-agent-failure-loop, ai-referral-classification, catalog-truth-before-pdp-fix, audit-service-change-discipline, and more",
      "FTS5-powered full-text search with domain filtering (beseam.shopify.publish, beseam.pdp.schema, etc.)",
      "Status lifecycle: active → retired → deprecated (never deleted, always auditable)",
      "Auto-extracted from successful traces via extract-block with confidence scoring",
      "Mirrored to .atelier/blocks/*.md — diffable in pull requests",
    ],
    usage:
      "uv run atelier context --task 'Fix Shopify JSON-LD' --domain beseam.pdp.schema",
    benefits: [
      "Human-reviewable procedures in git (markdown mirrors)",
      "Domain-specific injection — only relevant blocks fetched",
      "7%+ per-call token savings reproducible in benchmarks",
      "Never stores chain-of-thought — only explicit procedures",
    ],
    docs: "docs/quickstart.md",
    cliCommands: [
      "atelier context",
      "atelier list-blocks",
      "atelier add-block",
      "atelier extract-block",
    ],
    mcpTools: ["atelier_get_reasoning_context", "atelier_search"],
  },
  {
    id: "traces",
    icon: "📇",
    title: "Execution Traces",
    subtitle: "Observable Run Artifacts",
    status: "stable",
    what: "Records exactly what an agent did: which files it touched, which commands it ran, which tools it called, what errors it saw, and the diff/output summary. Traces never store chain-of-thought — only observables. Each trace links to a RunLedger for full event timeline.",
    why: "Full audit trail of every agent action. Feeds the failure analyzer to detect recurring errors. Enables cost attribution per task/domain. Required for the learning loop: trace → extract-block → reuse.",
    how: [
      "Records: agent, domain, task, status (success/failed/partial)",
      "Captures: files_touched, commands_run, tools_called, errors_seen, repeated_failures",
      "Stores diff_summary and output_summary for audit trail",
      "JSON mirror in .atelier/traces/*.json + RunLedger timeline",
      "Redaction filter applied to all fields before persistence (no secrets)",
    ],
    usage:
      "echo '{...}' | uv run atelier record-trace   # or --input path/to/trace.json",
    benefits: [
      "Full audit trail — every agent action recorded",
      "Feeds failure analysis and block extraction automatically",
      "Enables per-domain cost attribution",
      "Never stores chain-of-thought — only observables",
    ],
    docs: "docs/cli.md (Trace Commands section)",
    cliCommands: [
      "atelier record-trace",
      "atelier trace list",
      "atelier extract-block",
    ],
    mcpTools: ["atelier_record_trace"],
  },
  {
    id: "rubrics",
    icon: "📏",
    title: "Rubric Gates",
    subtitle: "Domain-Specific Verification",
    status: "stable",
    what: "YAML-defined checklists that act as quality gates. Pre-execution: block bad plans before they run. Post-execution: verify all required checks passed before marking a task done. High-risk domains (beseam.shopify.publish, beseam.pdp.schema, beseam.catalog.fix, beseam.tracker.classification) require rubric gates.",
    why: "Prevents known-bad plans from executing (exit code 2 = blocked). Enforces domain quality standards automatically. Rubric YAML files are reviewable in PRs just like code. Integrates into CI/CD via exit codes.",
    how: [
      "5 pre-seeded rubrics: rubric_shopify_publish, rubric_pdp_schema, rubric_ai_referral_classification, rubric_catalog_fix, rubric_code_change",
      "YAML format: id, domain, required_checks[] — mirrored to .atelier/rubrics/*.yaml",
      'Accepts JSON check map: {"check_name": true/false} — returns pass/fail/warn per check',
      "High-risk domains auto-required: blocks execution until all checks pass",
      "Pre-execution plan gating and post-execution output verification",
    ],
    usage:
      "echo '{\"product_identity_uses_gid\": true}' | uv run atelier run-rubric rubric_shopify_publish",
    benefits: [
      "Prevents known-bad plans before execution (exit 2 = blocked)",
      "Enforces domain quality gates automatically",
      "YAML format reviewable in pull requests",
      "Integrates into CI/CD via exit codes",
    ],
    docs: "docs/cli.md (Rubric Commands section)",
    cliCommands: [
      "atelier run-rubric",
      "atelier rubric list",
      "atelier rubric show",
    ],
    mcpTools: ["atelier_run_rubric_gate"],
  },
  {
    id: "environments",
    icon: "🌐",
    title: "Reasoning Environments",
    subtitle: "Context-Aware Configurations",
    status: "stable",
    what: "Per-domain environment bindings that store domain-specific config: API endpoints, required tools, linked rubric IDs. Retrieved at runtime to scope agent context precisely. Prevents context bloat by injecting only relevant environment config.",
    why: "Consistent context across agent sessions. Environment-specific rubric auto-binding. Reduces context window waste by injecting targeted config instead of everything.",
    how: [
      "Per-domain bindings: e.g., beseam.shopify.publish environment",
      "Stores: domain-specific config, API endpoints, required tools list, rubric_id link",
      "Retrieved at runtime to scope agent context",
      "Supports inheritance and overrides for complex domain hierarchies",
    ],
    usage:
      "uv run atelier env show beseam.shopify.publish   # or MCP: atelier_get_environment_context",
    benefits: [
      "Consistent context across agent sessions",
      "Environment-specific rubric auto-binding",
      "Reduces context bloat with targeted config",
    ],
    docs: "docs/cli.md (Environment Commands section)",
    cliCommands: [
      "atelier env list",
      "atelier env show",
      "atelier env context",
      "atelier env validate",
    ],
    mcpTools: ["atelier_get_environment", "atelier_get_environment_context"],
  },
  {
    id: "failures",
    icon: "🚨",
    title: "Failure Analyzer",
    subtitle: "Recurring Error Detection & Rescue",
    status: "stable",
    what: "Clusters traces by error signature (Levenshtein-aware matching). Detects repeated failures across runs. Generates rescue procedures automatically. Accept/reject workflow for rescue suggestions. Surfaces top failure patterns in Overview stats.",
    why: "Stops agents from retrying known dead-end paths. Auto-generates rescue blocks from failure clusters. Quantifies failure impact across the system. When an agent hits the same error 3+ times, rescue_failure gives it an escape plan.",
    how: [
      "Clusters traces by error signature with Levenshtein-aware matching",
      "Detects repeated failures: 3+ occurrences trigger rescue procedure generation",
      "Accept/reject workflow for rescue suggestions (human in the loop)",
      "Surfaces top failure patterns in Overview stats dashboard",
      "Rescue procedures follow the same lifecycle as ReasonBlocks",
    ],
    usage:
      "uv run atelier rescue --task '...' --error '...'   # or: atelier failure list",
    benefits: [
      "Stops agents from retrying known dead-end paths",
      "Auto-generates rescue blocks from failure clusters",
      "Quantifies failure impact (count, signature, example)",
      "Human-approved rescue procedures only",
    ],
    docs: "docs/cli.md (Failure Commands section)",
    cliCommands: [
      "atelier rescue",
      "atelier failure list",
      "atelier failure accept",
      "atelier analyze-failures",
    ],
    mcpTools: ["atelier_rescue_failure"],
  },
  {
    id: "savings",
    icon: "💰",
    title: "Cost & Token Savings",
    subtitle: "Per-Call Telemetry & Compression",
    status: "stable",
    what: "Tracks would-have vs. actual cost per operation. Measures compression ratio: raw → compressed token estimates. Per-model pricing: Claude, GPT, Gemini supported. Prompt-cache token tracking (cache-read hits). Exposed via /savings and /calls HTTP endpoints.",
    why: "Quantifies ROI of ReasonBlock reuse immediately. Identifies highest-saving domains for focus. Per-call lessons-used log for debugging. 7%+ savings reproducible in benchmarks (5 tasks × 5 rounds = 25 calls per model).",
    how: [
      "Tracks: would-have cost vs. actual cost per operation",
      "Compression ratio: raw_tokens_estimate → compressed_tokens_estimate",
      "Per-model pricing: claude-opus-4.6, gpt-5, gemini-2.5-pro, etc.",
      "Prompt-cache token tracking (cache-read tokens column)",
      "Exposed via /savings and /calls HTTP endpoints + React dashboard",
    ],
    usage: "uv run atelier savings   # or visit /savings page in dashboard",
    benefits: [
      "Quantifies ROI of ReasonBlock reuse (7%+ per-call)",
      "Identifies highest-saving domains for focus",
      "Per-call lessons-used log for debugging",
      "Reproducible benchmarks across 7 supported models",
    ],
    docs: "docs/benchmarks/phase7-2026-04-29.md",
    cliCommands: [
      "atelier savings",
      "atelier savings-detail",
      "atelier benchmark",
    ],
  },
  {
    id: "compressor",
    icon: "🗜️",
    title: "Context Compressor",
    subtitle: "Smart Context Window Management",
    status: "beta",
    what: "Compresses large context before agent injection. Preserves critical decision points and verified facts. Integrates with RunLedger for context history. Configurable compression ratio targets.",
    why: "Fits more reasoning into limited context windows. Reduces token waste on redundant context. Preserves signal while cutting noise. Essential for large-codebase agents.",
    how: [
      "Compresses large context before agent injection",
      "Preserves critical decision points and verified facts from RunLedger",
      "Integrates with RunLedger for full context history access",
      "Configurable compression ratio targets (default ~30% of original)",
    ],
    usage: "MCP: atelier_compress_context --run_id <id>",
    benefits: [
      "Fits more reasoning into limited context windows",
      "Reduces token waste on redundant context",
      "Preserves signal while cutting noise",
    ],
    mcpTools: ["atelier_compress_context"],
  },
  {
    id: "smart-tools",
    icon: "🔍",
    title: "Smart Tools",
    subtitle: "Enhanced File & Search Operations",
    what: "Context-aware file reading with relevance scoring. Cached grep with injection guards (patterns validated before shell execution). All tools expose metadata for compression hints. Reduces redundant file reads.",
    why: "Safer shell operations with pattern validation. Reduced redundant file reads via caching. Context-aware relevance scoring. Works with the Context Compressor for optimal token usage.",
    how: [
      "Smart read: context-aware file reading with relevance scoring",
      "Smart search: cached grep with injection guards (pattern-validated before execution)",
      "Cached grep: avoids re-reading files that haven't changed",
      "All tools expose metadata for compression hints",
    ],
    usage:
      "MCP: atelier_smart_read /path/to/file   # or: atelier_smart_search 'query'",
    benefits: [
      "Safer shell operations with pattern validation",
      "Reduced redundant file reads via caching",
      "Context-aware relevance scoring",
    ],
    status: "beta",
    mcpTools: [
      "atelier_smart_read",
      "atelier_smart_search",
      "atelier_cached_grep",
    ],
  },
  {
    id: "monitors",
    icon: "📡",
    title: "Runtime Monitors",
    subtitle: "Live Agent Run Observation",
    status: "beta",
    what: "Emit custom monitor events during agent runs. Event types: tool_call, command_result, monitor_alert. Attached to RunLedger for full timeline. Supports hypotheses tracking and verified facts accumulation.",
    why: "Real-time agent behavior observation. Custom domain-specific monitoring hooks. Full event timeline per run_id. Helps debug agent decision-making without storing chain-of-thought.",
    how: [
      "Emit custom monitor events: tool_call, command_result, monitor_alert",
      "Attached to RunLedger for full event timeline per run_id",
      "Supports hypotheses tracking and verified facts accumulation",
      "Domain-specific monitor hooks (configurable per domain)",
    ],
    usage: "MCP: atelier_monitor_event --monitor <name> --message <text>",
    benefits: [
      "Real-time agent behavior observation",
      "Custom domain-specific monitoring hooks",
      "Full event timeline per run_id",
    ],
    mcpTools: ["atelier_monitor_event"],
  },
  {
    id: "mcp-server",
    icon: "🔌",
    title: "MCP Server",
    subtitle: "Agent-Native Integration (stdio + HTTP)",
    status: "stable",
    what: "Full MCP (Model Context Protocol) server speaking JSON-RPC 2.0 over stdio. V1 core tools: get_reasoning_context, check_plan, rescue_failure, record_trace, run_rubric_gate, search. V2 extended tools: ledger, monitor, compress, smart_read, smart_search, cached_grep. Supports both stdio (local) and HTTP (remote) modes.",
    why: "Zero-code agent integration via MCP standard. All major coding agents supported (Claude Code, Codex, opencode, Copilot, Gemini CLI). Remote mode for team-shared reasoning runtime. HTTP mode for web-based agents.",
    how: [
      "V1 core (6 tools): context, check_plan, rescue, record_trace, run_rubric, search",
      "V2 extended (8 tools): ledger, monitor, compress, env, smart_read, smart_search, cached_grep",
      "Modes: stdio (local, default) or HTTP remote (shared instance)",
      "Works with Claude Code, Codex, opencode, VS Code Copilot, Gemini CLI",
      "Idempotent installers with backup-before-write + graceful skip for missing CLIs",
    ],
    usage:
      "uv run atelier-mcp   # or: ATELIER_MCP_MODE=remote uv run atelier-mcp",
    benefits: [
      "Zero-code agent integration via MCP standard",
      "All major coding agents supported",
      "Remote mode for team-shared reasoning runtime",
      "HTTP mode for REST-based agents",
    ],
    docs: "docs/engineering/mcp.md",
    cliCommands: ["atelier-mcp", "atelier service start"],
    mcpTools: ["V1: 6 tools", "V2: 8 additional tools"],
  },
  {
    id: "host-adapters",
    icon: "🧩",
    title: "Host Adapters",
    subtitle: "Per-Agent Plugin System",
    status: "stable",
    what: "Each agent host gets its native integration format. Claude Code: full plugin (agents + commands + skills + MCP). Codex: skills + AGENTS.md + MCP config. opencode: opencode.jsonc MCP config. VS Code Copilot: MCP config + custom instructions. Gemini CLI: .gemini/settings.json MCP entry.",
    why: "Each agent gets its native integration format — no generic wrappers. Graceful skip for unavailable CLIs. Dry-run and print-only modes for safety. All installers are idempotent.",
    how: [
      "Claude Code: atelier@atelier plugin + MCP + /atelier:code, /atelier:explore, /atelier:review, /atelier:repair agents",
      "Codex: skills/ directory + AGENTS.md + .mcp.json merge",
      "opencode: opencode.jsonc MCP config (auto-merged)",
      "VS Code Copilot: .mcp.json + custom instructions injection",
      "Gemini CLI: .gemini/settings.json MCP entry",
    ],
    usage:
      "make install-agent-clis   # or per-host: make install-claude, make install-codex, etc.",
    benefits: [
      "Each agent gets its native integration format",
      "Graceful skip for unavailable CLIs",
      "Dry-run and print-only modes for safety",
      "Idempotent installers with backup-before-write",
    ],
    docs: "docs/hosts/all-agent-clis.md",
    cliCommands: ["make install-agent-clis", "make verify-agent-clis"],
  },
  {
    id: "storage",
    icon: "💾",
    title: "Storage Backends",
    subtitle: "SQLite + PostgreSQL Options",
    status: "stable",
    what: "Default: SQLite + FTS5 (zero-config, single file). Optional: PostgreSQL with pgvector for similarity search. Markdown/YAML/JSON mirrors for all artifacts. Environment variable driven: ATELIER_STORAGE_BACKEND. Embedding support: text-embedding-3-small (configurable).",
    why: "Zero-config local dev with SQLite. Scale to team sharing with PostgreSQL. All artifacts readable in git (MD/YAML/JSON). pgvector is additive — FTS5 still works alongside it.",
    how: [
      "SQLite + FTS5 (default): zero-config, single file at .atelier/atelier.db",
      "PostgreSQL: for shared use, multi-agent concurrency, 1000+ blocks",
      "pgvector (optional): embedding-based similarity search alongside FTS5",
      "Mirrors: .atelier/blocks/*.md, .atelier/rubrics/*.yaml, .atelier/traces/*.json",
      "Environment driven: ATELIER_STORAGE_BACKEND, ATELIER_DATABASE_URL, ATELIER_VECTOR_SEARCH_ENABLED",
    ],
    usage:
      "ATELIER_STORAGE_BACKEND=postgres ATELIER_DATABASE_URL=... uv run atelier init",
    benefits: [
      "Zero-config local dev with SQLite",
      "Scale to team sharing with PostgreSQL",
      "All artifacts readable in git (MD/YAML/JSON)",
      "pgvector additive — FTS5 still works alongside",
    ],
    docs: "docs/engineering/storage.md",
    cliCommands: ["atelier init", "atelier init --no-seed"],
  },
];


function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="border-b border-neutral-800 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-500 font-mono">
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1 font-mono">{value}</div>
      {hint && <div className="text-xs text-neutral-500 mt-1 font-mono">{hint}</div>}
    </div>
  );
}


function FeatureCardContent({ feature }: { feature: FeatureCard }) {
  return (
    <div className="space-y-4">
      {/* What */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
          <span>❯</span> what
        </div>
        <p className="text-xs text-neutral-300 leading-relaxed">
          {feature.what}
        </p>
      </div>

      {/* Why */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
          <span>❯</span> why
        </div>
        <p className="text-xs text-neutral-300 leading-relaxed">
          {feature.why}
        </p>
      </div>

      {/* How */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
          <span>❯</span> how
        </div>
        <ul className="space-y-1">
          {feature.how.map((h, i) => (
            <li
              key={i}
              className="text-xs text-neutral-300 leading-relaxed pl-3 relative"
            >
              <span className="absolute left-0 text-neutral-600">·</span>
              {h}
            </li>
          ))}
        </ul>
      </div>

      {/* Usage */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
          <span>❯</span> usage
        </div>
        <code className="text-[10px] bg-neutral-950 px-3 py-2 block text-neutral-300 break-all font-mono border border-neutral-800 leading-relaxed">
          {feature.usage}
        </code>
      </div>

      {/* Benefits */}
      <div>
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
          <span>✓</span> benefits
        </div>
        <ul className="space-y-1">
          {feature.benefits.map((b, i) => (
            <li key={i} className="text-xs text-emerald-300/90 leading-relaxed">
              {b}
            </li>
          ))}
        </ul>
      </div>

      {/* CLI Commands */}
      {feature.cliCommands && (
        <div>
          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
            <span>⌨️</span> cli commands
          </div>
          <div className="flex flex-wrap gap-1">
            {feature.cliCommands.map((cmd) => (
              <code
                key={cmd}
                className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-300 font-mono border border-neutral-700"
              >
                {cmd}
              </code>
            ))}
          </div>
        </div>
      )}

      {/* MCP Tools */}
      {feature.mcpTools && (
        <div>
          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
            <span>🔌</span> mcp tools
          </div>
          <div className="flex flex-wrap gap-1">
            {feature.mcpTools.map((tool) => (
              <code
                key={tool}
                className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-300 font-mono border border-neutral-700"
              >
                {tool}
              </code>
            ))}
          </div>
        </div>
      )}

      {/* Docs link */}
      {feature.docs && (
        <div className="pt-2 border-t border-neutral-800">
          <a
            href={`/${feature.docs}`}
            className="text-[10px] text-neutral-500 hover:text-amber-400 transition uppercase tracking-wide font-mono"
          >
            view docs →
          </a>
        </div>
      )}
    </div>
  );
}

export default function Overview() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "stable" | "beta" | "alpha">(
    "all"
  );

  useEffect(() => {
    api
      .overview()
      .then(setStats)
      .catch((e) => setErr(String(e)));
  }, []);

  const toggle = (id: string) =>
    setExpandedId((prev) => (prev === id ? null : id));

  const filtered =
    filter === "all" ? FEATURES : FEATURES.filter((f) => f.status === filter);

  return (
    <div className="space-y-8">
      {/* Stats Grid */}
      <section>
        <h2 className="text-xs uppercase tracking-widest text-neutral-500 mb-4 font-mono">
          System Stats
        </h2>
        {err && <div className="text-red-400">Error: {err}</div>}
        {!stats && !err && <div className="text-neutral-500">Loading…</div>}
        {stats && (
          <div className="border border-neutral-800 bg-neutral-900/30 p-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-x-8 gap-y-1">
              <StatCard
                label="Total Traces"
                value={fmt.format(stats.total_traces)}
              />
              <StatCard
                label="Reason Blocks"
                value={fmt.format(stats.total_blocks)}
              />
              <StatCard label="Rubrics" value={fmt.format(stats.total_rubrics)} />
              <StatCard
                label="Environments"
                value={fmt.format(stats.total_environments)}
              />
              <StatCard
                label="Failure Clusters"
                value={fmt.format(stats.total_clusters)}
              />
              <StatCard
                label="Compression Ratio"
                value={stats.average_compression_ratio.toFixed(3)}
                hint="compressed / raw"
              />
              <StatCard
                label="Est. Cost"
                value={usd(stats.estimated_total_cost_usd)}
              />
              <StatCard
                label="Est. Savings"
                value={usd(stats.estimated_saved_cost_usd)}
              />
            </div>
          </div>
        )}
      </section>

      {/* Features */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs uppercase tracking-widest text-neutral-500 font-mono">
            Features & Capabilities
          </h2>
          <div className="flex gap-2">
            {(["all", "stable", "beta", "alpha"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-[10px] px-2.5 py-1 uppercase font-bold tracking-tight font-mono transition border ${
                  filter === f
                    ? "border-amber-400/50 bg-amber-400/10 text-amber-300"
                    : "border-neutral-700 text-neutral-500 hover:text-neutral-300"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          {filtered.map((f) => (
            <div
              key={f.id}
              className="border border-neutral-800 bg-neutral-900/50 overflow-hidden transition-all"
            >
              {/* Card Header */}
              <button
                onClick={() => toggle(f.id)}
                className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start justify-between group"
              >
                <div className="flex-1 flex items-start gap-4 min-w-0">
                  {/* Icon */}
                  <div className="text-2xl flex-shrink-0 mt-0.5">{f.icon}</div>

                  {/* Title & Subtitle */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1 flex-wrap">
                      {/* Expandable indicator */}
                      <span
                        className={`text-amber-400 font-mono text-xs transition-transform ${
                          expandedId === f.id ? "rotate-90" : ""
                        }`}
                      >
                        ❯
                      </span>
                      <h3 className="font-mono font-bold text-neutral-200 text-sm">
                        {f.title}
                      </h3>
                      <span
                        className={`text-[10px] px-2 py-0.5 font-mono font-bold uppercase tracking-wide ${
                          f.status === "stable"
                            ? "bg-emerald-900/30 text-emerald-300"
                            : f.status === "beta"
                              ? "bg-amber-900/30 text-amber-300"
                              : "bg-red-900/30 text-red-300"
                        }`}
                      >
                        {f.status}
                      </span>
                    </div>
                    {f.subtitle && (
                      <p className="font-mono text-[11px] text-neutral-500">
                        {f.subtitle}
                      </p>
                    )}
                  </div>
                </div>
              </button>

              {/* Expanded Content */}
              {expandedId === f.id && (
                <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4">
                  <FeatureCardContent feature={f} />
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
