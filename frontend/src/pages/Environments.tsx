import { useEffect, useState } from "react";
import { api, type EnvironmentSummary } from "../api";

export default function Environments() {
  const [items, setItems] = useState<EnvironmentSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api.environments().then(setItems).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!items) return <div className="text-neutral-500">Loading…</div>;

  return (
    <div className="space-y-6">
      {/* Feature Info */}
      <section className="border border-neutral-800 bg-neutral-900/50 p-5">
        <div className="flex items-start gap-4">
          <div className="text-3xl flex-shrink-0">🌐</div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="font-mono font-bold text-neutral-200 text-lg">
                Reasoning Environments
              </h2>
              <span className="text-[10px] px-2 py-0.5 font-mono font-bold uppercase tracking-wide bg-emerald-900/30 text-emerald-300">
                stable
              </span>
            </div>
            <p className="font-mono text-[11px] text-neutral-500 mb-3">
              Context-Aware Configurations
            </p>
            <p className="text-xs text-neutral-300 leading-relaxed mb-3">
              Per-domain environment bindings store domain-specific config: API endpoints, required tools, and linked rubric IDs. Retrieved at runtime to scope agent context precisely.
            </p>
            <div className="text-xs text-emerald-300/90 space-y-1">
              <p>✓ Consistent context across agent sessions</p>
              <p>✓ Environment-specific rubric auto-binding</p>
              <p>✓ Reduces context bloat with targeted config</p>
            </div>
          </div>
        </div>
      </section>

      {/* Environments List */}
      {items.length === 0 ? (
        <div className="text-neutral-500 text-center py-12">
          <div className="text-4xl mb-4">🌐</div>
          <p className="text-lg">No environments configured</p>
        </div>
      ) : (
        <div className="space-y-3">
      {items.map((e, i) => {
        const details = e.environment.details as Record<string, unknown> | undefined;
        const isExpanded = expandedId === e.environment.id;
        const isActive = e.environment.status === "active";

        return (
          <div
            key={i}
            className="border border-neutral-800 bg-neutral-900/50 overflow-hidden transition-all"
          >
            {/* Header */}
            <button
              onClick={() =>
                setExpandedId(expandedId === e.environment.id ? null : e.environment.id)
              }
              className="w-full px-5 py-4 text-left hover:bg-neutral-800/50 transition-colors flex items-start justify-between"
            >
              <div className="flex-1 flex items-start gap-3 min-w-0">
                {/* Status indicator */}
                <span
                  className={`w-2 h-2 mt-1.5 flex-shrink-0 ${
                    isActive ? "bg-emerald-500" : "bg-neutral-500"
                  }`}
                />

                {/* Title & Details */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-amber-400 font-mono text-xs transition-transform ${
                        isExpanded ? "rotate-90" : ""
                      }`}
                    >
                      ❯
                    </span>
                    <h3 className="font-mono font-bold text-neutral-200">
                      {e.environment.name || e.environment.id}
                    </h3>
                  </div>
                  <p className="text-xs text-neutral-500">
                    {e.environment.id}
                  </p>
                </div>
              </div>
            </button>

            {/* Expanded Content */}
            {isExpanded && (
              <div className="border-t border-neutral-800 bg-neutral-950/50 px-5 py-4 space-y-4">
                {details && (
                  <>
                    {/* Domain */}
                    <div>
                      <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                        <span>❯</span> domain
                      </div>
                      <div className="text-sm text-neutral-300 font-mono">
                        {(details.domain as string) || "—"}
                      </div>
                    </div>

                    {/* Description */}
                    {Boolean(details.description) && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                          <span>❯</span> description
                        </div>
                        <div className="text-xs text-neutral-300 leading-relaxed">
                          {String(details.description)}
                        </div>
                      </div>
                    )}

                    {/* Triggers, Forbidden, Required, Escalate */}
                    <div className="grid gap-3 sm:grid-cols-2">
                      {Boolean(details.triggers) && (
                        <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                            Triggers
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {(details.triggers as string[]).map((t, j) => (
                              <span
                                key={j}
                                className="px-2 py-0.5 bg-emerald-900/30 text-emerald-400 text-xs font-mono"
                              >
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {Boolean(details.forbidden) && (
                        <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                            Forbidden
                          </div>
                          <ul className="space-y-1">
                            {(details.forbidden as string[]).map((f, j) => (
                              <li key={j} className="text-xs text-neutral-300 flex items-start gap-1">
                                <span className="text-red-400 flex-shrink-0">✗</span>
                                <span>{f}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {Boolean(details.required) && (
                        <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                            Required
                          </div>
                          <ul className="space-y-1">
                            {(details.required as string[]).map((r, j) => (
                              <li key={j} className="text-xs text-neutral-300 flex items-start gap-1">
                                <span className="text-emerald-400 flex-shrink-0">✓</span>
                                <span>{r}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {Boolean(details.escalate) && (
                        <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                          <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                            Escalate
                          </div>
                          <ul className="space-y-1">
                            {(details.escalate as string[]).map((r, j) => (
                              <li key={j} className="text-xs text-neutral-300 flex items-start gap-1">
                                <span className="text-amber-400 flex-shrink-0">⚠</span>
                                <span>{r}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>

                    {/* High Risk Tools */}
                    {Boolean(details.high_risk_tools) && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                          <span>❯</span> high risk tools
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {(details.high_risk_tools as string[]).map((t, j) => (
                            <span
                              key={j}
                              className="px-2 py-0.5 bg-red-900/30 text-red-400 text-xs font-mono"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Related Blocks */}
                    {Boolean(details.related_blocks) && (
                      <div>
                        <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono flex items-center gap-1">
                          <span>❯</span> related blocks
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {(details.related_blocks as string[]).map((b, j) => (
                            <span key={j} className="px-2 py-0.5 bg-neutral-800 text-neutral-400 text-xs font-mono">
                              {b}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}

                {/* Rubric */}
                {e.rubric && (
                  <div className="pt-2 border-t border-neutral-800">
                    <div className="text-[10px] uppercase tracking-widest text-neutral-500 mb-2 font-mono">
                      Rubric
                    </div>
                    <div className="border border-neutral-800 p-3 bg-neutral-900/30">
                      <div className="text-sm text-neutral-300">
                        <span className="text-blue-300 font-mono">{e.rubric.domain}</span>
                        <span className="text-neutral-600"> • </span>
                        <span className="text-neutral-500">
                          {e.rubric.required_checks.length} checks
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
      )}
    </div>
  );
}