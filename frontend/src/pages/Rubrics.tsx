import { useEffect, useState, useMemo } from "react";
import { api, type Rubric } from "../api";

export default function Rubrics() {
  const [items, setItems] = useState<Rubric[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .rubrics()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  const domains = useMemo(
    () => [...new Set(items?.map((r) => r.domain).filter(Boolean))],
    [items],
  );

  const filtered = useMemo(() => {
    if (!items) return [];
    return domainFilter === "all"
      ? items
      : items.filter((r) => r.domain === domainFilter);
  }, [items, domainFilter]);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  return (
    <div className="space-y-6">
      {/* Feature Info */}
      <section className="border border-neutral-800 bg-neutral-900/50 p-5">
        <div className="flex items-start gap-4">
          <div className="text-3xl flex-shrink-0">📏</div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="font-mono font-bold text-neutral-200 text-lg">
                Rubric Gates
              </h2>
              <span className="text-[10px] px-2 py-0.5 font-mono font-bold uppercase tracking-wide bg-emerald-900/30 text-emerald-300">
                stable
              </span>
            </div>
            <p className="font-mono text-[11px] text-neutral-500 mb-3">
              Domain-Specific Verification
            </p>
            <p className="text-xs text-neutral-300 leading-relaxed mb-3">
              YAML-defined checklists that act as quality gates. Pre-execution:
              block bad plans before they run. Post-execution: verify all
              required checks passed. High-risk domains require rubric gates.
            </p>
            <div className="text-xs text-emerald-300/90 space-y-1">
              <p>
                ✓ Prevents known-bad plans before execution (exit 2 = blocked)
              </p>
              <p>✓ Enforces domain quality gates automatically</p>
              <p>✓ YAML format reviewable in pull requests</p>
            </div>
          </div>
        </div>
      </section>

      {/* Rubrics List */}
      <div className="space-y-4">
        {/* Filter */}
        <div className="flex gap-2 items-center px-4 py-2">
          <select
            aria-label="Filter rubrics by domain"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            className="text-[10px] bg-neutral-950 border border-neutral-800 px-2 py-1 text-neutral-400 font-mono"
          >
            <option value="all">All domains</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <span className="text-[10px] text-neutral-600 ml-auto">
            {filtered.length} rubric{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* List of Rubrics */}
        <div className="space-y-3">
          {filtered.map((r) => {
            const isExpanded = expandedId === r.id;

            return (
              <div
                key={r.id}
                className="border border-neutral-800 bg-neutral-900/50 overflow-hidden"
              >
                {/* Header */}
                <button
                  onClick={() =>
                    setExpandedId(expandedId === r.id ? null : r.id)
                  }
                  className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start justify-between"
                >
                  <div className="flex-1 flex items-start gap-3 min-w-0">
                    {/* Domain badge */}
                    <span className="text-[10px] px-2 py-1 bg-neutral-800 text-neutral-300 uppercase font-bold tracking-tight flex-shrink-0 mt-0.5">
                      {r.domain}
                    </span>

                    {/* Title & Details */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span
                          className={`text-amber-400 font-mono text-xs transition-transform ${
                            isExpanded ? "rotate-90" : ""
                          }`}
                        >
                          ❯
                        </span>
                        <h3 className="font-mono font-bold text-neutral-200">
                          {r.name}
                        </h3>
                      </div>
                      <p className="text-xs text-neutral-400">
                        {r.required_checks.length} check
                        {r.required_checks.length !== 1 ? "s" : ""}
                      </p>
                    </div>
                  </div>
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-4">
                    {/* ID */}
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                        ID
                      </div>
                      <code className="text-[10px] bg-neutral-950 px-2 py-1 text-neutral-500 font-mono border border-neutral-800 block break-all">
                        {r.id}
                      </code>
                    </div>

                    {/* Timestamps */}
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                        <span>❯</span> created
                      </div>
                      <p className="text-xs text-neutral-400 font-mono">
                        {new Date(r.created_at).toLocaleString()}
                      </p>
                      {r.updated_at && (
                        <p className="text-xs text-neutral-500 font-mono mt-1">
                          Updated: {new Date(r.updated_at).toLocaleString()}
                        </p>
                      )}
                    </div>

                    {/* Required Checks */}
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                        <span>❯</span> required checks
                      </div>
                      <ul className="space-y-1">
                        {r.required_checks.map((check, i) => (
                          <li
                            key={i}
                            className="text-[11px] text-neutral-300 leading-relaxed bg-neutral-900/40 px-2 py-1 border border-neutral-800 flex items-start gap-2"
                          >
                            <span className="text-emerald-400 flex-shrink-0 mt-0.5">
                              ✓
                            </span>
                            <span>{check}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    {/* Usage */}
                    <div className="pt-2 border-t border-neutral-800">
                      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                        Usage
                      </div>
                      <code className="text-[10px] bg-neutral-950 px-2 py-1 block text-neutral-300 break-all font-mono border border-neutral-800 mb-1">
                        atelier run-rubric {r.id} --json '{"{"}...{"}"}'
                      </code>
                      <code className="text-[10px] bg-neutral-950 px-2 py-1 block text-neutral-300 break-all font-mono border border-neutral-800">
                        MCP: atelier_run_rubric_gate --rubric_id {r.id} --checks
                        '{"{"}...{"}"}'
                      </code>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
