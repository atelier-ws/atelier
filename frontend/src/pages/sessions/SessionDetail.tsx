import { useEffect, useState, useMemo } from "react";
import {
  api,
  type Trace,
  type SessionReport,
  type RunInspectorData,
} from "../../api";
import { cx } from "../../components/WorkbenchUI";
import {
  fmtUsd,
  fmtTok,
  fmtDate,
  fmtDuration,
  parseInspectorData,
  groupTurns,
} from "./helpers";
import { StatusBadge } from "./StatusBadge";
import { FileDetail } from "./DiffView";
import { ConversationTurn, ToolCallDetail, CommandDetail } from "./TurnRenderers";

// ---------------------------------------------------------------------------
// Header stat chip
// ---------------------------------------------------------------------------

function HeaderStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "amber" | "emerald";
}) {
  return (
    <div className="flex-1 min-w-0 px-4 py-2 border-r last:border-0 border-neutral-800/40 hover:bg-neutral-800/20 transition-colors group">
      <div className="text-[8px] text-neutral-400 uppercase font-black tracking-widest mb-0.5 group-hover:text-neutral-500 transition-colors">
        {label}
      </div>
      <div
        className={cx(
          "text-[11px] font-bold font-mono truncate",
          tone === "amber"
            ? "text-amber-500/90"
            : tone === "emerald"
              ? "text-emerald-500/90"
              : "text-neutral-400"
        )}
      >
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right-panel helpers
// ---------------------------------------------------------------------------

function SidebarMetric({
  label,
  value,
  color = "text-neutral-400",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-[9px] text-neutral-400 font-mono uppercase font-bold">
        {label}
      </span>
      <span className={cx("text-[10px] font-mono font-black", color)}>
        {value}
      </span>
    </div>
  );
}

function SidebarList({
  title,
  items,
  color = "text-neutral-500",
}: {
  title: string;
  items: Array<string | { path: string; artifact_id?: string }>;
  color?: string;
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
        {title}
      </h3>
      <div className="space-y-1.5 font-mono text-[9px]">
        {items.map((item) => {
          const p = typeof item === "string" ? item : item.path;
          const artId = typeof item === "string" ? null : item.artifact_id;
          const isPath = p.startsWith("/");
          const canOpenRaw = Boolean(artId || isPath);
          const rawUrl = artId
            ? `/api/raw-artifacts/${artId}/content`
            : `/api/v1/files/content?path=${encodeURIComponent(p)}`;

          return (
            <div
              key={p}
              className={cx(
                "group/item flex items-center justify-between border-l border-neutral-800/60 pl-2 transition-colors",
                color
              )}
            >
              <span
                className="truncate flex-1 hover:text-neutral-300 cursor-default"
                title={p}
              >
                {p}
              </span>
              {canOpenRaw && (
                <div className="flex items-center gap-2 ml-2 opacity-0 group-hover/item:opacity-100 transition-opacity flex-shrink-0 bg-[#0a0a0a] px-1">
                  <a
                    href={rawUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[8px] text-neutral-400 hover:text-emerald-500 uppercase font-black flex items-center gap-1"
                    title="View raw content"
                  >
                    Raw <span className="text-[9px]">⎋</span>
                  </a>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main detail view
// ---------------------------------------------------------------------------

export function SessionExplorerDetail({ sessionId }: { sessionId: string }) {
  const [report, setReport] = useState<SessionReport | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [inspectorData, setInspectorData] = useState<RunInspectorData | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [allExpanded, setAllExpanded] = useState(false);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    setAllExpanded(false);
    Promise.all([
      api.sessionReport(sessionId).catch(() => null),
      api.trace(sessionId).catch(() => null),
      api.ledger(sessionId).catch(() => null),
    ])
      .then(([rep, tr, led]) => {
        setReport(rep);
        setTrace(tr);
        if (led) setInspectorData(parseInspectorData(sessionId, led));
        setLoading(false);
      })
      .catch((e) => {
        setErr(String(e));
        setLoading(false);
      });
  }, [sessionId]);

  const activeDurationSecs = useMemo(() => {
    if (
      !inspectorData?.conversations ||
      inspectorData.conversations.length === 0
    ) {
      return report?.duration_seconds || 0;
    }
    let ms = 0;
    let currentStart: number | null = null;
    for (const turn of inspectorData.conversations) {
      const at = new Date(turn.at || 0).getTime();
      if (turn.kind === "user_message") {
        currentStart = at;
      } else {
        if (currentStart !== null) {
          ms += at - currentStart;
          currentStart = at;
        } else {
          currentStart = at;
        }
      }
    }
    return ms / 1000;
  }, [inspectorData, report]);

  if (loading)
    return (
      <div className="flex flex-col items-center justify-center h-full space-y-4 bg-[#0a0a0a]">
        <div className="w-10 h-10 border border-purple-500/20 border-t-purple-500 rounded-full animate-spin" />
        <div className="text-[10px] text-neutral-400 uppercase tracking-[0.3em] font-mono animate-pulse">
          Reconstructing Ledger...
        </div>
      </div>
    );

  if (err)
    return (
      <div className="h-full flex items-center justify-center bg-[#0a0a0a] p-12 text-center">
        <div className="max-w-xs space-y-3">
          <div className="text-red-500 text-sm font-mono font-bold uppercase tracking-widest">
            Load Failure
          </div>
          <div className="text-neutral-400 text-xs font-mono leading-relaxed">
            {err}
          </div>
        </div>
      </div>
    );

  return (
    <div className="flex flex-col h-full bg-[#0a0a0a] relative animate-in fade-in duration-500">
      {/* Header */}
      <header className="flex-shrink-0 px-8 py-4 border-b border-neutral-800/80 bg-[#0d0d0d]/95 backdrop-blur-md sticky top-0 z-20 shadow-2xl">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-8">
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-center gap-3">
                {trace && (
                  <StatusBadge
                    status={trace.status}
                    className="text-[10px] rounded-none px-2 py-0"
                  />
                )}
                <h1 className="text-sm font-bold tracking-wide text-neutral-100 font-mono truncate uppercase">
                  {trace?.task || "Execution Detail"}
                </h1>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 text-[9px] text-neutral-400 font-mono font-bold uppercase">
                <span>SESSION: {sessionId}</span>
                <span>•</span>
                <span>
                  {fmtDate(report?.started_at || trace?.created_at)}
                </span>
                <span>•</span>
                <span className="text-amber-600">
                  @{trace?.agent || "unknown"}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-4">
              {report?.raw_artifact_ids &&
                report.raw_artifact_ids.length > 0 && (
                  <a
                    href={`/api/raw-artifacts/${report.raw_artifact_ids[0]}/content`}
                    target="_blank"
                    rel="noreferrer"
                    className="px-3 py-1.5 border border-neutral-700 hover:border-neutral-500 hover:text-white transition-all text-[9px] font-mono text-neutral-500 uppercase tracking-widest flex items-center gap-2"
                  >
                    <span className="text-[10px]">⎋</span>
                    Raw Link
                  </a>
                )}
              <button
                onClick={() => setAllExpanded(!allExpanded)}
                className="px-3 py-1.5 border border-neutral-700 hover:border-neutral-500 hover:text-white transition-all text-[9px] font-mono text-neutral-500 uppercase tracking-widest"
              >
                {allExpanded ? "Collapse View" : "Expand All"}
              </button>
              <button
                onClick={() => setRightPanelOpen(!rightPanelOpen)}
                className={cx(
                  "w-8 h-8 flex items-center justify-center border transition-all text-sm font-mono",
                  rightPanelOpen
                    ? "bg-purple-600 border-purple-500 text-white"
                    : "border-neutral-700 text-neutral-500 hover:border-neutral-500 hover:text-white"
                )}
                title="Toggle Detailed Metrics"
              >
                {rightPanelOpen ? "✕" : "›"}
              </button>
            </div>
          </div>

          {/* Stats strip */}
          <div className="flex flex-wrap items-center gap-px bg-neutral-800/20 border border-neutral-800/40 p-0.5 rounded-sm">
            <HeaderStat
              label="Total Cost"
              value={
                report
                  ? fmtUsd(report.total_cost_usd)
                  : trace?.input_tokens
                    ? "..."
                    : "—"
              }
              tone="amber"
            />
            <HeaderStat
              label="Atelier Savings"
              value={report ? fmtUsd(report.total_atelier_savings_usd) : "—"}
              tone="emerald"
            />
            <HeaderStat
              label="Turns / Msgs"
              value={
                report
                  ? `${report.total_turns} / ${inspectorData?.conversations?.length || "—"}`
                  : inspectorData?.conversations?.length
                    ? `— / ${inspectorData.conversations.length}`
                    : "—"
              }
            />
            <HeaderStat
              label="Total Tokens"
              value={
                report || trace
                  ? fmtTok(
                      (report?.input_tokens ?? trace?.input_tokens ?? 0) +
                        (report?.output_tokens ?? trace?.output_tokens ?? 0)
                    )
                  : "—"
              }
            />
            <HeaderStat
              label="In / Out"
              value={
                report || trace
                  ? `${fmtTok(report?.input_tokens ?? trace?.input_tokens ?? 0)} / ${fmtTok(report?.output_tokens ?? trace?.output_tokens ?? 0)}`
                  : "—"
              }
            />
            <HeaderStat
              label="Cached"
              value={
                report || trace
                  ? fmtTok(
                      report?.cache_read_tokens ??
                        trace?.cached_input_tokens ??
                        0
                    )
                  : "—"
              }
            />
            <HeaderStat
              label="Tools"
              value={
                trace
                  ? String(trace.tools_called.length)
                  : report
                    ? String(report.tool_call_count)
                    : "—"
              }
            />
            <HeaderStat
              label="Active Time"
              value={
                report
                  ? fmtDuration(
                      report.active_duration_seconds || activeDurationSecs
                    )
                  : "—"
              }
            />
          </div>
        </div>
      </header>

      {/* Timeline + right panel */}
      <div className="flex-1 overflow-hidden">
        <div className="flex h-full">
          {/* Scrollable timeline */}
          <div className="flex-1 overflow-y-auto custom-scrollbar bg-[#0a0a0a]">
            <div className="p-10 space-y-16 pb-48">
              <section className="space-y-12">
                <div className="flex items-center gap-6">
                  <h2 className="text-[10px] font-black uppercase tracking-[0.5em] text-neutral-500 whitespace-nowrap">
                    Execution Flow
                  </h2>
                  <div className="h-px w-full bg-gradient-to-r from-neutral-800 to-transparent" />
                </div>

                <div className="space-y-12">
                  {inspectorData?.conversations &&
                  inspectorData.conversations.length > 0 ? (
                    groupTurns(inspectorData.conversations).map((turn, i) => (
                      <ConversationTurn
                        key={i}
                        turn={turn}
                        forceExpand={allExpanded}
                      />
                    ))
                  ) : (
                    <div className="space-y-8">
                      {trace?.reasoning && trace.reasoning.length > 0 && (
                        <div className="space-y-4">
                          <h3 className="text-[10px] font-bold uppercase tracking-widest text-neutral-500 px-1">
                            Strategy
                          </h3>
                          {trace.reasoning.map((r, i) => (
                            <div
                              key={i}
                              className="bg-purple-950/[0.03] border border-purple-900/10 p-5 text-[11px] leading-relaxed text-purple-400/60 font-mono whitespace-pre-wrap rounded-sm shadow-inner"
                            >
                              {r}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="space-y-4">
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-neutral-500 px-1">
                          Events
                        </h3>
                        <div className="space-y-3">
                          {trace?.tools_called.map((t, i) => (
                            <ToolCallDetail
                              key={i}
                              tool={t}
                              forceExpand={allExpanded}
                            />
                          ))}
                          {trace?.commands_run.map((c, i) => (
                            <CommandDetail
                              key={i}
                              command={c}
                              forceExpand={allExpanded}
                            />
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </section>

              {trace?.files_touched && trace.files_touched.length > 0 && (
                <section className="space-y-6 pt-12 border-t border-neutral-900/50">
                  <div className="flex items-center gap-6">
                    <h2 className="text-[10px] font-black uppercase tracking-[0.5em] text-neutral-500 whitespace-nowrap">
                      File Changes
                    </h2>
                    <div className="h-px w-full bg-gradient-to-r from-neutral-800 to-transparent" />
                    <span className="text-[9px] text-neutral-500 font-mono font-bold uppercase tracking-widest flex-shrink-0">
                      {trace.files_touched.length} file
                      {trace.files_touched.length !== 1 ? "s" : ""} · current
                      content &amp; total diff
                    </span>
                  </div>
                  <div className="space-y-2">
                    {trace.files_touched.map((f, i) => (
                      <FileDetail key={i} file={f} forceExpand={allExpanded} />
                    ))}
                  </div>
                </section>
              )}
            </div>
          </div>

          {/* Right rail — detailed metrics */}
          {rightPanelOpen && (
            <aside className="w-96 flex-shrink-0 border-l border-neutral-800/60 bg-[#0d0d0d]/40 overflow-y-auto custom-scrollbar p-6 space-y-10 animate-in slide-in-from-right duration-300">
              <section className="space-y-4">
                <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-neutral-400 border-b border-neutral-800 pb-2">
                  Session Blueprint
                </h3>
                <div className="grid gap-4">
                  <SidebarMetric
                    label="Total cost"
                    value={report ? fmtUsd(report.total_cost_usd) : "—"}
                    color="text-amber-500"
                  />
                  <SidebarMetric
                    label="Model Savings"
                    value={
                      report ? fmtUsd(report.total_atelier_savings_usd) : "—"
                    }
                    color="text-emerald-500"
                  />
                  <SidebarMetric
                    label="Total Tokens"
                    value={
                      report
                        ? fmtTok(report.input_tokens + report.output_tokens)
                        : "—"
                    }
                  />
                  <SidebarMetric
                    label="Input Cost"
                    value={report ? fmtUsd(report.input_token_cost_usd) : "—"}
                  />
                  <SidebarMetric
                    label="Output Cost"
                    value={report ? fmtUsd(report.output_token_cost_usd) : "—"}
                  />
                  <SidebarMetric
                    label="Cache Savings"
                    value={report ? fmtUsd(report.cache_read_cost_usd) : "—"}
                  />
                </div>
              </section>

              {report?.top_tools_by_cost &&
                report.top_tools_by_cost.length > 0 && (
                  <section className="space-y-4">
                    <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-neutral-400 border-b border-neutral-800 pb-2">
                      Tool Breakdown
                    </h3>
                    <div className="space-y-2">
                      {report.top_tools_by_cost.map((t, i) => (
                        <div
                          key={i}
                          className="flex items-center justify-between text-[10px] font-mono border-b border-neutral-800/40 pb-1 last:border-0"
                        >
                          <span className="text-blue-400/80 truncate pr-4">
                            {t.tool} ({t.calls})
                          </span>
                          <span className="text-neutral-500">
                            {fmtUsd(t.cost_usd)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

              {report?.models_used &&
                Object.keys(report.models_used).length > 0 && (
                  <section className="space-y-4">
                    <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-neutral-400 border-b border-neutral-800 pb-2">
                      Models Involved
                    </h3>
                    <div className="space-y-2 text-[10px] font-mono">
                      {Object.entries(report.models_used).map(
                        ([model, count], i) => (
                          <div
                            key={i}
                            className="flex items-center justify-between border-b border-neutral-800/40 pb-1 last:border-0"
                          >
                            <span className="text-violet-400/80 truncate pr-4">
                              {model}
                            </span>
                            <span className="text-neutral-500">
                              {count} calls
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  </section>
                )}

              {report?.agent_settings &&
                Object.keys(report.agent_settings).length > 0 && (
                  <section className="space-y-4">
                    <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-neutral-400 border-b border-neutral-800 pb-2">
                      Agent Config
                    </h3>
                    <div className="space-y-2 text-[10px] font-mono">
                      {Object.entries(report.agent_settings).map(
                        ([key, val], i) => (
                          <div
                            key={i}
                            className="flex flex-col border-b border-neutral-800/40 pb-1 last:border-0 gap-0.5"
                          >
                            <span className="text-neutral-400 uppercase font-bold tracking-tighter text-[8px]">
                              {key}
                            </span>
                            <span className="text-neutral-400 truncate">
                              {String(val)}
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  </section>
                )}

              {report?.skills && report.skills.length > 0 && (
                <SidebarList
                  title="Active Skills"
                  items={report.skills}
                  color="text-amber-500/70"
                />
              )}
              {inspectorData?.source_files &&
                inspectorData.source_files.length > 0 && (
                  <SidebarList
                    title="Context Files"
                    items={inspectorData.source_files}
                  />
                )}
              {inspectorData?.artifacts && inspectorData.artifacts.length > 0 && (
                <SidebarList
                  title="Session Artifacts"
                  items={inspectorData.artifacts.map((artifact) => ({
                    path: `${artifact.scope === "subagent" ? "subagent" : "main"} · ${artifact.relative_path}`,
                    artifact_id: artifact.id,
                  }))}
                  color="text-sky-500/70"
                />
              )}
              {inspectorData?.pinned_blocks &&
                inspectorData.pinned_blocks.length > 0 && (
                  <SidebarList
                    title="Pinned Logic"
                    items={inspectorData.pinned_blocks}
                    color="text-purple-500/70"
                  />
                )}
              {inspectorData?.recalled_passages &&
                inspectorData.recalled_passages.length > 0 && (
                  <SidebarList
                    title="Memory Recall"
                    items={inspectorData.recalled_passages.map((p) => p.id)}
                    color="text-cyan-500/70"
                  />
                )}

              <section className="space-y-3 opacity-60 hover:opacity-100 transition-opacity pt-4 border-t border-neutral-800">
                <h3 className="text-[9px] font-black uppercase tracking-widest text-neutral-500">
                  Audit Telemetry
                </h3>
                <div className="space-y-1.5 text-[9px] font-mono text-neutral-500">
                  {report?.raw_artifact_ids &&
                    report.raw_artifact_ids.length > 0 && (
                      <div className="flex flex-col border-b border-neutral-800/20 pb-1.5 mb-1.5 last:border-0">
                        <span className="uppercase text-[8px] font-bold mb-1">
                          Source_Artifacts
                        </span>
                        <div className="space-y-1">
                          {report.raw_artifact_ids.map((id) => (
                            <a
                              key={id}
                              href={`/api/raw-artifacts/${id}/content`}
                              target="_blank"
                              rel="noreferrer"
                              className="block text-purple-500/70 hover:text-purple-400 transition-colors truncate"
                              title={id}
                            >
                              → {id}
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  {report?.telemetry &&
                    Object.entries(report.telemetry).map(([key, val], i) => (
                      <div
                        key={i}
                        className="flex justify-between border-b border-neutral-800/20 pb-0.5 last:border-0"
                      >
                        <span className="uppercase text-[8px] font-bold">
                          {key}
                        </span>
                        <span className="text-neutral-400">{String(val)}</span>
                      </div>
                    ))}
                  {inspectorData?.summarized_events_count ? (
                    <div className="flex justify-between border-b border-neutral-800/20 pb-0.5 last:border-0">
                      <span className="uppercase text-[8px] font-bold text-amber-600/80">
                        Compressed_Events
                      </span>
                      <span className="text-amber-500/70">
                        {inspectorData.summarized_events_count}
                      </span>
                    </div>
                  ) : null}
                  {inspectorData?.tokens_pre && (
                    <div className="flex justify-between border-b border-neutral-800/20 pb-0.5 last:border-0">
                      <span className="uppercase text-[8px] font-bold">
                        Context_Pre
                      </span>
                      <span className="text-neutral-400">
                        {fmtTok(inspectorData.tokens_pre)}
                      </span>
                    </div>
                  )}
                  {inspectorData?.tokens_post && (
                    <div className="flex justify-between border-b border-neutral-800/20 pb-0.5 last:border-0">
                      <span className="uppercase text-[8px] font-bold text-emerald-600/80">
                        Context_Post
                      </span>
                      <span className="text-emerald-500/70">
                        {fmtTok(inspectorData.tokens_post)}
                      </span>
                    </div>
                  )}
                </div>
              </section>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
