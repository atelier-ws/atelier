import { useEffect, useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  api,
  type ReasonBlock,
  type PlanRecord,
  type Cluster,
  type EnvironmentSummary,
} from "../api";

type Section = "blocks" | "failures" | "plans" | "laws";

const SECTIONS: { id: Section; label: string; icon: string; desc: string }[] = [
  { id: "blocks", label: "Blocks", icon: "🧠", desc: "Reusable procedures" },
  {
    id: "failures",
    label: "Failures",
    icon: "🚨",
    desc: "Error clusters",
  },
  { id: "plans", label: "Plans", icon: "📋", desc: "Plan validation" },
  {
    id: "laws",
    label: "Domain Laws",
    icon: "⚖️",
    desc: "Operating rules per domain",
  },
];

export default function Learnings() {
  const { section } = useParams<{ section?: string }>();
  const navigate = useNavigate();
  const active = (section as Section) || "blocks";

  const setSection = (s: Section) =>
    navigate(`/learnings/${s}`, { replace: true });

  return (
    <div className="space-y-4">
      {/* Sub-navigation */}
      <div className="flex gap-0 border-b border-neutral-800">
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`px-4 py-2 text-xs font-bold font-mono transition border-b-2 flex items-center gap-1.5 ${
              active === s.id
                ? "border-amber-400 text-amber-300 bg-neutral-900/30"
                : "border-transparent text-neutral-500 hover:text-neutral-300"
            }`}
            title={s.desc}
          >
            <span>{s.icon}</span>
            <span>{s.label}</span>
          </button>
        ))}
      </div>

      {/* Section content */}
      {active === "blocks" && <BlocksSection />}
      {active === "failures" && <FailuresSection />}
      {active === "plans" && <PlansSection />}
      {active === "laws" && <LawsSection />}
    </div>
  );
}

// ─── Blocks ───────────────────────────────────────────────────────────────────

function BlocksSection() {
  const [items, setItems] = useState<ReasonBlock[] | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<
    "all" | "active" | "retired" | "deprecated"
  >("all");
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api
      .blocks()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  const domains = useMemo(
    () => [...new Set(items?.map((b) => b.domain).filter(Boolean))],
    [items],
  );

  const filtered = useMemo(() => {
    if (!items) return [];
    return items.filter((b) => {
      if (filter !== "all" && b.status !== filter) return false;
      if (domainFilter !== "all" && b.domain !== domainFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          b.title.toLowerCase().includes(q) ||
          b.id.toLowerCase().includes(q) ||
          b.domain.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [items, filter, domainFilter, search]);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap items-center">
        {(["all", "active", "retired", "deprecated"] as const).map((f) => (
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
        <select
          aria-label="Filter learnings by domain"
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
        <input
          type="text"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="ml-auto text-[11px] bg-neutral-900/50 border border-neutral-700 px-2 py-1 text-neutral-300 placeholder:text-neutral-600 w-40 font-mono"
        />
      </div>

      <div className="space-y-2">
        {filtered.map((b) => (
          <BlockCard
            key={b.id}
            block={b}
            isExpanded={expandedId === b.id}
            onToggle={() =>
              setExpandedId((prev) => (prev === b.id ? null : b.id))
            }
          />
        ))}
        {filtered.length === 0 && (
          <div className="text-neutral-500 text-sm italic py-4 font-mono">
            No blocks match the current filters.
          </div>
        )}
      </div>
      <div className="text-[10px] text-neutral-600 font-mono pt-2 border-t border-neutral-800">
        Showing {filtered.length} of {items.length} blocks
      </div>
    </div>
  );
}

// ─── Failures ─────────────────────────────────────────────────────────────────

function FailuresSection() {
  const [items, setItems] = useState<Cluster[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .clusters()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  if (items.length === 0)
    return (
      <div className="text-neutral-500 text-center py-12">
        <div className="text-4xl mb-4">✅</div>
        <p>No failure clusters detected — agents running smoothly.</p>
      </div>
    );

  return (
    <div className="space-y-2">
      {items.map((c) => {
        const isExpanded = expandedId === c.id;
        const severityColor =
          c.severity === "high"
            ? "bg-red-900/30 text-red-400"
            : c.severity === "medium"
              ? "bg-amber-900/30 text-amber-400"
              : "bg-neutral-800/50 text-neutral-400";
        return (
          <div
            key={c.id}
            className="border border-neutral-800 bg-neutral-900/50 overflow-hidden"
          >
            <button
              onClick={() => setExpandedId(isExpanded ? null : c.id)}
              className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start gap-3"
            >
              <span
                className={`text-[10px] px-2 py-1 font-mono font-bold uppercase flex-shrink-0 mt-0.5 ${severityColor}`}
              >
                {c.severity}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-amber-400 font-mono text-xs transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  >
                    ❯
                  </span>
                  <span className="font-mono font-bold text-neutral-200 text-sm">
                    {c.domain}
                  </span>
                </div>
                <p className="text-xs text-neutral-400">
                  {c.trace_ids.length} trace
                  {c.trace_ids.length !== 1 ? "s" : ""} · {c.id}
                </p>
              </div>
            </button>
            {isExpanded && (
              <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-4 text-xs">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                    Fingerprint
                  </div>
                  <div className="font-mono text-red-400/70 whitespace-pre-wrap break-words bg-neutral-950 p-2 border border-neutral-800">
                    {c.fingerprint}
                  </div>
                </div>
                {c.sample_errors && c.sample_errors.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Sample errors
                    </div>
                    <div className="space-y-1">
                      {c.sample_errors.map((e, j) => (
                        <div
                          key={j}
                          className="font-mono text-neutral-400 bg-neutral-950 p-2 border border-neutral-800"
                        >
                          {e}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {c.suggested_block_title && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Suggested block
                    </div>
                    <div className="text-neutral-300 bg-neutral-950 p-2 border border-neutral-800">
                      {c.suggested_block_title}
                    </div>
                  </div>
                )}
                {c.trace_ids && c.trace_ids.length > 0 && (
                  <div className="pt-2 border-t border-neutral-800">
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Trace IDs
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {c.trace_ids.slice(0, 10).map((t, j) => (
                        <span
                          key={j}
                          className="font-mono text-neutral-500 bg-neutral-950 px-2 py-0.5 border border-neutral-800"
                        >
                          {t}
                        </span>
                      ))}
                      {c.trace_ids.length > 10 && (
                        <span className="text-neutral-600">
                          +{c.trace_ids.length - 10} more
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Plans ────────────────────────────────────────────────────────────────────

function PlansSection() {
  const [items, setItems] = useState<PlanRecord[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .plans()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  if (items.length === 0)
    return (
      <div className="text-neutral-500 text-center py-12">
        <div className="text-4xl mb-4">📋</div>
        <p>No plan validation results yet.</p>
      </div>
    );

  return (
    <div className="space-y-2">
      {items.map((p) => {
        const isExpanded = expandedId === p.trace_id;
        const statusColor =
          p.status === "success"
            ? "bg-emerald-900/30 text-emerald-400"
            : "bg-red-900/30 text-red-400";
        return (
          <div
            key={p.trace_id}
            className="border border-neutral-800 bg-neutral-900/50 overflow-hidden"
          >
            <button
              onClick={() => setExpandedId(isExpanded ? null : p.trace_id)}
              className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start gap-3"
            >
              <span
                className={`text-[10px] px-2 py-1 font-mono font-bold uppercase flex-shrink-0 mt-0.5 ${statusColor}`}
              >
                {p.status}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-amber-400 font-mono text-xs transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  >
                    ❯
                  </span>
                  <span className="font-mono font-bold text-neutral-200 text-sm">
                    {p.domain}
                  </span>
                </div>
                <p className="text-xs text-neutral-400 truncate">{p.task}</p>
              </div>
            </button>
            {isExpanded && (
              <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-3 text-xs">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                    Task
                  </div>
                  <p className="text-neutral-300">{p.task}</p>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                    Trace ID
                  </div>
                  <code className="font-mono text-neutral-500 bg-neutral-950 px-2 py-1 block border border-neutral-800">
                    {p.trace_id}
                  </code>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                    Checks
                  </div>
                  <ul className="space-y-1">
                    {p.plan_checks.map((c, i) => (
                      <li
                        key={i}
                        className={`px-2 py-1 border flex items-start gap-2 ${
                          c.passed
                            ? "text-emerald-300 bg-emerald-900/10 border-emerald-900/30"
                            : "text-red-300 bg-red-900/10 border-red-900/30"
                        }`}
                      >
                        <span className="flex-shrink-0 mt-0.5">
                          {c.passed ? "✓" : "✗"}
                        </span>
                        <div className="flex-1">
                          <div>{c.name}</div>
                          {c.detail && (
                            <div className="text-[10px] text-neutral-400 mt-0.5">
                              {c.detail}
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Domain Laws ──────────────────────────────────────────────────────────────

function LawsSection() {
  const [items, setItems] = useState<EnvironmentSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .environments()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  if (items.length === 0)
    return (
      <div className="text-neutral-500 text-center py-12">
        <div className="text-4xl mb-4">⚖️</div>
        <p>No domain laws configured.</p>
      </div>
    );

  return (
    <div className="space-y-2">
      {items.map((e) => {
        const details = e.environment.details as
          | Record<string, unknown>
          | undefined;
        const isExpanded = expandedId === e.environment.id;
        const isActive = e.environment.status === "active";
        return (
          <div
            key={e.environment.id}
            className="border border-neutral-800 bg-neutral-900/50 overflow-hidden"
          >
            <button
              onClick={() =>
                setExpandedId(isExpanded ? null : e.environment.id)
              }
              className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start gap-3"
            >
              <span
                className={`w-2 h-2 mt-2 flex-shrink-0 ${isActive ? "bg-emerald-500" : "bg-neutral-500"}`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-amber-400 font-mono text-xs transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  >
                    ❯
                  </span>
                  <h3 className="font-mono font-bold text-neutral-200">
                    {e.environment.name || e.environment.id}
                  </h3>
                </div>
                <p className="text-xs text-neutral-500">{e.environment.id}</p>
              </div>
            </button>
            {isExpanded && details && (
              <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-4 text-xs">
                {Boolean(details.description) && (
                  <p className="text-neutral-300 leading-relaxed">
                    {String(details.description)}
                  </p>
                )}
                <div className="grid gap-3 sm:grid-cols-2">
                  {Boolean(details.triggers) && (
                    <LawGrid
                      label="Triggers"
                      items={details.triggers as string[]}
                      chipClass="bg-emerald-900/30 text-emerald-400"
                    />
                  )}
                  {Boolean(details.forbidden) && (
                    <LawList
                      label="Forbidden"
                      items={details.forbidden as string[]}
                      icon="✗"
                      iconClass="text-red-400"
                    />
                  )}
                  {Boolean(details.required) && (
                    <LawList
                      label="Required"
                      items={details.required as string[]}
                      icon="✓"
                      iconClass="text-emerald-400"
                    />
                  )}
                  {Boolean(details.escalate) && (
                    <LawList
                      label="Escalate"
                      items={details.escalate as string[]}
                      icon="⚠"
                      iconClass="text-amber-400"
                    />
                  )}
                </div>
                {Boolean(details.high_risk_tools) && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      High-risk tools
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(details.high_risk_tools as string[]).map((t, j) => (
                        <span
                          key={j}
                          className="px-2 py-0.5 bg-red-900/30 text-red-400 font-mono"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {Boolean(details.related_blocks) && (
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Related blocks
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {(details.related_blocks as string[]).map((b, j) => (
                        <span
                          key={j}
                          className="px-2 py-0.5 bg-neutral-800 text-neutral-400 font-mono"
                        >
                          {b}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {e.rubric && (
                  <div className="pt-2 border-t border-neutral-800">
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Verification checks
                    </div>
                    <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                      <span className="text-blue-300 font-mono">
                        {e.rubric.domain}
                      </span>
                      <span className="text-neutral-600"> · </span>
                      <span className="text-neutral-500">
                        {e.rubric.required_checks.length} checks required
                      </span>
                      <ul className="mt-2 space-y-1">
                        {e.rubric.required_checks.map((c, i) => (
                          <li
                            key={i}
                            className="flex items-start gap-2 text-[11px] text-emerald-300"
                          >
                            <span className="text-emerald-500 flex-shrink-0">
                              ✓
                            </span>
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function LawGrid({
  label,
  items,
  chipClass,
}: {
  label: string;
  items: string[];
  chipClass: string;
}) {
  return (
    <div className="border border-neutral-800 p-3 bg-neutral-900/30">
      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {items.map((t, j) => (
          <span
            key={j}
            className={`px-2 py-0.5 font-mono text-[11px] ${chipClass}`}
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

function LawList({
  label,
  items,
  icon,
  iconClass,
}: {
  label: string;
  items: string[];
  icon: string;
  iconClass: string;
}) {
  return (
    <div className="border border-neutral-800 p-3 bg-neutral-900/30">
      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
        {label}
      </div>
      <ul className="space-y-1">
        {items.map((f, j) => (
          <li
            key={j}
            className="text-[11px] text-neutral-300 flex items-start gap-1"
          >
            <span className={`flex-shrink-0 ${iconClass}`}>{icon}</span>
            <span>{f}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── Block components (copied from Blocks.tsx) ────────────────────────────────

function BlockCard({
  block,
  isExpanded,
  onToggle,
}: {
  block: ReasonBlock;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border border-neutral-800 bg-neutral-900/50 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start gap-4"
      >
        <div className="text-lg flex-shrink-0 mt-0.5">
          {block.status === "active"
            ? "●"
            : block.status === "retired"
              ? "◐"
              : "○"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1 flex-wrap">
            <span
              className={`text-amber-400 font-mono text-xs transition-transform ${isExpanded ? "rotate-90" : ""}`}
            >
              ❯
            </span>
            <h3 className="font-mono font-bold text-neutral-200 text-sm">
              {block.title}
            </h3>
            <StatusBadge status={block.status} />
            {block.domain && (
              <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-300 uppercase font-bold tracking-tight font-mono">
                {block.domain}
              </span>
            )}
          </div>
          <div className="text-[10px] text-neutral-500 font-mono">
            {block.id}
          </div>
        </div>
      </button>
      {isExpanded && (
        <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4">
          <BlockDetail block={block} />
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "bg-emerald-900/40 text-emerald-400",
    retired: "bg-neutral-700 text-neutral-400",
    deprecated: "bg-red-900/40 text-red-400",
  };
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 font-bold uppercase tracking-tight font-mono ${map[status] || map.retired}`}
    >
      {status}
    </span>
  );
}

function BlockDetail({ block }: { block: ReasonBlock }) {
  const total = block.usage_count;
  const successRate =
    total > 0 ? Math.round((block.success_count / total) * 100) : null;

  return (
    <div className="space-y-5 text-sm">
      <header className="pb-4 border-b border-neutral-800">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <StatusBadge status={block.status} />
          <span className="text-[10px] px-1.5 py-0.5 bg-neutral-800 text-neutral-300 uppercase font-bold tracking-tight">
            {block.domain}
          </span>
          {block.task_types.map((t) => (
            <span
              key={t}
              className="text-[10px] px-1.5 py-0.5 bg-neutral-900 border border-neutral-700 text-neutral-400 font-mono"
            >
              {t}
            </span>
          ))}
        </div>
        <h2 className="text-base font-bold text-neutral-300 leading-snug">
          {block.title}
        </h2>
        <div className="font-mono text-[10px] text-neutral-600 mt-1">
          {block.id}
        </div>
        <div className="flex gap-2 mt-1 text-[10px] text-neutral-600">
          <span>Created {new Date(block.created_at).toLocaleString()}</span>
          {block.updated_at && (
            <span>· Updated {new Date(block.updated_at).toLocaleString()}</span>
          )}
        </div>
        {total > 0 && (
          <div className="flex gap-3 mt-3">
            <Stat label="Uses" value={total} />
            <Stat
              label="✓"
              value={block.success_count}
              color="text-emerald-400"
            />
            <Stat label="✗" value={block.failure_count} color="text-red-400" />
            {successRate !== null && (
              <Stat
                label="Rate"
                value={`${successRate}%`}
                color={
                  successRate >= 70 ? "text-emerald-400" : "text-amber-400"
                }
              />
            )}
          </div>
        )}
      </header>

      {block.situation && (
        <section>
          <SL>When to apply</SL>
          <p className="text-neutral-300 text-[13px] leading-relaxed bg-neutral-900/40 border border-neutral-800 px-3 py-2.5">
            {block.situation.trim()}
          </p>
        </section>
      )}

      {block.procedure.length > 0 && (
        <section>
          <SL>Procedure</SL>
          <ol className="space-y-2">
            {block.procedure.map((step, i) => (
              <li
                key={i}
                className="flex gap-3 bg-neutral-900/40 border border-neutral-800 px-3 py-2.5"
              >
                <span className="shrink-0 w-5 h-5 bg-[#ff6041]/15 text-amber-400 text-[10px] font-bold flex items-center justify-center mt-0.5">
                  {i + 1}
                </span>
                <span className="text-neutral-300 text-[13px] leading-relaxed">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {block.verification.length > 0 && (
        <section>
          <SL>Verification</SL>
          <ul className="space-y-1.5">
            {block.verification.map((v, i) => (
              <li
                key={i}
                className="flex gap-2 items-start text-[13px] text-emerald-300 bg-emerald-950/20 border border-emerald-900/30 px-3 py-2"
              >
                <span className="shrink-0 text-emerald-500 mt-0.5">✓</span>
                {v}
              </li>
            ))}
          </ul>
        </section>
      )}

      {block.dead_ends.length > 0 && (
        <section>
          <SL>Dead ends — do not attempt</SL>
          <ul className="space-y-1.5">
            {block.dead_ends.map((d, i) => (
              <li
                key={i}
                className="flex gap-2 items-start text-[13px] text-red-300 bg-red-950/20 border border-red-900/30 px-3 py-2"
              >
                <span className="shrink-0 text-red-500 mt-0.5">✗</span>
                {d}
              </li>
            ))}
          </ul>
        </section>
      )}

      {block.failure_signals.length > 0 && (
        <section>
          <SL>Failure signals</SL>
          <ul className="space-y-1.5">
            {block.failure_signals.map((s, i) => (
              <li
                key={i}
                className="flex gap-2 items-start text-[13px] text-amber-300 bg-amber-950/20 border border-amber-900/30 px-3 py-2"
              >
                <span className="shrink-0 text-amber-500 mt-0.5">⚠</span>
                {s}
              </li>
            ))}
          </ul>
        </section>
      )}

      {block.when_not_to_apply?.trim() && (
        <section>
          <SL>When NOT to apply</SL>
          <p className="text-neutral-400 text-[13px] leading-relaxed bg-neutral-900/40 border border-neutral-700 px-3 py-2.5 italic">
            {block.when_not_to_apply.trim()}
          </p>
        </section>
      )}

      {(block.triggers.length > 0 ||
        block.file_patterns.length > 0 ||
        block.tool_patterns.length > 0) && <MatchHints block={block} />}
    </div>
  );
}

function SL({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] uppercase font-bold tracking-widest text-neutral-500 mb-2">
      {children}
    </div>
  );
}

function Stat({
  label,
  value,
  color = "text-neutral-300",
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="flex flex-col items-center bg-neutral-900/60 border border-neutral-800 px-2.5 py-1.5 min-w-[48px]">
      <span className={`text-sm font-bold ${color}`}>{value}</span>
      <span className="text-[9px] text-neutral-600 uppercase tracking-wide">
        {label}
      </span>
    </div>
  );
}

function MatchHints({ block }: { block: ReasonBlock }) {
  const [open, setOpen] = useState(false);
  return (
    <section>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-[10px] uppercase font-bold tracking-widest text-neutral-600 hover:text-neutral-400 transition mb-2"
      >
        <span>{open ? "▼" : "▶"}</span> Match hints
      </button>
      {open && (
        <div className="space-y-2">
          {block.triggers.length > 0 && (
            <ChipRow
              label="Triggers"
              items={block.triggers}
              color="bg-blue-950/40 text-blue-300 border-blue-900/40"
            />
          )}
          {block.file_patterns.length > 0 && (
            <ChipRow
              label="File patterns"
              items={block.file_patterns}
              color="bg-purple-950/40 text-purple-300 border-purple-900/40"
              mono
            />
          )}
          {block.tool_patterns.length > 0 && (
            <ChipRow
              label="Tool patterns"
              items={block.tool_patterns}
              color="bg-neutral-800 text-neutral-300 border-neutral-700"
              mono
            />
          )}
        </div>
      )}
    </section>
  );
}

function ChipRow({
  label,
  items,
  color,
  mono = false,
}: {
  label: string;
  items: string[];
  color: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-[9px] uppercase text-neutral-600 mb-1">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className={`text-[11px] px-2 py-0.5 border ${color} ${mono ? "font-mono" : ""}`}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}
