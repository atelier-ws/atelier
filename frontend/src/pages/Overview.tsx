import { useEffect, useState } from "react";
import type {
  AnalyticsDashboard,
  InsightsWindow,
  InsightsSessionSummary,
  OverviewStats,
  TraceListResponse,
} from "../api";
import { api } from "../api";
import { Card, MetricCard, SectionHeader } from "../components/WorkbenchUI";
import { useTimeRange } from "../lib/TimeRangeContext";

const fmt = new Intl.NumberFormat();
const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

const usd = (n: number) => usdFmt.format(n);

type OverviewTone = "amber" | "cyan" | "emerald" | "violet";

interface OverviewData {
  stats: OverviewStats | null;
  traces: TraceListResponse | null;
  analytics: AnalyticsDashboard | null;
  insights: InsightsWindow | null;
}

interface SnapshotChipData {
  label: string;
  value: string;
  detail: string;
  tone: OverviewTone;
}

const EMPTY_DATA: OverviewData = {
  stats: null,
  traces: null,
  analytics: null,
  insights: null,
};

const TONE_STYLES: Record<
  OverviewTone,
  { chip: string; value: string }
> = {
  amber: { chip: "border-amber-900/40 bg-amber-950/20", value: "text-amber-200" },
  cyan: { chip: "border-cyan-900/40 bg-cyan-950/20", value: "text-cyan-100" },
  emerald: { chip: "border-emerald-900/40 bg-emerald-950/20", value: "text-emerald-100" },
  violet: { chip: "border-violet-900/40 bg-violet-950/20", value: "text-violet-100" },
};

function SnapshotChip({ label, value, detail, tone }: SnapshotChipData) {
  const palette = TONE_STYLES[tone];
  return (
    <div className={`border px-3 py-3 ${palette.chip}`}>
      <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">
        {label}
      </div>
      <div className={`mt-2 text-xl font-semibold ${palette.value}`}>{value}</div>
      <div className="mt-1 text-xs leading-relaxed text-neutral-500">{detail}</div>
    </div>
  );
}

function formatMetric(
  value: number | null | undefined,
  formatter: (value: number) => string = (input) => fmt.format(input)
): string {
  if (value == null || !Number.isFinite(value)) {
    return "…";
  }
  return formatter(value);
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function Overview() {
  const [data, setData] = useState<OverviewData>(EMPTY_DATA);
  const [err, setErr] = useState<string | null>(null);
  const { days, range } = useTimeRange();

  useEffect(() => {
    let active = true;

    void Promise.allSettled([
      api.overview(days),
      api.traces(1, 0, undefined, undefined, undefined, days),
      api.analyticsDashboard(days),
      api.insightsWindow(range),
    ]).then((results) => {
      if (!active) return;

      const [statsResult, tracesResult, analyticsResult, insightsResult] =
        results;

      const nextData: OverviewData = {
        stats: statsResult.status === "fulfilled" ? statsResult.value : null,
        traces: tracesResult.status === "fulfilled" ? tracesResult.value : null,
        analytics:
          analyticsResult.status === "fulfilled" ? analyticsResult.value : null,
        insights:
          insightsResult.status === "fulfilled" ? insightsResult.value : null,
      };

      setData(nextData);

      const loaded = Object.values(nextData).some(Boolean);
      if (loaded) {
        setErr(null);
        return;
      }

      const firstFailure = results.find(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected"
      );
      setErr(firstFailure ? errorMessage(firstFailure.reason) : "Unavailable");
    });

    return () => {
      active = false;
    };
  }, [days, range]);

  const analyticsTools = data.analytics
    ? [
        ...data.analytics.tools.core,
        ...data.analytics.tools.shell,
        ...data.analytics.tools.mcp,
      ]
    : [];
  const analyticsToolCalls = analyticsTools.reduce(
    (sum, tool) => sum + tool.calls,
    0
  );

  const snapshotChips: SnapshotChipData[] = [
    {
      label: "Sessions",
      value: formatMetric(
        data.insights?.session_count ?? data.stats?.total_traces
      ),
      detail: `Last ${range}`,
      tone: "cyan",
    },
    {
      label: "Total Cost",
      value:
        data.insights?.total_cost_usd != null
          ? usd(data.insights.total_cost_usd)
          : formatMetric(data.stats?.estimated_total_cost_usd, usd),
      detail: data.insights ? `${range} window` : "Estimated from tokens",
      tone: "amber",
    },
    {
      label: "Savings",
      value:
        data.insights?.total_atelier_savings_usd != null
          ? usd(data.insights.total_atelier_savings_usd)
          : "…",
      detail: "Atelier-attributed",
      tone: "emerald",
    },
    {
      label: "Active Hosts",
      value: data.traces
        ? fmt.format(data.traces.metrics.hosts.length)
        : "…",
      detail: data.traces
        ? `${fmt.format(data.traces.metrics.domains.length)} domains`
        : "Coverage pending",
      tone: "violet",
    },
  ];

  const hasAnyData =
    data.insights !== null || data.stats !== null || data.analytics !== null;

  return (
    <div className="space-y-6">
      {err && <div className="text-sm text-red-400">{err}</div>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {snapshotChips.map((chip) => (
          <SnapshotChip key={chip.label} {...chip} />
        ))}
      </section>

      {/* Primary content: session activity from insights */}
      {data.insights !== null && data.insights.session_count > 0 && (
        <section className="space-y-3">
          <SectionHeader title="Session Activity" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="border border-neutral-800 bg-neutral-950/60 p-4">
              <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">
                Sessions
              </div>
              <div className="mt-2 text-xl font-semibold text-violet-200">
                {data.insights.session_count}
              </div>
            </div>
            <div className="border border-neutral-800 bg-neutral-950/60 p-4">
              <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">
                Total Cost
              </div>
              <div className="mt-2 text-xl font-semibold text-amber-200">
                {usd(data.insights.total_cost_usd)}
              </div>
            </div>
            <div className="border border-neutral-800 bg-neutral-950/60 p-4">
              <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">
                Saved
              </div>
              <div className="mt-2 text-xl font-semibold text-emerald-200">
                {usd(data.insights.total_atelier_savings_usd)}
              </div>
            </div>
            <div className="border border-neutral-800 bg-neutral-950/60 p-4">
              <div className="text-[10px] font-mono uppercase tracking-widest text-neutral-500">
                Avg Session Cost
              </div>
              <div className="mt-2 text-xl font-semibold text-neutral-100">
                {data.insights.session_count > 0
                  ? usd(
                      data.insights.total_cost_usd /
                        data.insights.session_count
                    )
                  : "—"}
              </div>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            {data.insights.top_sessions.length > 0 && (
              <Card className="p-4">
                <h3 className="mb-3 text-[10px] font-mono font-bold uppercase tracking-widest text-neutral-500">
                  Top Cost Sessions
                </h3>
                <div className="space-y-2">
                  {data.insights.top_sessions.map(
                    (s: InsightsSessionSummary) => {
                      const maxCost =
                        data.insights!.top_sessions[0]?.cost_usd ?? 1;
                      return (
                        <div
                          key={s.session_id}
                          className="flex flex-col gap-0.5"
                        >
                          <div className="flex justify-between text-xs">
                            <span className="font-mono text-violet-400/80">
                              {s.session_id.slice(0, 14)}…
                            </span>
                            <span className="text-amber-300">
                              {usd(s.cost_usd)}
                            </span>
                          </div>
                          <div className="h-1 w-full bg-neutral-800">
                            <div
                              className="h-full bg-violet-600"
                              style={{
                                width: `${
                                  maxCost > 0
                                    ? Math.min(
                                        100,
                                        (s.cost_usd / maxCost) * 100
                                      )
                                    : 0
                                }%`,
                              }}
                            />
                          </div>
                        </div>
                      );
                    }
                  )}
                </div>
              </Card>
            )}

            {Object.keys(data.insights.cost_by_vendor).length > 0 && (
              <Card className="p-4">
                <h3 className="mb-3 text-[10px] font-mono font-bold uppercase tracking-widest text-neutral-500">
                  Cost by Vendor
                </h3>
                <div className="space-y-2">
                  {Object.entries(data.insights.cost_by_vendor)
                    .sort((a, b) => b[1] - a[1])
                    .map(([vendor, cost]) => {
                      const maxCost = Math.max(
                        ...Object.values(data.insights!.cost_by_vendor)
                      );
                      return (
                        <div key={vendor} className="flex flex-col gap-0.5">
                          <div className="flex justify-between text-xs">
                            <span className="text-neutral-300">{vendor}</span>
                            <span className="text-amber-300">{usd(cost)}</span>
                          </div>
                          <div className="h-1 w-full bg-neutral-800">
                            <div
                              className="h-full bg-amber-600"
                              style={{
                                width: `${
                                  maxCost > 0
                                    ? Math.min(100, (cost / maxCost) * 100)
                                    : 0
                                }%`,
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                </div>
              </Card>
            )}

            {data.insights.opportunities.length > 0 && (
              <Card tone="amber" className="p-4">
                <h3 className="mb-2 text-[10px] font-mono font-bold uppercase tracking-widest text-amber-500">
                  Optimization Opportunities
                </h3>
                <ul className="space-y-2">
                  {data.insights.opportunities.map((opp) => (
                    <li key={opp.kind} className="text-xs">
                      <div className="flex justify-between">
                        <span className="font-semibold text-neutral-200">
                          {opp.kind}
                        </span>
                        <span className="text-emerald-400">
                          {usd(opp.estimated_savings_usd)}
                        </span>
                      </div>
                      <p className="mt-0.5 text-neutral-500">{opp.message}</p>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </section>
      )}

      {/* Coverage — always shown when we have any data */}
      {hasAnyData && (
        <section className="space-y-3">
          <SectionHeader title="Coverage" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard
              label="Total Traces"
              value={formatMetric(data.stats?.total_traces)}
            />
            <MetricCard
              label="Active Hosts"
              value={
                data.traces
                  ? fmt.format(data.traces.metrics.hosts.length)
                  : "…"
              }
            />
            <MetricCard
              label="Domains"
              value={
                data.traces
                  ? fmt.format(data.traces.metrics.domains.length)
                  : "…"
              }
            />
            <MetricCard
              label="Failure Clusters"
              value={formatMetric(data.stats?.total_clusters)}
            />
          </div>
        </section>
      )}

      {/* Analytics quick summary — only when populated */}
      {data.analytics && data.analytics.summary.total_sessions > 0 && (
        <section className="space-y-3">
          <SectionHeader title="Analytics" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard
              label="Sessions"
              value={fmt.format(data.analytics.summary.total_sessions)}
            />
            <MetricCard
              label="Spend"
              value={usd(data.analytics.summary.total_cost)}
            />
            <MetricCard
              label="Tool Calls"
              value={fmt.format(analyticsToolCalls)}
            />
            <MetricCard
              label="Top Host"
              value={data.analytics.by_host[0]?.host ?? "—"}
            />
          </div>
        </section>
      )}

      {/* Empty state — no data at all */}
      {!hasAnyData && !err && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <p className="text-sm text-neutral-400">No activity data yet.</p>
          <p className="mt-2 text-xs text-neutral-600">
            Start using Atelier with your AI agent to see sessions, costs, and
            savings here.
          </p>
        </div>
      )}
    </div>
  );
}

