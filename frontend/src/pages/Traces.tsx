import { useEffect, useState, useMemo } from "react";
import {
  api,
  type Trace,
  type CommandRecord,
  type FileEditRecord,
  type ToolCall,
} from "../api";
import RunInspectorDrawer from "../components/RunInspectorDrawer";

export default function Traces() {
  const [items, setItems] = useState<Trace[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<
    "all" | "success" | "failed" | "partial"
  >("all");
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [hostFilter, setHostFilter] = useState<string>("all");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [inspectorTrace, setInspectorTrace] = useState<Trace | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .traces(50, 0)
      .then((traces) => {
        setItems(traces);
        setHasMore(traces.length >= 50);
        setLoading(false);
      })
      .catch((e) => {
        setErr(String(e));
        setLoading(false);
      });
  }, []);

  const loadMore = () => {
    if (loading || !hasMore) return;
    setLoading(true);
    api
      .traces(50, (page + 1) * 50)
      .then((traces) => {
        setItems((prev) => (prev ? [...prev, ...traces] : traces));
        setHasMore(traces.length >= 50);
        setPage((p) => p + 1);
        setLoading(false);
      })
      .catch((e) => {
        setErr(String(e));
        setLoading(false);
      });
  };

  const domains = useMemo(
    () => [...new Set(items?.map((t) => t.domain).filter(Boolean))],
    [items],
  );
  const hosts = useMemo(
    () => [...new Set(items?.map((t) => extractHost(t.agent)).filter(Boolean))],
    [items],
  );
  const filtered = useMemo(() => {
    if (!items) return [];
    return items.filter((t) => {
      if (filter !== "all" && t.status !== filter) return false;
      if (domainFilter !== "all" && t.domain !== domainFilter) return false;
      if (hostFilter !== "all" && extractHost(t.agent) !== hostFilter)
        return false;
      return true;
    });
  }, [items, filter, domainFilter, hostFilter]);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items && !loading)
    return <div className="text-neutral-500">No traces found.</div>;

  const toggleExpanded = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
    if (expandedId !== id) {
      // Load trace details when expanding
      api
        .trace(id)
        .then(() => {
          // Details loaded successfully
        })
        .catch(() => {
          // Error loading trace
          console.error(`Failed to load trace: ${id.slice(0, 12)}…`);
        });
    }
  };

  const openInspector = (trace: Trace) => {
    setInspectorTrace(trace);
  };

  return (
    <div className="space-y-6">
      {/* Feature Info */}
      <div>
        <button
          onClick={() => setInfoOpen(!infoOpen)}
          className="text-[10px] text-neutral-600 hover:text-neutral-400 font-mono flex items-center gap-1 py-1"
        >
          <span>{infoOpen ? "▼" : "▶"}</span> about
        </button>
        {infoOpen && (
          <section className="border border-neutral-800 bg-neutral-900/50 p-5">
            <div className="flex items-start gap-4">
              <div className="text-3xl flex-shrink-0">📇</div>
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <h2 className="font-mono font-bold text-neutral-200 text-lg">
                    Execution Traces
                  </h2>
                  <span className="text-[10px] px-2 py-0.5 font-mono font-bold uppercase tracking-wide bg-emerald-900/30 text-emerald-300">
                    stable
                  </span>
                </div>
                <p className="font-mono text-[11px] text-neutral-500 mb-3">
                  Observable Run Artifacts
                </p>
                <p className="text-xs text-neutral-300 leading-relaxed mb-3">
                  Records exactly what an agent did: files touched, commands
                  run, tools called, errors seen. Traces never store
                  chain-of-thought — only observables. Each trace links to a
                  RunLedger for full event timeline.
                </p>
                <div className="text-xs text-emerald-300/90 space-y-1">
                  <p>✓ Full audit trail — every agent action recorded</p>
                  <p>
                    ✓ Feeds failure analysis and block extraction automatically
                  </p>
                  <p>✓ Enables per-domain cost attribution</p>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center justify-between gap-2 mb-4 flex-wrap">
        {/* Left: status + domain */}
        <div className="flex gap-2 flex-wrap items-center">
          {["all", "success", "failed", "partial"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f as any)}
              className={`text-[10px] px-2.5 py-1 uppercase font-bold tracking-tight font-mono transition border ${
                filter === f
                  ? "border-amber-400/50 bg-amber-400/10 text-amber-300"
                  : "border-neutral-700 text-neutral-500 hover:text-neutral-300"
              }`}
            >
              {f}
            </button>
          ))}
          <select
            aria-label="Filter traces by domain"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            className="text-[10px] bg-neutral-900/50 border border-neutral-700 px-2 py-1 text-neutral-400 font-mono"
          >
            <option value="all">All domains</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        {/* Right: host buttons */}
        <div className="flex gap-2 flex-wrap items-center">
          {(["all", ...hosts] as string[]).map((h) => (
            <button
              key={h}
              onClick={() => setHostFilter(h)}
              className={`text-[10px] px-2.5 py-1 uppercase font-bold tracking-tight font-mono transition border ${
                hostFilter === h
                  ? "border-violet-400/50 bg-violet-400/10 text-violet-300"
                  : "border-neutral-700 text-neutral-500 hover:text-neutral-300"
              }`}
            >
              {h === "all" ? "all hosts" : h}
            </button>
          ))}
        </div>
      </div>

      {/* Traces List */}
      <div className="space-y-2">
        {filtered.map((t) => (
          <TraceCard
            key={t.id}
            trace={t}
            isExpanded={expandedId === t.id}
            onToggle={() => toggleExpanded(t.id)}
            onOpenInspector={() => openInspector(t)}
          />
        ))}
        {loading && (
          <div className="text-center py-4 text-neutral-500 italic font-mono text-xs">
            Loading more traces…
          </div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="text-neutral-500 text-sm italic py-4 font-mono">
            No traces match the current filters.
          </div>
        )}
        {!loading && hasMore && (
          <button
            onClick={loadMore}
            className="w-full py-2.5 border border-dashed border-neutral-700 text-xs text-neutral-400 hover:text-amber-400 hover:border-amber-400/50 transition font-mono"
          >
            Load More Traces
          </button>
        )}
      </div>

      <RunInspectorDrawer
        open={Boolean(inspectorTrace)}
        trace={inspectorTrace}
        onClose={() => setInspectorTrace(null)}
      />
    </div>
  );
}

function TraceCard({
  trace,
  isExpanded,
  onToggle,
  onOpenInspector,
}: {
  trace: Trace;
  isExpanded: boolean;
  onToggle: () => void;
  onOpenInspector: () => void;
}) {
  return (
    <div className="border border-neutral-800 bg-neutral-900/50 overflow-hidden transition-all">
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start justify-between"
      >
        <div className="flex-1 flex items-start gap-4 min-w-0">
          {/* Icon/Status */}
          <div className="text-lg flex-shrink-0 mt-0.5">
            {trace.status === "success"
              ? "✓"
              : trace.status === "failed"
                ? "✗"
                : "◐"}
          </div>

          {/* Title & Details */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1 flex-wrap">
              {/* Expandable indicator */}
              <span
                className={`text-amber-400 font-mono text-xs transition-transform ${
                  isExpanded ? "rotate-90" : ""
                }`}
              >
                ❯
              </span>
              <div className="flex items-center gap-2 flex-wrap">
                <StatusBadge status={trace.status} />
                {(trace as any)._live && (
                  <span className="text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-tight font-mono bg-cyan-900/40 text-cyan-300 animate-pulse">
                    LIVE
                  </span>
                )}
                {trace.domain && (
                  <span className="text-[10px] px-2 py-0.5 bg-neutral-800 text-neutral-300 uppercase font-bold tracking-tight font-mono">
                    {trace.domain}
                  </span>
                )}
                <HostBadge agent={trace.agent} />
              </div>
            </div>
            <p className="font-mono text-sm text-neutral-200 mb-1">
              {trace.task}
            </p>
            <div className="flex items-center gap-3 text-[10px] text-neutral-500 font-mono">
              <span>{trace.agent}</span>
              <span>ID: {trace.id.slice(0, 12)}…</span>
            </div>
          </div>
        </div>
      </button>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4">
          <TraceDetail trace={trace} onOpenInspector={onOpenInspector} />
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    success: "bg-emerald-900/40 text-emerald-400",
    failed: "bg-red-900/40 text-red-400",
    partial: "bg-amber-900/40 text-amber-400",
  };
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-tight font-mono ${
        map[status] || map.failed
      }`}
    >
      {status}
    </span>
  );
}

function TraceDetail({
  trace,
  onOpenInspector,
}: {
  trace: Trace;
  onOpenInspector: () => void;
}) {
  return (
    <div className="space-y-6 text-sm">
      <header>
        <div className="flex items-center gap-2 mb-1">
          <StatusBadge status={trace.status} />
          {trace.domain && (
            <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 uppercase font-bold tracking-tight">
              {trace.domain}
            </span>
          )}
        </div>
        <h2 className="text-lg font-bold text-neutral-300 leading-tight">
          {trace.task}
        </h2>
        <div className="font-mono text-[10px] text-neutral-500 flex gap-3 mt-1 flex-wrap">
          <span>ID: {trace.id}</span>
          {trace.run_id && <span>RUN: {trace.run_id}</span>}
          <span>{new Date(trace.created_at).toLocaleString()}</span>
        </div>
        <div className="mt-3">
          <button
            type="button"
            aria-label="Open run inspector"
            onClick={onOpenInspector}
            className="text-[11px] px-2.5 py-1 border border-neutral-700 text-neutral-300 hover:text-amber-300 hover:border-amber-500/50 transition"
          >
            Open run inspector
          </button>
        </div>
      </header>

      {/* Reasoning section - show AI thinking/thought process */}
      {trace.reasoning && trace.reasoning.length > 0 && (
        <ReasoningSection reasoning={trace.reasoning} />
      )}

      <div className="grid gap-4">
        <div>
          <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-2">
            Tools Used
          </div>
          <div className="space-y-1">
            {trace.tools_called.map((t, i) => (
              <ToolCallDetail key={i} tool={t} />
            ))}
          </div>
        </div>
        <FilesTouchedSection files={trace.files_touched} runId={trace.run_id} />
      </div>

      {trace.commands_run.length > 0 && (
        <CommandsSection commands={trace.commands_run} />
      )}
      <Section title="Errors Seen" items={trace.errors_seen} variant="danger" />

      {trace.conversations && trace.conversations.length > 0 && (
        <ConversationsSection conversations={trace.conversations} />
      )}

      {trace.trace && <NestedTraceSection trace={trace.trace} />}

      {trace.run_id && (
        <LedgerFetcher
          runId={trace.run_id}
          conversations={trace.conversations}
        />
      )}

      {trace.validation_results.length > 0 && (
        <div>
          <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-2">
            Validations
          </div>
          <ul className="space-y-1.5">
            {trace.validation_results.map((v, i) => (
              <li
                key={i}
                className={`p-2 border ${
                  v.passed
                    ? "bg-emerald-950/20 border-emerald-900/50 text-emerald-300"
                    : "bg-red-950/20 border-red-900/50 text-red-300"
                }`}
              >
                <div className="flex items-center gap-2 font-bold text-xs">
                  <span>{v.passed ? "✓" : "✗"}</span>
                  <span>{v.name}</span>
                </div>
                {v.detail && (
                  <div className="text-[11px] mt-1 opacity-80">{v.detail}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CommandsSection({
  commands,
}: {
  commands: (string | CommandRecord)[];
}) {
  const [expanded, setExpanded] = useState(false);
  const display = expanded ? commands : commands.slice(0, 5);
  return (
    <div>
      <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-2">
        Commands Run{" "}
        <span className="text-neutral-600">({commands.length})</span>
      </div>
      <div className="space-y-1">
        {display.map((c, i) =>
          typeof c === "string" ? (
            <div
              key={i}
              className="text-[11px] font-mono text-neutral-300 bg-neutral-900/40 px-2 py-1 border border-neutral-800/50 truncate"
              title={c}
            >
              {c.length > 100 ? c.slice(0, 100) + "..." : c}
            </div>
          ) : (
            <CommandRecordDetail key={i} record={c} />
          ),
        )}
      </div>
      {commands.length > 5 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-neutral-500 hover:text-neutral-300 mt-2 underline"
        >
          {expanded ? "Show less" : `Show all ${commands.length} commands`}
        </button>
      )}
    </div>
  );
}

function ReasoningSection({ reasoning }: { reasoning: string[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!reasoning || reasoning.length === 0) return null;

  const display = expanded ? reasoning : reasoning.slice(0, 3);
  return (
    <div className="border border-purple-800/50 bg-purple-950/20 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="text-[10px] uppercase font-bold tracking-widest text-purple-400">
          AI Reasoning / Thinking
        </div>
        <span className="text-[9px] text-purple-600">
          ({reasoning.length} blocks)
        </span>
      </div>
      <div className="space-y-2">
        {display.map((r, i) => (
          <div
            key={i}
            className="text-[11px] text-purple-200 leading-relaxed bg-neutral-900/40 px-2 py-1.5 border border-purple-900/30"
          >
            {r.length > 300 ? r.slice(0, 300) + "…" : r}
          </div>
        ))}
      </div>
      {reasoning.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-purple-400 hover:text-purple-300 mt-2 underline"
        >
          {expanded
            ? "Show less"
            : `Show all ${reasoning.length} reasoning blocks`}
        </button>
      )}
    </div>
  );
}

function ConversationsSection({ conversations }: { conversations: any[] }) {
  return (
    <div>
      <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-3">
        Conversation Timeline
      </div>
      <div className="space-y-2">
        {conversations.map((c, i) => (
          <ConversationItem key={i} entry={c} />
        ))}
      </div>
    </div>
  );
}

function ConversationItem({ entry }: { entry: any }) {
  const [expanded, setExpanded] = useState(false);
  const colorClass = getKindColor(entry.kind);
  const isImportant = isImportantEntry(entry.kind, entry.summary);
  const time = entry.at ? new Date(entry.at).toLocaleTimeString() : "";

  return (
    <div
      className={` overflow-hidden bg-neutral-950/40 ${
        isImportant
          ? "border-2 border-amber-600/50"
          : "border border-neutral-800"
      }`}
    >
      <div
        className={`flex items-center justify-between px-3 py-1.5 ${
          colorClass.includes("border-")
            ? ""
            : "bg-neutral-900/50 border-neutral-800"
        }`}
      >
        <span
          className={`text-[9px] font-bold uppercase tracking-tighter px-1.5 border ${colorClass}`}
        >
          {entry.kind.replace("_", " ")}
        </span>
        <span className="text-[9px] font-mono text-neutral-600">{time}</span>
      </div>
      <div className="px-3 py-2">
        <div className="text-xs font-medium text-neutral-300 leading-snug">
          {entry.summary}
        </div>
        {entry.content && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[10px] text-neutral-500 hover:text-neutral-300 underline mt-1"
          >
            {expanded ? "Hide content" : "View content"}
          </button>
        )}
        {expanded && entry.content && (
          <pre className="mt-2 text-[10px] bg-black/60 p-2.5 border border-neutral-800 overflow-auto max-h-48 text-neutral-400 font-mono leading-relaxed whitespace-pre-wrap">
            {typeof entry.content === "string"
              ? entry.content.slice(0, 2000)
              : JSON.stringify(entry.content, null, 2).slice(0, 2000)}
          </pre>
        )}
      </div>
    </div>
  );
}

function NestedTraceSection({ trace }: { trace: any }) {
  return (
    <div className="border border-neutral-800 p-4 bg-neutral-900/20">
      <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-3">
        Nested Run Trace
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs mb-3">
        <div>
          <span className="text-neutral-500">Agent:</span>{" "}
          <span className="text-neutral-300">{trace.agent}</span>
        </div>
        <div>
          <span className="text-neutral-500">Domain:</span>{" "}
          <span className="text-neutral-300">{trace.domain}</span>
        </div>
        <div>
          <span className="text-neutral-500">Status:</span>{" "}
          <StatusBadge status={trace.status} />
        </div>
        <div>
          <span className="text-neutral-500">Traces:</span>{" "}
          <span className="text-neutral-300">
            {trace.trace_ids?.length || 0}
          </span>
        </div>
      </div>
      {trace.files_touched && trace.files_touched.length > 0 && (
        <div className="mb-3">
          <div className="text-[10px] uppercase text-neutral-500 mb-1">
            Files Touched
          </div>
          <div className="flex flex-wrap gap-1">
            {trace.files_touched.map((f: string, i: number) => (
              <span
                key={i}
                className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-400 font-mono truncate max-w-[200px]"
              >
                {f.split("/").pop()}
              </span>
            ))}
          </div>
        </div>
      )}
      {trace.tools_called && trace.tools_called.length > 0 && (
        <div>
          <div className="text-[10px] uppercase text-neutral-500 mb-1">
            Tools Called
          </div>
          <div className="flex flex-wrap gap-1">
            {trace.tools_called.map((t: any, i: number) => (
              <span
                key={i}
                className="text-[10px] px-2 py-0.5 bg-blue-900/30 text-blue-300 border border-blue-800"
              >
                {t.name} ×{t.count}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  items,
  mono,
  variant,
}: {
  title: string;
  items: string[];
  mono?: boolean;
  variant?: "default" | "warning" | "danger";
}) {
  if (items.length === 0) return null;
  const titleColor =
    variant === "warning"
      ? "text-amber-500"
      : variant === "danger"
        ? "text-red-500"
        : "text-neutral-500";
  return (
    <div className="space-y-1.5">
      <div
        className={`text-[10px] uppercase font-bold tracking-widest ${titleColor}`}
      >
        {title}
      </div>
      <ul className={`space-y-1 ${mono ? "font-mono" : ""}`}>
        {items.map((x, i) => (
          <li
            key={i}
            className="text-[11px] text-neutral-300 leading-relaxed bg-neutral-900/40 px-2 py-1 border border-neutral-800/50"
          >
            {x}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LedgerFetcher({
  runId,
  conversations,
}: {
  runId: string;
  conversations?: any[];
}) {
  const [ledger, setLedger] = useState<any | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset ledger when runId changes (new trace selected)
  useEffect(() => {
    setLedger(null);
    setError(null);
  }, [runId]);

  useEffect(() => {
    if (expanded && !ledger) {
      setLoading(true);
      api
        .ledger(runId)
        .then((data) => {
          setLedger(data);
          setLoading(false);
        })
        .catch((e) => {
          setError(String(e));
          setLoading(false);
        });
    }
  }, [expanded, ledger, runId]);

  if (!expanded) {
    return (
      <div className="pt-4 border-t border-neutral-800">
        <button
          onClick={() => setExpanded(true)}
          className="w-full py-3  border border-dashed border-neutral-800 text-xs text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 transition font-medium"
        >
          View Full Run Ledger (Events, Hypotheses, Details)
        </button>
      </div>
    );
  }

  if (loading)
    return (
      <div className="text-xs text-neutral-500 italic py-4 animate-pulse">
        Retrieving ledger records…
      </div>
    );
  if (error)
    return (
      <div className="text-xs text-red-400 py-4">
        Failed to load ledger: {error}
      </div>
    );

  const ledgerConversations = ledger?.conversations || conversations;

  if (!ledger)
    return (
      <div className="text-xs text-neutral-500 py-4">
        No ledger data available.
      </div>
    );

  return (
    <div className="pt-6 border-t border-neutral-800 space-y-4">
      <div className="flex justify-between items-center">
        <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500">
          Run Ledger
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="text-[10px] font-bold uppercase text-neutral-500 hover:text-amber-400 transition"
        >
          Collapse
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {ledger.hypotheses_tried && ledger.hypotheses_tried.length > 0 && (
          <div className="bg-neutral-900/40 border border-neutral-800 p-2">
            <div className="text-[9px] font-bold uppercase text-neutral-500 mb-1.5">
              Hypotheses Tried
            </div>
            <ul className="space-y-1">
              {ledger.hypotheses_tried.map((h: string, i: number) => (
                <li
                  key={i}
                  className="text-[11px] text-neutral-300 leading-tight"
                >
                  • {h}
                </li>
              ))}
            </ul>
          </div>
        )}
        {ledger.verified_facts && ledger.verified_facts.length > 0 && (
          <div className="bg-neutral-900/40 border border-neutral-800 p-2">
            <div className="text-[9px] font-bold uppercase text-neutral-500 mb-1.5">
              Verified Facts
            </div>
            <ul className="space-y-1">
              {ledger.verified_facts.map((f: string, i: number) => (
                <li
                  key={i}
                  className="text-[11px] text-neutral-300 leading-tight"
                >
                  • {f}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {ledger.events && ledger.events.length > 0 && (
        <div className="space-y-2">
          <div className="text-[10px] uppercase text-neutral-500">Events</div>
          {ledger.events.map((ev: any, i: number) => (
            <div
              key={i}
              className="border border-neutral-800  overflow-hidden bg-neutral-950/40"
            >
              <div className="flex justify-between items-center px-3 py-1.5 bg-neutral-900/50 border-b border-neutral-800">
                <span
                  className={`text-[9px] font-bold uppercase tracking-tighter px-1.5 ${getKindColor(
                    ev.kind,
                  )}`}
                >
                  {ev.kind}
                </span>
                <span className="text-[9px] font-mono text-neutral-600">
                  {ev.at ? new Date(ev.at).toLocaleTimeString() : ""}
                </span>
              </div>
              <div className="px-3 py-2">
                <div className="text-xs font-medium text-neutral-300 leading-snug">
                  {ev.summary}
                </div>
                {ev.payload && Object.keys(ev.payload).length > 0 && (
                  <LedgerPayload payload={ev.payload} />
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {ledgerConversations && ledgerConversations.length > 0 && (
        <div className="pt-4 border-t border-neutral-800">
          <ConversationsSection conversations={ledgerConversations} />
        </div>
      )}

      {!ledger.hypotheses_tried?.length &&
        !ledger.verified_facts?.length &&
        !ledger.events?.length &&
        !ledgerConversations?.length && (
          <div className="text-xs text-neutral-500 italic">
            No ledger events found.
          </div>
        )}
    </div>
  );
}

function LedgerPayload({ payload }: { payload: any }) {
  const [open, setOpen] = useState(true);
  const isDiffPayload = payload.diff && typeof payload.diff === "string";
  const isCommandResult =
    payload.command !== undefined &&
    (payload.stdout !== undefined || payload.stderr !== undefined);
  const isSessionStats =
    payload.event === "Stop" && payload.total_tokens !== undefined;
  const isSessionStart = payload.event === "SessionStart";
  const isUserPrompt =
    payload.event === "UserPromptSubmit" && payload.prompt !== undefined;
  const isCompact =
    payload.event === "PreCompact" || payload.event === "PostCompact";

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-[10px] text-neutral-500 hover:text-neutral-300 underline"
      >
        {open ? "Hide Details" : "View Details"}
      </button>
      {open && (
        <>
          {isDiffPayload ? (
            <DiffViewer
              diff={payload.diff}
              filePath={payload.path}
              event={payload.event}
            />
          ) : isCommandResult ? (
            <CommandResultPayload payload={payload} />
          ) : isSessionStats ? (
            <SessionStatsPayload payload={payload} />
          ) : isSessionStart ? (
            <SessionStartPayload payload={payload} />
          ) : isUserPrompt ? (
            <UserPromptPayload payload={payload} />
          ) : isCompact ? (
            <CompactPayload payload={payload} />
          ) : (
            <pre className="mt-2 text-[10px] bg-black/60 p-2.5 border border-neutral-800 overflow-auto max-h-48 text-neutral-400 font-mono leading-relaxed">
              {JSON.stringify(payload, null, 2)}
            </pre>
          )}
        </>
      )}
    </div>
  );
}

function CommandResultPayload({ payload }: { payload: any }) {
  const rc = payload.return_code;
  const ok = rc === 0;
  const rcColor =
    rc === null || rc === undefined
      ? "text-neutral-500"
      : ok
        ? "text-emerald-400"
        : "text-red-400";
  return (
    <div className="mt-2 space-y-1.5">
      {/* Command */}
      <pre className="text-[10px] bg-black/60 px-2.5 py-1.5 border border-neutral-800 text-amber-300 font-mono whitespace-pre-wrap break-all">
        $ {payload.command}
      </pre>
      {/* Return code */}
      <div className={`text-[9px] font-mono font-bold ${rcColor}`}>
        exit {rc ?? "?"}
        {payload.truncated ? " · output truncated to 4 KB" : ""}
      </div>
      {/* Stdout */}
      {payload.stdout && (
        <pre className="text-[9px] bg-black/40 px-2.5 py-1.5 border border-neutral-800/60 text-neutral-300 font-mono overflow-auto max-h-40 whitespace-pre-wrap break-all leading-relaxed">
          {payload.stdout}
        </pre>
      )}
      {/* Stderr */}
      {payload.stderr && (
        <pre className="text-[9px] bg-red-950/20 px-2.5 py-1.5 border border-red-900/40 text-red-300 font-mono overflow-auto max-h-32 whitespace-pre-wrap break-all leading-relaxed">
          {payload.stderr}
        </pre>
      )}
    </div>
  );
}

function SessionStatsPayload({ payload }: { payload: any }) {
  const topTools: [string, number][] = Object.entries(payload.top_tools ?? {});
  return (
    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
      <span className="text-neutral-500">input tokens</span>
      <span className="text-neutral-300">
        {(payload.input_tokens ?? 0).toLocaleString()}
      </span>
      <span className="text-neutral-500">output tokens</span>
      <span className="text-neutral-300">
        {(payload.output_tokens ?? 0).toLocaleString()}
      </span>
      <span className="text-neutral-500">total tokens</span>
      <span className="text-neutral-200 font-bold">
        {(payload.total_tokens ?? 0).toLocaleString()}
      </span>
      <span className="text-neutral-500">est. cost</span>
      <span className="text-amber-300">
        ~${(payload.est_cost_usd ?? 0).toFixed(4)}
      </span>
      <span className="text-neutral-500">tool calls</span>
      <span className="text-neutral-300">{payload.tool_calls ?? 0}</span>
      {topTools.length > 0 && (
        <>
          <span className="text-neutral-500">top tools</span>
          <span className="text-neutral-400">
            {topTools.map(([n, c]) => `${n}×${c}`).join(" · ")}
          </span>
        </>
      )}
    </div>
  );
}

function SessionStartPayload({ payload }: { payload: any }) {
  return (
    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
      <span className="text-neutral-500">session_id</span>
      <span className="text-neutral-300 truncate">
        {payload.session_id || "—"}
      </span>
      <span className="text-neutral-500">source</span>
      <span className="text-cyan-300">{payload.source || "—"}</span>
      <span className="text-neutral-500">model</span>
      <span className="text-violet-300">{payload.model || "—"}</span>
      {payload.cwd && (
        <>
          <span className="text-neutral-500">cwd</span>
          <span className="text-neutral-400 truncate">{payload.cwd}</span>
        </>
      )}
    </div>
  );
}

function UserPromptPayload({ payload }: { payload: any }) {
  const [expanded, setExpanded] = useState(false);
  const prompt: string = payload.prompt ?? "";
  const short = prompt.slice(0, 300);
  const needsExpand = prompt.length > 300;
  return (
    <div className="mt-2">
      <pre className="text-[10px] bg-neutral-900/60 px-3 py-2 border-l-2 border-pink-700/60 text-neutral-200 font-mono whitespace-pre-wrap break-words leading-relaxed max-h-48 overflow-auto">
        {expanded ? prompt : short}
        {needsExpand && !expanded && "…"}
      </pre>
      {needsExpand && (
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-[10px] text-neutral-500 hover:text-neutral-300 underline mt-1"
        >
          {expanded ? "collapse" : `show all (${prompt.length} chars)`}
        </button>
      )}
      {payload.truncated && (
        <div className="text-[9px] text-amber-500 mt-1">
          prompt truncated to 8 KB
        </div>
      )}
    </div>
  );
}

function CompactPayload({ payload }: { payload: any }) {
  const isPost = payload.event === "PostCompact";
  return (
    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
      <span className="text-neutral-500">phase</span>
      <span className={isPost ? "text-emerald-400" : "text-amber-400"}>
        {isPost ? "completed" : "starting"}
      </span>
      <span className="text-neutral-500">trigger</span>
      <span className="text-neutral-300">{payload.trigger || "—"}</span>
    </div>
  );
}

function DiffViewer({
  diff,
  filePath,
  event,
}: {
  diff: string;
  filePath?: string;
  event?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const lines = diff.split("\n");
  const addedLines = lines.filter(
    (l) => l.startsWith("+") && !l.startsWith("+++"),
  ).length;
  const removedLines = lines.filter(
    (l) => l.startsWith("-") && !l.startsWith("---"),
  ).length;

  return (
    <div className="mt-2 border border-neutral-700 bg-black/30 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-neutral-900/50 border-b border-neutral-800">
        <div className="flex items-center gap-3 text-[10px]">
          {filePath && (
            <span className="text-neutral-400 font-mono">{filePath}</span>
          )}
          {event && <span className="text-neutral-500">{event}</span>}
          {addedLines > 0 && (
            <span className="text-emerald-400">+{addedLines}</span>
          )}
          {removedLines > 0 && (
            <span className="text-red-400">-{removedLines}</span>
          )}
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] text-neutral-500 hover:text-neutral-300 uppercase font-bold"
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>

      {/* Diff Content */}
      {expanded && (
        <pre className="text-[9px] bg-black/80 p-3 overflow-auto max-h-96 text-neutral-300 font-mono leading-relaxed whitespace-pre-wrap break-words">
          {lines.map((line, i) => {
            let color = "text-neutral-400";
            if (line.startsWith("+++") || line.startsWith("---")) {
              color = "text-neutral-500";
            } else if (line.startsWith("+")) {
              color = "text-emerald-400 bg-emerald-950/20";
            } else if (line.startsWith("-")) {
              color = "text-red-400 bg-red-950/20";
            } else if (line.startsWith("@@")) {
              color = "text-cyan-400";
            }
            return (
              <div key={i} className={color}>
                {line}
              </div>
            );
          })}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Files Touched — clickable with inline side-by-side diff
// ---------------------------------------------------------------------------

function FilesTouchedSection({
  files,
  runId,
}: {
  files: (string | FileEditRecord)[];
  runId?: string | null;
}) {
  if (!files || files.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500">
        Files Touched
      </div>
      <div className="space-y-1">
        {files.map((f) => {
          const path = typeof f === "string" ? f : f.path;
          const diff = typeof f === "string" ? undefined : f.diff;
          return (
            <FileRow key={path} path={path} runId={runId} inlineDiff={diff} />
          );
        })}
      </div>
    </div>
  );
}

function FileRow({
  path,
  runId,
  inlineDiff,
}: {
  path: string;
  runId?: string | null;
  inlineDiff?: string;
}) {
  const [open, setOpen] = useState(false);
  const [diffs, setDiffs] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If we have an inline diff, use it directly without fetching the ledger
  const hasInlineDiff = !!inlineDiff;

  const handleClick = async () => {
    setOpen((o) => !o);
    if (hasInlineDiff || diffs !== null || loading) return;
    if (!runId) return;
    setLoading(true);
    try {
      const ledger = await api.ledger(runId);
      const events: any[] = ledger?.events ?? [];
      const collected = events
        .filter(
          (ev) =>
            ev.kind === "file_edit" &&
            ev.payload?.diff &&
            (ev.payload?.path === path ||
              ev.payload?.path?.endsWith("/" + path) ||
              path.endsWith("/" + (ev.payload?.path ?? "").split("/").pop())),
        )
        .map((ev) => ev.payload.diff as string);
      setDiffs(collected.length > 0 ? collected : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const filename = path.split("/").pop() ?? path;
  const canExpand = hasInlineDiff || !!runId;

  return (
    <div className="border border-neutral-800/50 overflow-hidden">
      <button
        onClick={handleClick}
        disabled={!canExpand}
        className={`w-full flex items-center justify-between px-2 py-1 text-left transition-colors ${
          canExpand
            ? "hover:bg-neutral-800/40 cursor-pointer"
            : "cursor-default"
        }`}
      >
        <span className="text-[11px] text-neutral-300 font-mono">{path}</span>
        {canExpand && (
          <span className="text-[9px] text-neutral-500 font-mono ml-2 flex-shrink-0">
            {open ? "▲ hide diff" : "▼ diff"}
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-neutral-800/50">
          {/* Show inline diff directly if available */}
          {hasInlineDiff && (
            <SideBySideDiffViewer diff={inlineDiff!} path={path} />
          )}
          {/* Otherwise fall back to ledger fetch */}
          {!hasInlineDiff && loading && (
            <div className="px-3 py-2 text-[11px] text-neutral-500 italic animate-pulse">
              Loading diff…
            </div>
          )}
          {!hasInlineDiff && error && (
            <div className="px-3 py-2 text-[11px] text-red-400">{error}</div>
          )}
          {!hasInlineDiff &&
            !loading &&
            !error &&
            diffs !== null &&
            diffs.length === 0 && (
              <div className="px-3 py-2 text-[11px] text-neutral-500 italic">
                No diff captured for {filename}.
              </div>
            )}
          {!hasInlineDiff &&
            diffs &&
            diffs.map((diff, i) => (
              <SideBySideDiffViewer key={i} diff={diff} path={path} />
            ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Side-by-side diff viewer
// ---------------------------------------------------------------------------

type DiffLine = {
  lineNo: number | null;
  content: string;
  type: "add" | "remove" | "context" | "header";
};

function parseDiffSides(raw: string): { left: DiffLine[]; right: DiffLine[] } {
  const lines = raw.split("\n");
  const left: DiffLine[] = [];
  const right: DiffLine[] = [];
  let leftNo = 1;
  let rightNo = 1;

  for (const line of lines) {
    if (line.startsWith("---") || line.startsWith("+++")) {
      left.push({ lineNo: null, content: line, type: "header" });
      right.push({ lineNo: null, content: line, type: "header" });
    } else if (line.startsWith("@@")) {
      // Parse hunk header: @@ -l,s +l,s @@
      const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        leftNo = parseInt(m[1]);
        rightNo = parseInt(m[2]);
      }
      left.push({ lineNo: null, content: line, type: "header" });
      right.push({ lineNo: null, content: line, type: "header" });
    } else if (line.startsWith("-")) {
      left.push({ lineNo: leftNo++, content: line.slice(1), type: "remove" });
      right.push({ lineNo: null, content: "", type: "remove" });
    } else if (line.startsWith("+")) {
      left.push({ lineNo: null, content: "", type: "add" });
      right.push({ lineNo: rightNo++, content: line.slice(1), type: "add" });
    } else {
      const content = line.startsWith(" ") ? line.slice(1) : line;
      left.push({ lineNo: leftNo++, content, type: "context" });
      right.push({ lineNo: rightNo++, content, type: "context" });
    }
  }
  return { left, right };
}

function SideBySideDiffViewer({ diff, path }: { diff: string; path: string }) {
  const [expanded, setExpanded] = useState(true);
  const { left, right } = useMemo(() => parseDiffSides(diff), [diff]);

  const addedCount = right.filter(
    (l) => l.type === "add" && l.content !== "",
  ).length;
  const removedCount = left.filter(
    (l) => l.type === "remove" && l.content !== "",
  ).length;

  const lineClass = (type: DiffLine["type"], side: "left" | "right") => {
    if (type === "header") return "bg-neutral-900/60 text-neutral-500";
    if (type === "add" && side === "right")
      return "bg-emerald-950/40 text-emerald-300";
    if (type === "remove" && side === "left")
      return "bg-red-950/40 text-red-300";
    if (type === "add" || type === "remove")
      return "bg-transparent text-transparent select-none";
    return "text-neutral-400";
  };

  return (
    <div className="border-t border-neutral-800/30">
      {/* Diff header */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-neutral-900/40 border-b border-neutral-800/50">
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="text-neutral-400 truncate max-w-[300px]">
            {path}
          </span>
          {addedCount > 0 && (
            <span className="text-emerald-400">+{addedCount}</span>
          )}
          {removedCount > 0 && (
            <span className="text-red-400">-{removedCount}</span>
          )}
        </div>
        <button
          onClick={() => setExpanded((e) => !e)}
          className="text-[10px] text-neutral-500 hover:text-neutral-300 uppercase font-bold font-mono"
        >
          {expanded ? "collapse" : "expand"}
        </button>
      </div>

      {expanded && (
        <div className="flex overflow-x-auto max-h-[500px] overflow-y-auto">
          {/* Left (old) */}
          <div className="flex-1 min-w-0 border-r border-neutral-800/50">
            <div className="text-[9px] px-2 py-0.5 bg-red-950/20 text-red-400 font-mono font-bold border-b border-neutral-800/30">
              before
            </div>
            {left.map((line, i) => (
              <div
                key={i}
                className={`flex text-[10px] font-mono leading-5 ${lineClass(line.type, "left")}`}
              >
                <span className="w-8 flex-shrink-0 text-right pr-2 text-neutral-600 select-none border-r border-neutral-800/40 bg-black/20">
                  {line.lineNo ?? ""}
                </span>
                <span className="px-2 whitespace-pre overflow-hidden text-ellipsis flex-1">
                  {line.content}
                </span>
              </div>
            ))}
          </div>
          {/* Right (new) */}
          <div className="flex-1 min-w-0">
            <div className="text-[9px] px-2 py-0.5 bg-emerald-950/20 text-emerald-400 font-mono font-bold border-b border-neutral-800/30">
              after
            </div>
            {right.map((line, i) => (
              <div
                key={i}
                className={`flex text-[10px] font-mono leading-5 ${lineClass(line.type, "right")}`}
              >
                <span className="w-8 flex-shrink-0 text-right pr-2 text-neutral-600 select-none border-r border-neutral-800/40 bg-black/20">
                  {line.lineNo ?? ""}
                </span>
                <span className="px-2 whitespace-pre overflow-hidden text-ellipsis flex-1">
                  {line.content}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Enriched detail components
// ---------------------------------------------------------------------------

function ToolCallDetail({ tool }: { tool: ToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails =
    (tool.args && Object.keys(tool.args).length > 0) || tool.result_summary;
  return (
    <div className="border border-neutral-800/50 overflow-hidden">
      <div className="flex items-center gap-2 px-2 py-1 bg-neutral-900/40">
        <span className="text-[11px] px-2 py-0.5 bg-blue-900/30 text-blue-300 border border-blue-800/50">
          {tool.name}
          {tool.count > 1 ? ` ×${tool.count}` : ""}
        </span>
        {hasDetails && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-[9px] text-neutral-500 hover:text-neutral-300 underline"
          >
            {expanded ? "hide" : "details"}
          </button>
        )}
      </div>
      {expanded && hasDetails && (
        <div className="px-2 py-1.5 space-y-1 border-t border-neutral-800/50 bg-neutral-950/40">
          {tool.args && Object.keys(tool.args).length > 0 && (
            <div>
              <div className="text-[9px] uppercase text-neutral-500 font-bold mb-0.5">
                Args
              </div>
              <pre className="text-[10px] bg-black/40 p-1.5 border border-neutral-800/50 overflow-auto max-h-32 text-neutral-300 font-mono whitespace-pre-wrap break-all">
                {JSON.stringify(tool.args, null, 2).slice(0, 1000)}
              </pre>
            </div>
          )}
          {tool.result_summary && (
            <div>
              <div className="text-[9px] uppercase text-neutral-500 font-bold mb-0.5">
                Result
              </div>
              <pre className="text-[10px] bg-black/40 p-1.5 border border-neutral-800/50 overflow-auto max-h-24 text-emerald-300/80 font-mono whitespace-pre-wrap break-all">
                {tool.result_summary}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CommandRecordDetail({ record }: { record: CommandRecord }) {
  const [expanded, setExpanded] = useState(false);
  const rc = record.exit_code;
  const ok = rc === 0 || rc === null || rc === undefined;
  return (
    <div className="border border-neutral-800/50 overflow-hidden">
      <div
        className="flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-neutral-800/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <pre className="text-[10px] font-mono text-amber-300 flex-1 truncate">
          $ {record.command}
        </pre>
        <span
          className={`text-[9px] font-mono font-bold ${ok ? "text-emerald-400" : "text-red-400"}`}
        >
          exit {rc ?? "?"}
        </span>
        <span className="text-[9px] text-neutral-500">
          {expanded ? "▲" : "▼"}
        </span>
      </div>
      {expanded && (
        <div className="border-t border-neutral-800/50 px-2 py-1.5 space-y-1 bg-neutral-950/40">
          {record.stdout && (
            <pre className="text-[9px] bg-black/40 p-1.5 border border-neutral-800/50 text-neutral-300 font-mono overflow-auto max-h-32 whitespace-pre-wrap break-all leading-relaxed">
              {record.stdout}
            </pre>
          )}
          {record.stderr && (
            <pre className="text-[9px] bg-red-950/20 p-1.5 border border-red-900/40 text-red-300 font-mono overflow-auto max-h-24 whitespace-pre-wrap break-all leading-relaxed">
              {record.stderr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Host helpers
// ---------------------------------------------------------------------------

function extractHost(agent: string): string {
  if (!agent) return "unknown";
  const a = agent.toLowerCase();
  if (a.includes("gemini")) return "gemini";
  if (a.includes("copilot")) return "copilot";
  if (a.includes("codex")) return "codex";
  if (a.includes("opencode")) return "opencode";
  // atelier:code and any claude-code sessions
  if (a.startsWith("atelier:") || a.includes("claude")) return "claude";
  return agent; // return raw if nothing matched
}

const HOST_COLORS: Record<string, string> = {
  claude: "bg-violet-900/40 text-violet-300 border-violet-700/50",
  gemini: "bg-blue-900/40 text-blue-300 border-blue-700/50",
  copilot: "bg-sky-900/40 text-sky-300 border-sky-700/50",
  codex: "bg-teal-900/40 text-teal-300 border-teal-700/50",
  opencode: "bg-indigo-900/40 text-indigo-300 border-indigo-700/50",
};

function HostBadge({ agent }: { agent: string }) {
  const host = extractHost(agent);
  const cls =
    HOST_COLORS[host] ??
    "bg-neutral-800/60 text-neutral-400 border-neutral-700/50";
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-tight font-mono border ${cls}`}
    >
      {host}
    </span>
  );
}

function getKindColor(kind: string) {
  const map: Record<string, string> = {
    // User message - most prominent, bright pink/magenta
    user_message: "text-pink-400 bg-pink-950/60 border-pink-700",
    // Agent messages - soft teal
    agent_message: "text-teal-400 bg-teal-950/40 border-teal-800",
    reasoning: "text-purple-400 bg-purple-950/40 border-purple-800",
    // Tool calls - green for success
    tool_call: "text-green-400 bg-green-950/40 border-green-800",
    // Shell commands - slate/gray
    shell_command: "text-slate-400 bg-slate-900/40 border-slate-700",
    command_result: "text-slate-400 bg-slate-900/40 border-slate-700",
    // File edits - important, orange
    file_edit: "text-orange-400 bg-orange-950/40 border-orange-800",
    // System alerts - yellow
    monitor_alert: "text-yellow-400 bg-yellow-950/40 border-yellow-800",
  };
  return map[kind] || "text-neutral-400 bg-neutral-800/50 border-neutral-700";
}

// Highlight important entries with border
function isImportantEntry(kind: string, summary: string): boolean {
  const importantKinds = ["user_message", "file_edit", "monitor_alert"];
  const importantKeywords = [
    "error",
    "failed",
    "success",
    "fixed",
    "completed",
    "important",
  ];

  if (importantKinds.includes(kind)) return true;
  const lower = summary.toLowerCase();
  return importantKeywords.some((k) => lower.includes(k));
}
