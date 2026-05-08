import { useEffect, useState } from "react";
import LeverBar from "../components/LeverBar";
import SavingsTimeChart from "../components/SavingsTimeChart";
import type { SavingsSummaryV2 } from "../api";
import { api } from "../api";

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
});

const fmt = new Intl.NumberFormat();

function toTitle(label: string): string {
  return label
    .split(/[_\s:-]+/)
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const width = 240;
  const height = 56;
  const maxVal = Math.max(1, ...values);
  const points = values
    .map((value, i) => {
      const x = (i * width) / Math.max(1, values.length - 1);
      const y = height - (value / maxVal) * height;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full max-w-[240px]"
      aria-label="reduction sparkline"
    >
      <polyline fill="none" stroke="#06b6d4" strokeWidth="3" points={points} />
    </svg>
  );
}

function EmptyState() {
  return (
    <div className="border border-neutral-800 bg-neutral-950/70 p-6 text-neutral-300">
      <h2 className="font-mono text-lg text-neutral-100 mb-2">
        No savings telemetry yet
      </h2>
      <p className="text-sm text-neutral-400">
        Run any task with{" "}
        <code className="bg-neutral-900 px-1">atelier-mcp</code> enabled to
        start collecting savings telemetry.
      </p>
    </div>
  );
}

export default function Savings() {
  const [data, setData] = useState<SavingsSummaryV2 | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .savingsSummary(14)
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!data) return <div className="text-neutral-500">Loading…</div>;

  const latestBenchmark = data.latest_benchmark ?? null;
  const hasData = data.total_naive_tokens > 0 || latestBenchmark !== null;
  const sortedLevers = Object.entries(data.per_lever)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value }));
  const sparkValues = data.by_day.map((d) => {
    if (d.naive <= 0) return 0;
    return Math.max(0, Math.round((1 - d.actual / d.naive) * 100));
  });
  const maxLever = sortedLevers[0]?.value ?? 0;
  const topSources = data.top_sources ?? [];

  return (
    <div className="space-y-8">
      <section className="border border-cyan-900/60 bg-gradient-to-r from-cyan-950/60 to-neutral-950 p-6">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div>
            <div className="text-[11px] font-mono uppercase tracking-[0.22em] text-cyan-300/80">
              Token Reduction
            </div>
            <div className="text-6xl md:text-7xl font-semibold leading-none text-cyan-200 mt-2">
              {data.reduction_pct.toFixed(1)}%
            </div>
            <p className="text-sm text-neutral-400 mt-3">
              {fmt.format(data.total_naive_tokens)} naive tokens vs{" "}
              {fmt.format(data.total_actual_tokens)} actual over the last{" "}
              {data.window_days} days.
            </p>
          </div>
          <div className="w-full md:w-auto">
            <Sparkline values={sparkValues} />
            <p className="font-mono text-[10px] text-neutral-500 uppercase tracking-wider mt-2">
              Daily reduction trend
            </p>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="border border-emerald-900/60 bg-emerald-950/30 p-4">
          <div className="text-[10px] font-mono uppercase tracking-widest text-emerald-400/70 mb-1">
            Cost Saved
          </div>
          <div className="text-2xl font-semibold text-emerald-300">
            {usdFmt.format(data.saved_usd ?? 0)}
          </div>
          {(data.saved_pct ?? 0) > 0 && (
            <div className="text-xs text-emerald-400/60 mt-1">
              {(data.saved_pct ?? 0).toFixed(1)}% vs baseline
            </div>
          )}
        </div>
        <div className="border border-neutral-800 bg-neutral-950/50 p-4">
          <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-400/70 mb-1">
            Actual Cost
          </div>
          <div className="text-2xl font-semibold text-neutral-200">
            {usdFmt.format(data.actually_cost_usd ?? 0)}
          </div>
            <div className="text-xs text-neutral-500 mt-1">
              live estimate {usdFmt.format(data.live_saved_usd ?? 0)}
            </div>
          </div>
        <div className="border border-neutral-800 bg-neutral-950/50 p-4">
          <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-400/70 mb-1">
            Calls Saved
          </div>
          <div className="text-2xl font-semibold text-neutral-200">
            {fmt.format(data.live_calls_saved ?? 0)}
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {fmt.format(data.total_calls ?? 0)} LLM calls tracked
          </div>
        </div>
        <div className="border border-neutral-800 bg-neutral-950/50 p-4">
          <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-400/70 mb-1">
            Context Reduction
          </div>
          <div className="text-2xl font-semibold text-neutral-200">
            {data.reduction_pct.toFixed(1)}%
          </div>
          <div className="text-xs text-neutral-500 mt-1">
            {fmt.format(data.total_actual_tokens)} actual tokens
          </div>
        </div>
      </section>

      {!hasData ? (
        <EmptyState />
      ) : (
        <>
          <section className="border border-neutral-800 bg-neutral-950/70 p-5">
            <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-4">
              Per-lever savings
            </h2>
            <div className="space-y-4">
              {sortedLevers.map((lever) => (
                <LeverBar
                  key={lever.label}
                  label={lever.label}
                  value={lever.value}
                  maxValue={maxLever}
                />
              ))}
            </div>
          </section>

            <SavingsTimeChart data={data.by_day} />

          {latestBenchmark && (
            <section className="border border-cyan-900/50 bg-cyan-950/20 p-5">
              <h2 className="text-xs uppercase tracking-widest font-mono text-cyan-300 mb-4">
                Latest paired benchmark
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500">
                    Token reduction
                  </div>
                  <div className="text-2xl font-semibold text-cyan-200">
                    {latestBenchmark.reduction_pct.toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500">
                    Cost saved
                  </div>
                  <div className="text-2xl font-semibold text-emerald-300">
                    {usdFmt.format(latestBenchmark.cost_saved_usd)}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500">
                    Tasks
                  </div>
                  <div className="text-2xl font-semibold text-neutral-200">
                    {fmt.format(latestBenchmark.n_prompts)}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500">
                    Success
                  </div>
                  <div className="text-2xl font-semibold text-neutral-200">
                    {(latestBenchmark.atelier_success_rate * 100).toFixed(0)}%
                  </div>
                </div>
              </div>
              <p className="mt-3 text-xs text-neutral-500">
                Real paired command run: baseline{" "}
                {fmt.format(latestBenchmark.total_tokens_baseline)} tokens vs
                Atelier-enabled{" "}
                {fmt.format(latestBenchmark.total_tokens_atelier)} tokens.
              </p>
            </section>
          )}

          {topSources.length > 0 && (
            <section className="border border-neutral-800 bg-neutral-950/70 p-5">
              <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-4">
                Top savings sources
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-[10px] uppercase tracking-widest text-neutral-500">
                    <tr>
                      <th className="pb-2 pr-4">Lever</th>
                      <th className="pb-2 pr-4">Tool</th>
                      <th className="pb-2 pr-4 text-right">Calls</th>
                      <th className="pb-2 pr-4 text-right">Tokens</th>
                      <th className="pb-2 text-right">Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topSources.map((source) => (
                      <tr
                        key={`${source.lever}:${source.tool_name}`}
                        className="border-t border-neutral-900 text-neutral-300"
                      >
                        <td className="py-2 pr-4 font-semibold text-cyan-200">
                          {toTitle(source.lever)}
                        </td>
                        <td className="py-2 pr-4 text-neutral-400">
                          {source.tool_name}
                        </td>
                        <td className="py-2 pr-4 text-right">
                          {fmt.format(source.calls_saved)}
                        </td>
                        <td className="py-2 pr-4 text-right">
                          {fmt.format(source.tokens_saved)}
                        </td>
                        <td className="py-2 text-right text-emerald-300">
                          {usdFmt.format(source.cost_saved_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-neutral-500">
                These rows use an equivalent-call estimator: search, edit, and
                SQL tools count the built-in calls they replace, then apply live
                token constants to estimate avoided cost.
              </p>
            </section>
          )}
        </>
      )}

      <section className="border border-neutral-800 bg-neutral-950/60 p-5">
        <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-2">
          Why this matters
        </h2>
        <p className="text-sm text-neutral-300 leading-relaxed">
          This view breaks savings down by lever so regressions are visible
          immediately, not hidden in a single aggregate metric. See the
          <a
            className="text-cyan-300 hover:text-cyan-200 ml-1"
            href="/docs/architecture/IMPLEMENTATION_PLAN_V2.md"
            target="_blank"
            rel="noreferrer noopener"
          >
            V2 implementation plan
          </a>{" "}
          for the methodology.
        </p>
      </section>
    </div>
  );
}
