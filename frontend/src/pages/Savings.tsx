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

  const hasData = data.total_naive_tokens > 0;
  const sortedLevers = Object.entries(data.per_lever)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value }));
  const sparkValues = data.by_day.map((d) => {
    if (d.naive <= 0) return 0;
    return Math.max(0, Math.round((1 - d.actual / d.naive) * 100));
  });
  const maxLever = sortedLevers[0]?.value ?? 0;

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
            would have been {usdFmt.format(data.would_have_cost_usd ?? 0)}
          </div>
        </div>
        <div className="border border-neutral-800 bg-neutral-950/50 p-4">
          <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-400/70 mb-1">
            Total Calls
          </div>
          <div className="text-2xl font-semibold text-neutral-200">
            {fmt.format(data.total_calls ?? 0)}
          </div>
          <div className="text-xs text-neutral-500 mt-1">LLM calls tracked</div>
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
        </>
      )}

      <section className="border border-neutral-800 bg-neutral-950/60 p-5">
        <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-2">
          Why this matters
        </h2>
        <p className="text-sm text-neutral-300 leading-relaxed">
          This view breaks savings down by lever so regressions are visible
          immediately, not hidden in a single aggregate metric. See{" "}
          <a
            className="text-cyan-300 hover:text-cyan-200"
            href="https://baseline.com"
            target="_blank"
            rel="noreferrer noopener"
          >
            baseline
          </a>{" "}
          and the
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
