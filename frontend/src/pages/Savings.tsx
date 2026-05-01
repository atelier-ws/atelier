import { useEffect, useState } from "react";
import type { CallEntry, SavingsSummary } from "../api";
import { api } from "../api";

const fmt = new Intl.NumberFormat();
const usd = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
  }).format(n);

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border-b border-amber-400/30 py-3">
      <div className="text-xs uppercase tracking-widest text-amber-400 font-mono">
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1 text-neutral-200">{value}</div>
      {hint && <div className="text-xs text-neutral-500 mt-1">{hint}</div>}
    </div>
  );
}

export default function Savings() {
  const [data, setData] = useState<SavingsSummary | null>(null);
  const [calls, setCalls] = useState<CallEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.savings(), api.calls(200)])
      .then(([s, c]) => {
        setData(s);
        setCalls(c);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!data || !calls) return <div className="text-neutral-500">Loading…</div>;

  return (
    <div>
      {/* Aggregate */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-x-12 mb-8">
        <Stat label="Operations Tracked" value={fmt.format(data.operations_tracked)} />
        <Stat label="Total Calls" value={fmt.format(data.total_calls)} />
        <Stat label="Would Have Cost" value={usd(data.would_have_cost_usd)} hint="sum of baselines × calls" />
        <Stat
          label="Saved"
          value={`${usd(data.saved_usd)} (${data.saved_pct}%)`}
          hint="baseline − actual, summed across operations"
        />
      </div>

      {/* Per-operation breakdown */}
      <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-4">
        Per-operation savings
      </h2>
      <div className="overflow-x-auto mb-10 border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-neutral-500 border-b border-neutral-800 bg-neutral-900/20">
              <th className="py-2 px-4 font-mono text-[10px]">op_key</th>
              <th className="py-2 px-4 font-mono text-[10px]">domain</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">calls</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">baseline</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">last</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">current</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">Δ vs last</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">Δ vs baseline</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">% saved</th>
              <th className="py-2 px-4 font-mono text-[10px]">task</th>
            </tr>
          </thead>
          <tbody>
            {data.per_operation.map((r) => (
              <tr key={r.op_key} className="border-b border-neutral-800/50 hover:bg-neutral-900/30 transition">
                <td className="py-2 px-4 font-mono text-xs text-neutral-400">{r.op_key}</td>
                <td className="py-2 px-4 text-neutral-300">{r.domain || "-"}</td>
                <td className="py-2 px-4 text-right text-neutral-300">{r.calls_count}</td>
                <td className="py-2 px-4 text-right text-neutral-300">{usd(r.baseline_cost_usd)}</td>
                <td className="py-2 px-4 text-right text-neutral-300">{usd(r.last_cost_usd)}</td>
                <td className="py-2 px-4 text-right text-neutral-300">{usd(r.current_cost_usd)}</td>
                <td
                  className="py-2 px-4 text-right text-neutral-300"
                  style={{ color: r.delta_vs_last_usd > 0 ? "#fbbf24" : undefined }}
                >
                  {usd(r.delta_vs_last_usd)}
                </td>
                <td
                  className="py-2 px-4 text-right text-neutral-300"
                  style={{ color: r.delta_vs_base_usd > 0 ? "#fbbf24" : undefined }}
                >
                  {usd(r.delta_vs_base_usd)}
                </td>
                <td className="py-2 px-4 text-right text-neutral-300">{r.pct_vs_base.toFixed(1)}%</td>
                <td className="py-2 px-4 text-neutral-400 text-xs font-mono">{r.task_sample}</td>
              </tr>
            ))}
            {data.per_operation.length === 0 && (
              <tr>
                <td colSpan={10} className="py-4 px-4 text-neutral-500 text-center">
                  No cost history yet. Run <code className="font-mono bg-neutral-900 px-1">atelier benchmark</code> to populate it.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Per-call log with lessons-used (the "learning" the user asked to see) */}
      <h2 className="text-xs uppercase tracking-widest font-mono text-amber-400 mb-4">
        Recent calls — each row shows lessons (ReasonBlock IDs) injected
      </h2>
      <div className="overflow-x-auto border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-neutral-500 border-b border-neutral-800 bg-neutral-900/20">
              <th className="py-2 px-4 font-mono text-[10px]">when</th>
              <th className="py-2 px-4 font-mono text-[10px]">domain</th>
              <th className="py-2 px-4 font-mono text-[10px]">op</th>
              <th className="py-2 px-4 font-mono text-[10px]">model</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">in</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">out</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">cache</th>
              <th className="py-2 px-4 text-right font-mono text-[10px]">cost</th>
              <th className="py-2 px-4 font-mono text-[10px]">lessons</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((c, i) => (
              <tr
                key={`${c.run_id}-${i}`}
                className="border-b border-neutral-800/50 hover:bg-neutral-900/30 transition align-top"
              >
                <td className="py-2 px-4 text-xs text-neutral-400 font-mono">{c.at.slice(0, 19)}</td>
                <td className="py-2 px-4 text-neutral-300">{c.domain || "-"}</td>
                <td className="py-2 px-4 text-neutral-300 text-xs">{c.operation}</td>
                <td className="py-2 px-4 text-xs text-neutral-300">{c.model}</td>
                <td className="py-2 px-4 text-right text-neutral-300 text-xs">{fmt.format(c.input_tokens)}</td>
                <td className="py-2 px-4 text-right text-neutral-300 text-xs">{fmt.format(c.output_tokens)}</td>
                <td className="py-2 px-4 text-right text-neutral-300 text-xs">{fmt.format(c.cache_read_tokens)}</td>
                <td className="py-2 px-4 text-right text-neutral-300 text-xs">{usd(c.cost_usd)}</td>
                <td className="py-2 px-4 text-xs text-neutral-400 font-mono">
                  {c.lessons_used.length === 0 ? (
                    <span className="text-neutral-500">— none —</span>
                  ) : (
                    <span className="font-mono text-amber-400">
                      {c.lessons_used.join(", ")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {calls.length === 0 && (
              <tr>
                <td colSpan={9} className="py-4 text-neutral-500">
                  No recorded calls.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
