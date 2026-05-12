import { useEffect, useState, useMemo } from "react";
import {
  api,
  type GranularToolUsage,
  type AnalyticsDashboard,
  type DashboardTool,
  type DashboardHostModelOverview,
} from "../api";
import { MetricCard } from "../components/WorkbenchUI";

const AGENTS = ["Claude", "Codex", "Copilot", "Opencode", "Gemini"];
const CATEGORIES = [
  "Native / Unoptimized",
  "Atelier Optimized",
  "Other Third-Party / Minor",
  "Miscellaneous",
  "Token Usage",
];
const TABS = [
  "Overview",
  "Timeline",
  "Domains",
  "Tool Breakdown",
  "Analysis",
] as const;
type Tab = (typeof TABS)[number];

// ---- Shared helpers --------------------------------------------------------

function defaultdict_int() {
  return new Proxy({} as Record<string, number>, {
    get: (target, name: string) => (name in target ? target[name] : 0),
  });
}

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals);
}

function fmtM(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
  return String(n);
}

// ---- Mini bar chart --------------------------------------------------------

function MiniBar({
  value,
  max,
  color = "bg-emerald-500/50",
}: {
  value: number;
  max: number;
  color?: string;
}) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="w-24 h-1.5 bg-neutral-800 rounded-full overflow-hidden">
      <div
        className={`h-full ${color} rounded-full`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---- Daily activity chart --------------------------------------------------

function DailyChart({ daily }: { daily: AnalyticsDashboard["daily"] }) {
  if (!daily.length)
    return (
      <div className="text-neutral-600 italic text-xs p-4">No daily data.</div>
    );

  const maxCost = Math.max(...daily.map((d) => d.cost), 0.0001);
  const recent = daily.slice(-30);

  return (
    <section className="border border-neutral-800 bg-neutral-950/40 p-5 space-y-3">
      <div className="text-[11px] uppercase tracking-widest text-neutral-400 font-bold">
        Spend by Day
      </div>
      <div className="flex items-end gap-1 h-20 overflow-x-auto pb-1">
        {recent.map((d, i) => {
          const h = Math.max(4, (d.cost / maxCost) * 80);
          return (
            <div
              key={i}
              className="flex flex-col items-center gap-0.5 shrink-0"
              title={`${d.date}: $${d.cost.toFixed(3)} · ${d.sessions} sessions`}
            >
              <div
                className="w-4 bg-emerald-500/60 rounded-sm hover:bg-emerald-400/80 transition-colors cursor-default"
                style={{ height: `${h}px` }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[9px] text-neutral-600 font-mono">
        <span>{recent[0]?.date}</span>
        <span>{recent[recent.length - 1]?.date}</span>
      </div>
      <div className="grid grid-cols-3 gap-3 pt-2 border-t border-neutral-800/60">
        <div>
          <div className="text-[9px] uppercase text-neutral-500 mb-0.5">
            Total Days
          </div>
          <div className="text-sm font-mono text-neutral-200">
            {daily.length}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-neutral-500 mb-0.5">
            Avg/Day
          </div>
          <div className="text-sm font-mono text-neutral-200">
            ${(daily.reduce((a, d) => a + d.cost, 0) / daily.length).toFixed(2)}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-neutral-500 mb-0.5">
            Peak Day
          </div>
          <div className="text-sm font-mono text-emerald-300">
            ${Math.max(...daily.map((d) => d.cost)).toFixed(2)}
          </div>
        </div>
      </div>
    </section>
  );
}

// ---- By Host table ---------------------------------------------------------

function ByHostTable({ byHost }: { byHost: AnalyticsDashboard["by_host"] }) {
  const maxCost = Math.max(...byHost.map((r) => r.cost), 0.0001);
  return (
    <section className="border border-neutral-800 bg-neutral-950/40">
      <div className="bg-neutral-900/80 border-b border-neutral-800 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
          Agent Host Breakdown
        </div>
      </div>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 bg-neutral-900/50">
            <th className="px-4 py-2 text-left">Host</th>
            <th className="px-4 py-2 text-right">Sessions</th>
            <th className="px-4 py-2 text-right">Cost</th>
            <th className="px-4 py-2 text-right">Cache %</th>
            <th className="px-4 py-2">Rel. Cost</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-900">
          {byHost.map((r, i) => (
            <tr key={i} className="hover:bg-neutral-800/20">
              <td className="px-4 py-2 font-mono text-cyan-300/80 capitalize">
                {r.host}
              </td>
              <td className="px-4 py-2 text-right font-mono text-neutral-400">
                {r.sessions}
              </td>
              <td className="px-4 py-2 text-right font-mono text-emerald-300">
                ${fmt(r.cost)}
              </td>
              <td className="px-4 py-2 text-right font-mono text-amber-300/80">
                {fmt(r.cache_pct, 1)}%
              </td>
              <td className="px-4 py-2">
                <MiniBar value={r.cost} max={maxCost} color="bg-cyan-500/50" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ---- By Model table --------------------------------------------------------

function ByModelTable({
  byModel,
}: {
  byModel: AnalyticsDashboard["by_model"];
}) {
  const maxCost = Math.max(...byModel.map((r) => r.cost), 0.0001);
  return (
    <section className="border border-neutral-800 bg-neutral-950/40">
      <div className="bg-neutral-900/80 border-b border-neutral-800 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
          By Model
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 bg-neutral-900/50">
              <th className="px-4 py-2 text-left">Model</th>
              <th className="px-4 py-2 text-right">Sessions</th>
              <th className="px-4 py-2 text-right">Input (M)</th>
              <th className="px-4 py-2 text-right">Output (M)</th>
              <th className="px-4 py-2 text-right">Cache %</th>
              <th className="px-4 py-2 text-right">Cost</th>
              <th className="px-4 py-2">Rel. Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-900">
            {byModel.map((r, i) => (
              <tr key={i} className="hover:bg-neutral-800/20">
                <td className="px-4 py-2 font-mono text-neutral-300 text-[10px]">
                  {r.model || "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {r.sessions}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {(r.input_tokens / 1_000_000).toFixed(2)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {(r.output_tokens / 1_000_000).toFixed(2)}
                </td>
                <td className="px-4 py-2 text-right">
                  <span
                    className={`font-mono text-[10px] ${
                      r.cache_pct > 60
                        ? "text-emerald-400"
                        : r.cache_pct > 30
                          ? "text-amber-400"
                          : "text-red-400/80"
                    }`}
                  >
                    {fmt(r.cache_pct, 1)}%
                  </span>
                </td>
                <td className="px-4 py-2 text-right font-mono text-emerald-300">
                  ${fmt(r.cost)}
                </td>
                <td className="px-4 py-2">
                  <MiniBar value={r.cost} max={maxCost} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---- Top Sessions ----------------------------------------------------------

function TopSessions({
  sessions,
}: {
  sessions: AnalyticsDashboard["top_sessions"];
}) {
  const maxCost = Math.max(...sessions.map((s) => s.cost), 0.0001);
  return (
    <section className="border border-neutral-800 bg-neutral-950/40">
      <div className="bg-neutral-900/80 border-b border-neutral-800 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
          Costliest Sessions
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 bg-neutral-900/50">
              <th className="px-4 py-2">#</th>
              <th className="px-4 py-2 text-left">Date</th>
              <th className="px-4 py-2 text-left">Host</th>
              <th className="px-4 py-2 text-left">Project</th>
              <th className="px-4 py-2 text-left">Model</th>
              <th className="px-4 py-2 text-right">Input</th>
              <th className="px-4 py-2 text-right">Output</th>
              <th className="px-4 py-2 text-right">Cache</th>
              <th className="px-4 py-2 text-right">Cost</th>
              <th className="px-4 py-2">Rel.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-900">
            {sessions.map((s, i) => (
              <tr key={i} className="hover:bg-neutral-800/20">
                <td className="px-4 py-2 font-mono text-neutral-600">
                  {i + 1}
                </td>
                <td className="px-4 py-2 font-mono text-neutral-500 text-[10px]">
                  {s.date}
                </td>
                <td className="px-4 py-2 font-mono text-cyan-300/80 capitalize">
                  {s.host}
                </td>
                <td
                  className="px-4 py-2 text-neutral-400 max-w-[140px] truncate"
                  title={s.domain}
                >
                  {s.domain}
                </td>
                <td className="px-4 py-2 font-mono text-neutral-500 text-[10px]">
                  {s.model || "—"}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {fmtM(s.input_tokens)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {fmtM(s.output_tokens)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-amber-400/70">
                  {fmtM(s.cached_tokens)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-emerald-300 font-bold">
                  ${fmt(s.cost)}
                </td>
                <td className="px-4 py-2">
                  <MiniBar
                    value={s.cost}
                    max={maxCost}
                    color="bg-amber-500/50"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---- By Project ------------------------------------------------------------

function ByProjectTable({
  domains,
}: {
  domains: AnalyticsDashboard["by_domain"];
}) {
  const maxCost = Math.max(...domains.map((d) => d.cost), 0.0001);
  return (
    <section className="border border-neutral-800 bg-neutral-950/40">
      <div className="bg-neutral-900/80 border-b border-neutral-800 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
          Domain Spend
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 bg-neutral-900/50">
              <th className="px-4 py-2 text-left">Project</th>
              <th className="px-4 py-2 text-right">Sessions</th>
              <th className="px-4 py-2 text-right">Total Cost</th>
              <th className="px-4 py-2 text-right">Avg / Session</th>
              <th className="px-4 py-2">Rel. Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-900">
            {domains.map((d, i) => (
              <tr key={i} className="hover:bg-neutral-800/20">
                <td
                  className="px-4 py-2 text-neutral-300 font-medium max-w-[200px] truncate"
                  title={d.domain}
                >
                  {d.domain}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  {d.sessions}
                </td>
                <td className="px-4 py-2 text-right font-mono text-emerald-300">
                  ${fmt(d.cost)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-neutral-400">
                  ${fmt(d.avg_cost, 3)}
                </td>
                <td className="px-4 py-2">
                  <MiniBar
                    value={d.cost}
                    max={maxCost}
                    color="bg-violet-500/50"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---- Tool breakdown section ------------------------------------------------

function ToolTable({
  title,
  tools,
  color = "bg-orange-500/50",
}: {
  title: string;
  tools: DashboardTool[];
  color?: string;
}) {
  const maxCalls = Math.max(...tools.map((t) => t.calls), 1);
  if (!tools.length)
    return (
      <section className="border border-neutral-800 bg-neutral-950/40 p-4">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold mb-2">
          {title}
        </div>
        <div className="text-neutral-600 italic text-xs">No data.</div>
      </section>
    );
  return (
    <section className="border border-neutral-800 bg-neutral-950/40">
      <div className="bg-neutral-900/80 border-b border-neutral-800 p-3">
        <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
          {title}
        </div>
      </div>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 bg-neutral-900/50">
            <th className="px-4 py-2 text-left">Tool</th>
            <th className="px-4 py-2 text-right">Calls</th>
            <th className="px-4 py-2 text-right">Out Tokens</th>
            <th className="px-4 py-2">Usage</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-900">
          {tools.map((t, i) => (
            <tr key={i} className="hover:bg-neutral-800/20">
              <td className="px-4 py-2 font-mono text-neutral-300">{t.name}</td>
              <td className="px-4 py-2 text-right font-mono text-neutral-400">
                {t.calls.toLocaleString()}
              </td>
              <td className="px-4 py-2 text-right font-mono text-neutral-400">
                {fmtM(t.output_tokens)}
              </td>
              <td className="px-4 py-2">
                <MiniBar value={t.calls} max={maxCalls} color={color} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

// ---- Savings Insights ------------------------------------------------------

function SavingsInsights({ dashboard }: { dashboard: AnalyticsDashboard }) {
  const { top_sessions, by_model } = dashboard;

  const highCostSessions = top_sessions.filter((s) => s.cost > 1.0);
  const noCacheSessions = top_sessions.filter(
    (s) =>
      s.cost > 0.5 &&
      s.input_tokens > 0 &&
      s.cached_tokens / (s.input_tokens + s.cached_tokens) < 0.1
  );
  const heavyContextSessions = top_sessions.filter(
    (s) => s.input_tokens > 500_000
  );
  const multiModelCount = by_model.filter((m) => m.cost > 0.1).length;

  return (
    <div className="space-y-4">
      <section className="border border-neutral-800 bg-neutral-950/40 p-5">
        <div className="text-[11px] uppercase tracking-widest text-neutral-400 font-bold mb-4">
          Session Analysis
        </div>
        <div className="space-y-3">
          {highCostSessions.length > 0 && (
            <div className="border border-red-900/40 bg-red-950/20 p-3 rounded">
              <div className="text-[10px] text-red-400 font-bold uppercase mb-1">
                🔴 {highCostSessions.length} High-Cost Session
                {highCostSessions.length > 1 ? "s" : ""} (&gt;$1.00 each)
              </div>
              <div className="text-[10px] text-red-300/70 space-y-0.5">
                {highCostSessions.slice(0, 3).map((s, i) => (
                  <div key={i}>
                    {s.date} · {s.host} · {s.domain} —{" "}
                    <span className="text-red-300">${fmt(s.cost)}</span>
                  </div>
                ))}
              </div>
              <div className="text-[9px] text-red-400/50 mt-2">
                Consider adding context pruning, summarization, or session
                splitting.
              </div>
            </div>
          )}

          {noCacheSessions.length > 0 && (
            <div className="border border-amber-900/40 bg-amber-950/20 p-3 rounded">
              <div className="text-[10px] text-amber-400 font-bold uppercase mb-1">
                🟡 {noCacheSessions.length} Session
                {noCacheSessions.length > 1 ? "s" : ""} with Low Cache
                Utilization
              </div>
              <div className="text-[10px] text-amber-300/70">
                These sessions have &lt;10% cache hit rate on expensive prompts.
              </div>
              <div className="text-[9px] text-amber-400/50 mt-2">
                Use long-lived system prompts and structured prefixes to improve
                caching.
              </div>
            </div>
          )}

          {heavyContextSessions.length > 0 && (
            <div className="border border-orange-900/40 bg-orange-950/20 p-3 rounded">
              <div className="text-[10px] text-orange-400 font-bold uppercase mb-1">
                🟠 {heavyContextSessions.length} Context-Heavy Session
                {heavyContextSessions.length > 1 ? "s" : ""} (&gt;500k input
                tokens)
              </div>
              <div className="text-[10px] text-orange-300/70 space-y-0.5">
                {heavyContextSessions.slice(0, 3).map((s, i) => (
                  <div key={i}>
                    {s.date} · {s.host} — {fmtM(s.input_tokens)} input tokens
                  </div>
                ))}
              </div>
              <div className="text-[9px] text-orange-400/50 mt-2">
                Add file chunking, selective context inclusion, and compact
                intermediate results.
              </div>
            </div>
          )}

          {multiModelCount > 2 && (
            <div className="border border-blue-900/40 bg-blue-950/20 p-3 rounded">
              <div className="text-[10px] text-blue-400 font-bold uppercase mb-1">
                🔵 {multiModelCount} Active Models — Consider Consolidation
              </div>
              <div className="text-[10px] text-blue-300/70">
                You're using {multiModelCount} models with non-trivial cost.
                Routing cheaper tasks to smaller models could reduce spend.
              </div>
            </div>
          )}

          {highCostSessions.length === 0 &&
            noCacheSessions.length === 0 &&
            heavyContextSessions.length === 0 && (
              <div className="text-neutral-500 italic text-xs">
                ✅ No significant optimization opportunities detected in this
                period.
              </div>
            )}
        </div>
      </section>

      {top_sessions.length > 0 && <TopSessions sessions={top_sessions} />}
    </div>
  );
}

// ---- Cost Drivers Chart ----------------------------------------------------

function CostDriversChart({
  stats,
}: {
  stats: {
    userInputTokens: number;
    modelThinkingTokens: number;
    llmOutputTokens: number;
    toolOutputTokens: number;
  };
}) {
  const breakdown = [
    {
      label: "User Input",
      tokens: stats.userInputTokens,
      color: "bg-emerald-500/60",
      accent: "text-emerald-300",
    },
    {
      label: "Thinking",
      tokens: stats.modelThinkingTokens,
      color: "bg-cyan-500/60",
      accent: "text-cyan-300",
    },
    {
      label: "Tool Output",
      tokens: stats.toolOutputTokens,
      color: "bg-amber-500/60",
      accent: "text-amber-300",
    },
    {
      label: "Output",
      tokens: stats.llmOutputTokens,
      color: "bg-violet-500/60",
      accent: "text-violet-300",
    },
  ].filter((item) => item.tokens > 0);

  const totalTrackedTokens =
    breakdown.reduce((sum, item) => sum + item.tokens, 0) || 1;

  if (!breakdown.length) {
    return (
      <section className="border border-neutral-800 bg-neutral-950/70 p-5 space-y-4">
        <div className="text-[11px] uppercase tracking-widest text-neutral-400 font-bold">
          Token Flow
        </div>
        <div className="text-xs text-neutral-500 italic">
          No input or output token activity found for the current filters.
        </div>
      </section>
    );
  }

  return (
    <section className="border border-neutral-800 bg-neutral-950/70 p-5 space-y-4">
      <div className="text-[11px] uppercase tracking-widest text-neutral-400 font-bold">
        Token Flow
      </div>
      <div className="space-y-3">
        {breakdown.map((item) => {
          const share = (item.tokens / totalTrackedTokens) * 100;
          return (
            <div key={item.label} className="space-y-1">
              <div className="flex justify-between text-[10px] gap-4">
                <span className="text-neutral-300">{item.label}</span>
                <span className={`font-mono ${item.accent}`}>
                  {fmtM(item.tokens)} tokens · {share.toFixed(1)}%
                </span>
              </div>
              <div className="h-2 bg-neutral-900 overflow-hidden rounded">
                <div
                  className={`h-full ${item.color}`}
                  style={{ width: `${share}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="text-[9px] text-neutral-500 pt-2 border-t border-neutral-800 space-y-1">
        <p>
          Output is model-generated text, including assistant responses plus
          tool call arguments. Tool output stays separate.
        </p>
      </div>
    </section>
  );
}

// ---- Main component --------------------------------------------------------

export default function Analytics() {
  const [data, setData] = useState<GranularToolUsage[]>([]);
  const [dashboard, setDashboard] = useState<AnalyticsDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [dashLoading, setDashLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("Overview");

  // Filters
  const [agentFilter, setAgentFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [dateRange, setDateRange] = useState({ days: 30 });

  useEffect(() => {
    setLoading(true);
    api
      .granularAnalytics(undefined, undefined, 5000, dateRange.days)
      .then(setData)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));

    setDashLoading(true);
    api
      .analyticsDashboard(dateRange.days)
      .then(setDashboard)
      .catch(() => setDashboard(null))
      .finally(() => setDashLoading(false));
  }, [dateRange.days]);

  const filteredData = useMemo(() => {
    const agentMatch = agentFilter.toLowerCase();
    const modelMatch = modelFilter.toLowerCase();
    return data.filter((item) => {
      const itemAgent = (item.agent || "").toLowerCase();
      const itemModel = (item.model || "").toLowerCase();
      if (agentFilter !== "all" && itemAgent !== agentMatch) return false;
      if (modelFilter !== "all" && itemModel !== modelMatch) return false;
      if (categoryFilter !== "all" && item.category !== categoryFilter)
        return false;
      if (search) {
        const s = search.toLowerCase();
        return (
          item.tool_name.toLowerCase().includes(s) ||
          (item.sub_command?.toLowerCase() || "").includes(s)
        );
      }
      return true;
    });
  }, [data, agentFilter, modelFilter, categoryFilter, search]);

  const models = useMemo(() => {
    const set = new Set<string>();
    data.forEach((d) => {
      if (d.model) set.add(d.model);
    });
    return Array.from(set).sort();
  }, [data]);

  const stats = useMemo(() => {
    const totalOutputTokens = filteredData
      .filter((d) => ["result", "thinking", "tool_call"].includes(d.event_type))
      .reduce((acc, item) => acc + item.output_tokens, 0);
    const userInputTokens = filteredData
      .filter((d) => d.event_type === "user_string")
      .reduce((acc, item) => acc + item.input_tokens, 0);
    const toolCalls = filteredData
      .filter((d) => d.event_type === "tool_call")
      .reduce((acc, item) => acc + (item.call_count ?? 1), 0);
    const uniqueTools = new Set(
      filteredData
        .filter((d) => d.event_type === "tool_call")
        .map((item) => item.tool_name)
    ).size;
    const cachedPromptTokens = filteredData
      .filter((d) => d.event_type === "cached_prompt")
      .reduce((acc, item) => acc + item.input_tokens, 0);
    const modelResponseTokens = filteredData
      .filter((d) => d.event_type === "result")
      .reduce((acc, item) => acc + item.output_tokens, 0);
    const modelThinkingTokens = filteredData
      .filter((d) => d.event_type === "thinking")
      .reduce((acc, item) => acc + item.output_tokens, 0);
    const toolInputTokens = filteredData
      .filter((d) => d.event_type === "tool_call")
      .reduce((acc, item) => acc + item.input_tokens, 0);
    const toolOutputTokens = filteredData
      .filter((d) => d.event_type === "tool_call")
      .reduce((acc, item) => acc + item.output_tokens, 0);
    const totalCost = filteredData.reduce((acc, item) => {
      if (
        [
          "prompt",
          "cached_prompt",
          "cache_create",
          "result",
          "thinking",
        ].includes(item.event_type)
      ) {
        return acc + (item.cost || 0);
      }
      return acc;
    }, 0);
    const estimatedMonthlyCost = totalCost * (30 / (dateRange.days || 1));
    const toolCosts = defaultdict_int();
    filteredData.forEach((item) => {
      toolCosts[item.tool_name] += item.cost || 0;
    });
    const topCostDriver =
      Object.entries(toolCosts).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";
    return {
      totalCost,
      estimatedMonthlyCost,
      topCostDriver,
      userInputTokens,
      modelThinkingTokens,
      llmOutputTokens: modelResponseTokens + toolInputTokens,
      toolOutputTokens,
      cachedPromptTokens,
      toolCalls,
      uniqueTools,
      totalOutputTokens,
    };
  }, [filteredData, dateRange.days]);

  const hostModelStats = dashboard?.host_model_overview ?? [];

  const costDriversData = useMemo(() => {
    const toolCosts = defaultdict_int();
    const toolCalls = defaultdict_int();
    const toolTokens = defaultdict_int();
    filteredData
      .filter((d) => d.event_type === "tool_call")
      .forEach((d) => {
        toolCosts[d.tool_name] += d.cost || 0;
        toolCalls[d.tool_name] += d.call_count ?? 1;
        toolTokens[d.tool_name] += d.output_tokens;
      });
    return Object.entries(toolCosts)
      .map(([tool, cost]) => ({
        tool,
        cost,
        calls: toolCalls[tool],
        tokens: toolTokens[tool],
        costPerCall: cost / (toolCalls[tool] || 1),
      }))
      .sort((a, b) => b.cost - a.cost)
      .slice(0, 10);
  }, [filteredData]);

  const tableData = useMemo(() => {
    return filteredData
      .map((item) => {
        const cost = item.cost || 0;
        const calls = item.call_count || 1;
        return {
          ...item,
          outPerCall: item.output_tokens / calls,
          cost,
          costPerCall: cost / calls,
          pctOfTotal:
            (item.output_tokens / (stats.totalOutputTokens || 1)) * 100,
        };
      })
      .sort((a, b) => b.cost - a.cost);
  }, [filteredData, stats.totalOutputTokens]);

  if (err) return <div className="text-red-400 p-6">Error: {err}</div>;
  if (loading && data.length === 0)
    return (
      <div className="text-neutral-400 p-6 italic animate-pulse">
        Loading analytics...
      </div>
    );

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 bg-black min-h-screen text-neutral-200 font-sans">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-neutral-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Cost & Efficiency
          </h1>
          <p className="text-neutral-500 text-sm mt-1">
            Real-time token attribution and economic breakdown.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase font-bold text-neutral-500">
              Days
            </span>
            <input
              type="number"
              value={dateRange.days}
              onChange={(e) =>
                setDateRange({ days: parseInt(e.target.value) || 30 })
              }
              className="w-16 bg-neutral-900 border border-neutral-700 px-2 py-1 text-xs font-mono text-neutral-300 focus:outline-none focus:border-emerald-500"
            />
          </div>
          <div className="h-4 w-px bg-neutral-800 mx-1 hidden md:block" />
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase font-bold text-neutral-500">
              Agent
            </span>
            <select
              value={agentFilter}
              onChange={(e) => {
                setAgentFilter(e.target.value);
                setModelFilter("all");
              }}
              className="bg-neutral-900 border border-neutral-700 px-2 py-1 text-xs text-neutral-300 focus:outline-none"
            >
              <option value="all">All Agents</option>
              {AGENTS.map((a) => (
                <option key={a} value={a.toLowerCase()}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase font-bold text-neutral-500">
              Model
            </span>
            <select
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
              className="bg-neutral-900 border border-neutral-700 px-2 py-1 text-xs text-neutral-300 focus:outline-none max-w-[150px]"
            >
              <option value="all">All Models</option>
              {models.map((m) => (
                <option key={m} value={m.toLowerCase()}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase font-bold text-neutral-500">
              Category
            </span>
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-neutral-900 border border-neutral-700 px-2 py-1 text-xs text-neutral-300 focus:outline-none"
            >
              <option value="all">All Categories</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Summary metrics */}
      <section className="grid gap-4 md:grid-cols-4">
        <MetricCard
          label="Total Estimated Cost"
          value={`$${stats.totalCost.toFixed(2)}`}
          tone="emerald"
        />
        <MetricCard
          label="Projected Month-End"
          value={`$${stats.estimatedMonthlyCost.toFixed(2)}`}
          tone="emerald"
        />
        <MetricCard
          label="Total Tool Calls"
          value={stats.toolCalls.toLocaleString()}
          tone="cyan"
        />
        <MetricCard
          label="Unique Tools"
          value={stats.uniqueTools.toString()}
          tone="cyan"
        />
      </section>

      {/* Tab navigation */}
      <div className="flex gap-1 border-b border-neutral-800">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-[11px] uppercase tracking-wider font-semibold transition-colors ${
              activeTab === tab
                ? "text-emerald-400 border-b-2 border-emerald-500 -mb-px"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "Overview" && (
        <div className="space-y-6">
          <section className="border border-neutral-800 bg-neutral-950/40 overflow-hidden">
            <div className="bg-neutral-900/80 border-b border-neutral-800 p-4 flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
                Host / Model Overview
              </div>
              <div className="text-[9px] text-neutral-600 font-mono">
                {hostModelStats.length} host/model groups
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 text-[10px] uppercase tracking-widest text-neutral-500 font-mono bg-neutral-900/50">
                    <th className="px-4 py-3">Host</th>
                    <th className="px-4 py-3">Model</th>
                    <th className="px-4 py-3 text-right">Sessions</th>
                    <th className="px-4 py-3 text-right">User Typed (k)</th>
                    <th className="px-4 py-3 text-right">Base Context (M)</th>
                    <th className="px-4 py-3 text-right">Cached (M)</th>
                    <th className="px-4 py-3 text-right">Cache Write (M)</th>
                    <th className="px-4 py-3 text-right">Billable Out (M)</th>
                    <th className="px-4 py-3 text-right">Tool Out (M)</th>
                    <th className="px-4 py-3 text-right">Thinking (M)</th>
                    <th className="px-4 py-3 text-right">Calls</th>
                    <th className="px-4 py-3 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-900">
                  {hostModelStats.length === 0 ? (
                    <tr>
                      <td
                        colSpan={12}
                        className="px-4 py-8 text-center text-neutral-600 italic"
                      >
                        No data.
                      </td>
                    </tr>
                  ) : (
                    hostModelStats.map(
                      (row: DashboardHostModelOverview, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-neutral-800/20 transition-colors"
                        >
                          <td className="px-4 py-2 font-mono text-cyan-300/80">
                            {row.host}
                          </td>
                          <td className="px-4 py-2 font-mono text-neutral-400">
                            {row.model}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-400">
                            {row.sessions.toLocaleString()}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-emerald-300/80">
                            {(row.user_typed_tokens / 1000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-emerald-400/80">
                            {(row.base_context_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-red-400/80">
                            {(row.cached_prompt_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-orange-400/80">
                            {(row.cache_write_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-violet-400/80">
                            {(row.billable_output_tokens / 1_000_000).toFixed(
                              1
                            )}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-amber-400/80">
                            {(row.tool_output_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-cyan-400/80">
                            {(row.thinking_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-400">
                            {row.tool_calls.toLocaleString()}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-emerald-300 font-bold">
                            ${row.cost.toFixed(2)}
                          </td>
                        </tr>
                      )
                    )
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <CostDriversChart stats={stats} />

          <section className="border border-neutral-800 bg-neutral-950/40">
            <div className="bg-neutral-900/80 border-b border-neutral-800 p-4">
              <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
                Cost Drivers Ranking
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 text-[10px] uppercase tracking-widest text-neutral-500 font-mono bg-neutral-900/50">
                    <th className="px-4 py-3">Rank</th>
                    <th className="px-4 py-3">Tool</th>
                    <th className="px-4 py-3 text-right">Calls</th>
                    <th className="px-4 py-3 text-right">Output (M)</th>
                    <th className="px-4 py-3 text-right">Out/Call</th>
                    <th className="px-4 py-3 text-right">Est. Cost</th>
                    <th className="px-4 py-3 text-right">Cost/Call</th>
                    <th className="px-4 py-3 text-right">% Total</th>
                    <th className="px-4 py-3">Hint</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-900">
                  {costDriversData.length === 0 ? (
                    <tr>
                      <td
                        colSpan={9}
                        className="px-4 py-8 text-center text-neutral-600 italic"
                      >
                        No tool usage found.
                      </td>
                    </tr>
                  ) : (
                    costDriversData.map((item, i) => (
                      <tr
                        key={i}
                        className="hover:bg-neutral-800/20 transition-colors"
                      >
                        <td className="px-4 py-3 font-mono text-neutral-600">
                          {i + 1}
                        </td>
                        <td className="px-4 py-3 font-medium text-neutral-300">
                          {item.tool}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-neutral-400">
                          {(item.calls || 0).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-neutral-400">
                          {(item.tokens / 1_000_000).toFixed(1)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-neutral-400">
                          {item.tokens / (item.calls || 1) > 10_000
                            ? `${(item.tokens / (item.calls || 1) / 1000).toFixed(0)}k`
                            : (item.tokens / (item.calls || 1)).toFixed(0)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-amber-300/80">
                          ${item.cost.toFixed(2)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-amber-300/80">
                          ${item.costPerCall.toFixed(4)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <span className="font-mono text-[10px] text-neutral-500">
                              {(
                                (item.tokens / (stats.toolOutputTokens || 1)) *
                                100
                              ).toFixed(1)}
                              %
                            </span>
                            <div className="w-12 h-1 bg-neutral-900 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-amber-500/50"
                                style={{
                                  width: `${(item.tokens / (stats.toolOutputTokens || 1)) * 100}%`,
                                }}
                              />
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-[10px] text-neutral-500 italic">
                          Review output size
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="border border-neutral-800 bg-neutral-950/40">
            <div className="bg-neutral-900/80 border-b border-neutral-800 p-4 flex items-center justify-between">
              <div className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold">
                Full Data Table
              </div>
              <div className="relative">
                <input
                  type="text"
                  placeholder="Search Tool / Sub-command"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="bg-neutral-900 border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 focus:outline-none focus:border-emerald-500 w-64 pl-8"
                />
                <svg
                  className="absolute left-2.5 top-2 w-3.5 h-3.5 text-neutral-600"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 text-[10px] uppercase tracking-widest text-neutral-500 font-mono bg-neutral-900/50">
                    <th className="px-4 py-3">Agent</th>
                    <th className="px-4 py-3">Model</th>
                    <th className="px-4 py-3">Category</th>
                    <th className="px-4 py-3">Tool</th>
                    <th className="px-4 py-3">Sub-command</th>
                    <th className="px-4 py-3 text-right">Calls</th>
                    <th className="px-4 py-3 text-right">In (M)</th>
                    <th className="px-4 py-3 text-right">Out (M)</th>
                    <th className="px-4 py-3 text-right">Out/Call</th>
                    <th className="px-4 py-3 text-right">Est. Cost</th>
                    <th className="px-4 py-3 text-right">Cost/Call</th>
                    <th className="px-4 py-3 text-right">% Total</th>
                    <th className="px-4 py-3">Date Range</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-900">
                  {tableData.length === 0 ? (
                    <tr>
                      <td
                        colSpan={13}
                        className="px-4 py-8 text-center text-neutral-600 italic"
                      >
                        No records found.
                      </td>
                    </tr>
                  ) : (
                    tableData.map((item, i) => {
                      const dr =
                        item.first_seen && item.last_seen
                          ? `${new Date(item.first_seen).toLocaleDateString("en-GB")} – ${new Date(item.last_seen).toLocaleDateString("en-GB")}`
                          : "—";
                      return (
                        <tr
                          key={i}
                          className="hover:bg-neutral-800/20 transition-colors"
                        >
                          <td className="px-4 py-2 font-mono text-neutral-400">
                            {item.agent}
                          </td>
                          <td className="px-4 py-2 font-mono text-neutral-500 text-[10px]">
                            {item.model || "—"}
                          </td>
                          <td className="px-4 py-2">
                            <span
                              className={`text-[9px] px-1.5 py-0.5 border ${
                                item.category.includes("Optimized")
                                  ? "border-emerald-900/50 text-emerald-400 bg-emerald-950/20"
                                  : "border-neutral-800 text-neutral-500 bg-neutral-900/20"
                              }`}
                            >
                              {item.category}
                            </span>
                          </td>
                          <td className="px-4 py-2 font-medium text-neutral-300">
                            {item.tool_name}
                          </td>
                          <td className="px-4 py-2 text-neutral-500 font-mono italic">
                            {item.sub_command || "—"}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-400">
                            {(item.call_count ?? 1).toLocaleString()}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-400">
                            {(item.input_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-400">
                            {(item.output_tokens / 1_000_000).toFixed(1)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-500">
                            {(item.outPerCall / 1000).toFixed(0)}k
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-emerald-500/80">
                            ${(item.cost || 0).toFixed(2)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-500">
                            $
                            {(
                              (item.cost || 0) / (item.call_count || 1)
                            ).toFixed(4)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-neutral-500">
                            {item.pctOfTotal.toFixed(1)}%
                          </td>
                          <td className="px-4 py-2 text-neutral-600 text-[10px]">
                            {dr}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}

      {/* Timeline tab */}
      {activeTab === "Timeline" && (
        <div className="space-y-6">
          {dashLoading ? (
            <div className="text-neutral-500 italic text-sm animate-pulse">
              Loading...
            </div>
          ) : dashboard ? (
            <>
              <DailyChart daily={dashboard.daily} />
              <div className="grid md:grid-cols-2 gap-6">
                <ByHostTable byHost={dashboard.by_host} />
                <ByModelTable byModel={dashboard.by_model} />
              </div>
            </>
          ) : (
            <div className="text-neutral-600 italic text-sm">
              Data unavailable.
            </div>
          )}
        </div>
      )}

      {/* Domains tab */}
      {activeTab === "Domains" && (
        <div className="space-y-6">
          {dashLoading ? (
            <div className="text-neutral-500 italic text-sm animate-pulse">
              Loading...
            </div>
          ) : dashboard ? (
            <ByProjectTable domains={dashboard.by_domain} />
          ) : (
            <div className="text-neutral-600 italic text-sm">
              Data unavailable.
            </div>
          )}
        </div>
      )}

      {/* Tool Breakdown tab */}
      {activeTab === "Tool Breakdown" && (
        <div className="space-y-6">
          {dashLoading ? (
            <div className="text-neutral-500 italic text-sm animate-pulse">
              Loading...
            </div>
          ) : dashboard ? (
            <>
              <ToolTable
                title="File & Search Tools"
                tools={dashboard.tools.core}
                color="bg-blue-500/50"
              />
              <ToolTable
                title="Bash & Exec Usage"
                tools={dashboard.tools.shell}
                color="bg-yellow-500/50"
              />
              <ToolTable
                title="MCP Tool Usage"
                tools={dashboard.tools.mcp}
                color="bg-purple-500/50"
              />
            </>
          ) : (
            <div className="text-neutral-600 italic text-sm">
              Data unavailable.
            </div>
          )}
        </div>
      )}

      {/* Analysis tab */}
      {activeTab === "Analysis" && (
        <div className="space-y-6">
          {dashLoading ? (
            <div className="text-neutral-500 italic text-sm animate-pulse">
              Loading...
            </div>
          ) : dashboard ? (
            <>
              <SavingsInsights dashboard={dashboard} />
            </>
          ) : (
            <div className="text-neutral-600 italic text-sm">
              Data unavailable.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
