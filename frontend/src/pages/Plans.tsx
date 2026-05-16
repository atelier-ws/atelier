import { useEffect, useState } from "react";
import { api, type PlanRecord } from "../api";
import {
  Alert,
  Chip,
  DisclosureCard,
  EmptyState,
  FeaturePanel,
  FieldLabel,
} from "../components/WorkbenchUI";

export default function Plans() {
  const [items, setItems] = useState<PlanRecord[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .plans()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <Alert tone="danger" description={err} />;
  if (!items) return <EmptyState title="Loading plans…" className="p-6" />;

  return (
    <div className="space-y-6">
      <FeaturePanel
        icon="📋"
        title="Plan Validation"
        subtitle="Pre-Execution Plan Review"
        description="Agent plans are validated against reasoning context before implementation. Detects unachievable steps, missing dependencies, and violations of domain rules. Prevents wasted execution."
        bullets={[
          "Catches impossible plans early",
          "Enforces domain-specific guardrails",
          "Prevents thrashing on unachievable goals",
        ]}
      />

      {/* Plan Results */}
      {items.length === 0 ? (
        <EmptyState
          icon="📋"
          title="No plan-related validation results yet"
        />
      ) : (
        <div className="space-y-3">
          {items.map((p) => {
            const isExpanded = expandedId === p.trace_id;
            const statusTone = p.status === "success" ? "emerald" : "red";

            return (
              <DisclosureCard
                key={p.trace_id}
                open={isExpanded}
                onToggle={() =>
                  setExpandedId(expandedId === p.trace_id ? null : p.trace_id)
                }
                contentClassName="space-y-3"
                header={
                  <div className="flex min-w-0 items-start gap-3">
                    <Chip tone={statusTone}>{p.status}</Chip>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span
                          className={`text-neutral-500 font-mono text-xs transition-transform ${
                            isExpanded ? "rotate-90" : ""
                          }`}
                        >
                          ❯
                        </span>
                        <span className="font-mono font-bold text-neutral-200 text-sm">
                          {p.domain}
                        </span>
                      </div>
                      <p className="truncate text-xs text-neutral-400">
                        {p.task}
                      </p>
                    </div>
                  </div>
                }
              >
                    {/* Task Description */}
                    <div>
                      <FieldLabel className="mb-2">❯ task</FieldLabel>
                      <p className="text-sm text-neutral-300">{p.task}</p>
                    </div>

                    {/* Trace ID */}
                    <div>
                      <FieldLabel className="mb-2">❯ trace id</FieldLabel>
                      <code className="text-xs font-mono text-neutral-500 bg-neutral-950 px-2 py-1 block border border-neutral-800">
                        {p.trace_id}
                      </code>
                    </div>

                    {/* Plan Checks */}
                    <div>
                      <FieldLabel className="mb-2">❯ checks</FieldLabel>
                      <ul className="space-y-1">
                        {p.plan_checks.map((c, i) => (
                          <li
                            key={i}
                            className={`text-xs px-2 py-1 border border-neutral-800 flex items-start gap-2 ${
                              c.passed
                                ? "text-emerald-300 bg-emerald-900/10"
                                : "text-red-300 bg-red-900/10"
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
              </DisclosureCard>
            );
          })}
        </div>
      )}
    </div>
  );
}
