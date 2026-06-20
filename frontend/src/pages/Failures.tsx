import { useEffect, useState } from "react";
import { api, type Cluster } from "../api";
import {
  Alert,
  Chip,
  DisclosureCard,
  EmptyState,
  FeaturePanel,
  FieldLabel,
} from "../components/WorkbenchUI";

export default function Failures() {
  const [items, setItems] = useState<Cluster[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .clusters()
      .then(setItems)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <Alert tone="danger" description={err} />;
  if (!items) return <EmptyState title="Loading failure clusters…" className="p-6" />;

  return (
    <div className="space-y-6">
      <FeaturePanel
        icon="🚨"
        title="Failure Analyzer"
        subtitle="Recurring Error Detection & Rescue"
        description="Clusters traces by error signature. Detects repeated failures and generates rescue procedures automatically. Surfaces top failure patterns for visibility."
        bullets={[
          "Stops agents from retrying known dead-end paths",
          "Auto-generates rescue blocks from failure clusters",
          "Quantifies failure impact across the system",
        ]}
      />

      {/* Failure Clusters */}
      {items.length === 0 ? (
        <EmptyState
          icon="✅"
          title="No failure clusters detected"
          description="Your agents are running smoothly!"
        />
      ) : (
        <div className="space-y-3">
          {items.map((c, i) => {
            const isExpanded = expandedId === c.id;
            const severityTone =
              c.severity === "high"
                ? "red"
                : c.severity === "medium"
                  ? "amber"
                  : "neutral";

            return (
              <DisclosureCard
                key={i}
                open={isExpanded}
                onToggle={() =>
                  setExpandedId(expandedId === c.id ? null : c.id)
                }
                contentClassName="space-y-4"
                header={
                  <div className="flex min-w-0 items-start gap-3">
                    <Chip tone={severityTone}>{c.severity}</Chip>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        <span
                          className={`text-neutral-400 font-mono text-xs transition-transform ${
                            isExpanded ? "rotate-90" : ""
                          }`}
                        >
                          ❯
                        </span>
                        <span className="font-mono font-bold text-neutral-200 text-sm">
                          {c.domain}
                        </span>
                      </div>
                      <p className="text-xs text-neutral-400">
                        {c.trace_ids.length} trace
                        {c.trace_ids.length !== 1 ? "s" : ""} · ID: {c.id}
                      </p>
                    </div>
                  </div>
                }
              >
                    {/* Fingerprint */}
                    <div>
                      <FieldLabel className="mb-2">❯ fingerprint</FieldLabel>
                      <div className="text-xs font-mono text-red-300 whitespace-pre-wrap break-words bg-neutral-950 p-2 border border-neutral-800">
                        {c.fingerprint}
                      </div>
                    </div>

                    {/* Sample Errors */}
                    {c.sample_errors && c.sample_errors.length > 0 && (
                      <div>
                        <FieldLabel className="mb-2">❯ sample errors</FieldLabel>
                        <div className="space-y-1">
                          {c.sample_errors.map((e, j) => (
                            <div
                              key={j}
                              className="text-xs font-mono text-neutral-400 bg-neutral-950 p-2 border border-neutral-800"
                            >
                              {e}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Suggested Block */}
                    {c.suggested_block_title && (
                      <div>
                        <FieldLabel className="mb-2">❯ suggested block</FieldLabel>
                        <div className="text-sm text-neutral-300 bg-neutral-950 p-2 border border-neutral-800">
                          {c.suggested_block_title}
                        </div>
                      </div>
                    )}

                    {/* Suggested Rubric Check */}
                    {c.suggested_rubric_check && (
                      <div>
                        <FieldLabel className="mb-2">
                          ❯ suggested rubric check
                        </FieldLabel>
                        <div className="text-sm font-mono text-blue-300 bg-neutral-950 p-2 border border-neutral-800">
                          {c.suggested_rubric_check}
                        </div>
                      </div>
                    )}

                    {/* Suggested Eval Case */}
                    {c.suggested_eval_case && (
                      <div>
                        <FieldLabel className="mb-2">❯ suggested eval case</FieldLabel>
                        <div className="text-sm font-mono text-neutral-400 bg-neutral-950 p-2 border border-neutral-800">
                          {c.suggested_eval_case}
                        </div>
                      </div>
                    )}

                    {/* Suggested Prompt */}
                    {c.suggested_prompt && (
                      <div>
                        <FieldLabel className="mb-2">❯ suggested prompt</FieldLabel>
                        <pre className="text-xs text-neutral-400 whitespace-pre-wrap break-words bg-neutral-950 p-2 border border-neutral-800 overflow-x-auto">
                          {c.suggested_prompt}
                        </pre>
                      </div>
                    )}

                    {/* Trace IDs */}
                    {c.trace_ids && c.trace_ids.length > 0 && (
                      <div className="pt-2 border-t border-neutral-800">
                        <FieldLabel className="mb-2">❯ trace ids</FieldLabel>
                        <div className="flex flex-wrap gap-1">
                          {c.trace_ids.slice(0, 10).map((t, j) => (
                            <span
                              key={j}
                              className="text-xs font-mono text-neutral-400 bg-neutral-950 px-2 py-0.5 border border-neutral-800"
                            >
                              {t}
                            </span>
                          ))}
                          {c.trace_ids.length > 10 && (
                            <span className="text-xs text-neutral-400">
                              +{c.trace_ids.length - 10} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}
              </DisclosureCard>
            );
          })}
        </div>
      )}
    </div>
  );
}
