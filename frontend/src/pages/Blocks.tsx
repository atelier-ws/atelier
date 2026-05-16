import { useEffect, useState, useMemo } from "react";
import { api, type ReasonBlock } from "../api";
import {
  Alert,
  Chip,
  DisclosureCard,
  EmptyState,
  FeaturePanel,
  FieldLabel,
  Input,
  Select,
  ToggleGroup,
} from "../components/WorkbenchUI";

export default function Blocks() {
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
    [items]
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

  if (err) return <Alert tone="danger" description={err} />;
  if (!items) return <EmptyState title="Loading blocks…" className="p-6" />;

  const toggleExpanded = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="space-y-6">
      <FeaturePanel
        icon="🧠"
        title="ReasonBlocks"
        subtitle="Reusable Reasoning Procedures"
        description={
          <>
            Stored, reviewable procedures that tell agents how to do things
            safely in a specific domain. Blocks are injected into agent context
            before execution via get_reasoning_context. They live in SQLite and
            are mirrored to .atelier/blocks/*.md for PR reviewability.
          </>
        }
        bullets={[
          "Human-reviewable procedures in git (markdown mirrors)",
          "Domain-specific injection — only relevant blocks fetched",
          "7%+ per-call token savings reproducible in benchmarks",
        ]}
      />
      {/* Filters & Blocks List */}
      <div className="space-y-3">
        {/* Filters */}
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <ToggleGroup
            options={(["all", "active", "retired", "deprecated"] as const).map(
              (value) => ({
                value,
                label: value,
              })
            )}
            value={filter}
            onChange={(value) =>
              setFilter(value as "all" | "active" | "retired" | "deprecated")
            }
          />
          <Select
            aria-label="Filter blocks by domain"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            uiSize="xs"
            className="min-w-[148px] bg-neutral-900/50 text-neutral-400"
          >
            <option value="all">All domains</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
          <Input
            type="text"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            uiSize="xs"
            className="ml-auto w-40 bg-neutral-900/50"
          />
        </div>

        {/* Blocks List */}
        <div className="space-y-2">
          {filtered.map((b) => (
            <BlockCard
              key={b.id}
              block={b}
              isExpanded={expandedId === b.id}
              onToggle={() => toggleExpanded(b.id)}
            />
          ))}
          {filtered.length === 0 && (
            <EmptyState
              title="No blocks match the current filters."
              className="p-4"
            />
          )}
        </div>

        {/* Stats footer */}
        <div className="pt-4 border-t border-neutral-800">
          <FieldLabel className="text-neutral-600">
            Showing {filtered.length} of {items.length} blocks
          </FieldLabel>
        </div>
      </div>
    </div>
  );
}

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
    <DisclosureCard
      open={isExpanded}
      onToggle={onToggle}
      header={
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 flex-1 items-start gap-4">
            <div className="mt-0.5 shrink-0 text-lg">
              {block.status === "active"
                ? "●"
                : block.status === "retired"
                  ? "◐"
                  : "○"}
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-3">
                <span
                  className={`text-neutral-500 font-mono text-xs transition-transform ${
                    isExpanded ? "rotate-90" : ""
                  }`}
                >
                  ❯
                </span>
                <h3 className="font-mono text-sm font-bold text-neutral-200">
                  {block.title}
                </h3>
                <StatusBadge status={block.status} />
                {block.domain && <Chip tone="neutral">{block.domain}</Chip>}
              </div>
              <FieldLabel>{block.id}</FieldLabel>
            </div>
          </div>
        </div>
      }
    >
      <BlockDetail block={block} />
    </DisclosureCard>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, "emerald" | "neutral" | "red"> = {
    active: "emerald",
    retired: "neutral",
    deprecated: "red",
  };
  return (
    <Chip tone={map[status] || map.retired}>
      {status}
    </Chip>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <FieldLabel className="mb-2">{children}</FieldLabel>;
}

function BlockDetail({ block }: { block: ReasonBlock }) {
  const total = block.usage_count;
  const successRate =
    total > 0 ? Math.round((block.success_count / total) * 100) : null;

  return (
    <div className="space-y-5 text-sm">
      {/* ── Header ── */}
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
        <div className="flex gap-4 mt-2 text-[10px] text-neutral-600">
          <span>Created {new Date(block.created_at).toLocaleString()}</span>
          {block.updated_at && (
            <span>· Updated {new Date(block.updated_at).toLocaleString()}</span>
          )}
        </div>
        {/* Stats */}
        {total > 0 && (
          <div className="flex gap-3 mt-3">
            <Stat label="Uses" value={total} />
            <Stat
              label="✓ Success"
              value={block.success_count}
              color="text-emerald-400"
            />
            <Stat
              label="✗ Failures"
              value={block.failure_count}
              color="text-red-400"
            />
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

      {/* ── Situation ── */}
      {block.situation && (
        <section>
          <SectionLabel>When to apply</SectionLabel>
          <p className="text-neutral-300 text-[13px] leading-relaxed bg-neutral-900/40 border border-neutral-800  px-3 py-2.5">
            {block.situation.trim()}
          </p>
        </section>
      )}

      {/* ── Procedure ── */}
      {block.procedure.length > 0 && (
        <section>
          <SectionLabel>Procedure</SectionLabel>
          <ol className="space-y-2">
            {block.procedure.map((step, i) => (
              <li
                key={i}
                className="flex gap-3 bg-neutral-900/40 border border-neutral-800  px-3 py-2.5"
              >
                <span className="shrink-0 w-5 h-5 bg-neutral-800 text-neutral-400 text-[10px] font-bold flex items-center justify-center mt-0.5">
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

      {/* ── Verification ── */}
      {block.verification.length > 0 && (
        <section>
          <SectionLabel>Verification</SectionLabel>
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

      {/* ── Dead Ends ── */}
      {block.dead_ends.length > 0 && (
        <section>
          <SectionLabel>Dead ends — do not attempt</SectionLabel>
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

      {/* ── Failure Signals ── */}
      {block.failure_signals.length > 0 && (
        <section>
          <SectionLabel>Failure signals</SectionLabel>
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

      {/* ── When NOT to apply ── */}
      {block.when_not_to_apply && block.when_not_to_apply.trim() && (
        <section>
          <SectionLabel>When NOT to apply</SectionLabel>
          <p className="text-neutral-400 text-[13px] leading-relaxed bg-neutral-900/40 border border-neutral-700  px-3 py-2.5 italic">
            {block.when_not_to_apply.trim()}
          </p>
        </section>
      )}

      {/* ── Match hints (collapsible) ── */}
      {(block.triggers.length > 0 ||
        block.file_patterns.length > 0 ||
        block.tool_patterns.length > 0) && <MatchHints block={block} />}
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
        <span>{open ? "▼" : "▶"}</span>
        Match hints
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
