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

interface FeatureItem {
  icon: string;
  title: string;
  desc: string;
}

const FEATURES: FeatureItem[] = [
  {
    icon: "🧠",
    title: "Reasoning reuse",
    desc: "Retrieve and inject known procedures (ReasonBlocks) into agent context before runs — skip dead-end exploration the agent already solved.",
  },
  {
    icon: "🔍",
    title: "Semantic memory",
    desc: "FTS + optional vector search over procedures and traces — surface the most relevant blocks for any task, any domain.",
  },
  {
    icon: "🔄",
    title: "Loop detection",
    desc: "Monitor for thrashing, second-guessing, and budget exhaustion — interrupt before the agent wastes tokens re-exploring the same path.",
  },
  {
    icon: "🛡️",
    title: "Tool supervision",
    desc: "Cached reads, memoized searches, injection-guarded grep — safe and efficient tool calls with no redundant I/O.",
  },
  {
    icon: "🗜️",
    title: "Context compression",
    desc: "Ledger summarisation for long-running tasks — compress context history while preserving verified facts and decision points.",
  },
  {
    icon: "✅",
    title: "Rubric verification",
    desc: "Gate agent plans and outputs against domain-specific rubrics — block bad plans before execution, enforce quality checks after.",
  },
  {
    icon: "🚨",
    title: "Failure rescue",
    desc: "Record observable execution traces, detect recurring failures, surface targeted rescue procedures — stop agents from retrying known dead ends.",
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

export default function Overview() {
  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .overview()
      .then(setStats)
      .catch((e) => setErr(String(e)));
  }, []);

  // Core features to highlight on overview

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
        <h2 className="text-xs uppercase tracking-widest text-neutral-500 mb-4 font-mono">
          What it does
        </h2>
        <div className="space-y-px border border-neutral-800">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className="flex items-start gap-4 px-5 py-3 bg-neutral-900/30 hover:bg-neutral-900/60 transition-colors border-b border-neutral-800/60 last:border-b-0"
            >
              <span className="text-lg flex-shrink-0 mt-0.5">{f.icon}</span>
              <div>
                <span className="font-mono font-bold text-neutral-200 text-[13px]">
                  {f.title}
                </span>
                <span className="text-neutral-600 mx-2">—</span>
                <span className="text-xs text-neutral-400">{f.desc}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Navigation Hint */}
      <section className="border border-neutral-800 bg-neutral-900/30 p-4">
        <p className="text-xs text-neutral-400 font-mono">
          <span className="text-amber-400">❯</span> explore in the tabs:{" "}
          <strong>Trace</strong>, <strong>Learnings</strong>,{" "}
          <strong>Savings</strong>, <strong>Agents</strong>,{" "}
          <strong>Tools</strong>, <strong>Gateway</strong>.
        </p>
      </section>
    </div>
  );
}
