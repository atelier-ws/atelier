import { useEffect, useMemo, useState } from "react";
import { api, type RunInspectorData, type Trace } from "../api";

interface RunInspectorDrawerProps {
  open: boolean;
  trace: Trace | null;
  onClose: () => void;
}

function parseInspectorData(runId: string, ledger: any): RunInspectorData {
  const events: any[] = Array.isArray(ledger?.events) ? ledger.events : [];

  const recalled = events
    .filter((event) =>
      String(event?.kind || "")
        .toLowerCase()
        .includes("recall"),
    )
    .flatMap((event) => {
      const payload = event?.payload || {};
      if (Array.isArray(payload.top_passages)) {
        return payload.top_passages.map((id: string) => ({
          id,
          source_ref: payload.source_ref || "",
        }));
      }
      if (payload.selected_passage_id) {
        return [
          {
            id: String(payload.selected_passage_id),
            source_ref: String(payload.source_ref || ""),
          },
        ];
      }
      return [];
    });

  let tokensPre: number | null = null;
  let tokensPost: number | null = null;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const payload = events[i]?.payload || {};
    const pre = payload.tokens_pre_summary ?? payload.tokens_pre;
    const post = payload.tokens_post_summary ?? payload.tokens_post;
    if (typeof pre === "number" && typeof post === "number") {
      tokensPre = pre;
      tokensPost = post;
      break;
    }
  }

  const summarizedEventsCount = events.reduce((acc, event) => {
    const payload = event?.payload || {};
    if (Array.isArray(payload.evicted_event_ids))
      return acc + payload.evicted_event_ids.length;
    if (Array.isArray(payload.summarized_events))
      return acc + payload.summarized_events.length;
    return acc;
  }, 0);

  return {
    run_id: runId,
    pinned_blocks: Array.isArray(ledger?.active_reasonblocks)
      ? ledger.active_reasonblocks
      : [],
    recalled_passages: recalled,
    summarized_events_count: summarizedEventsCount,
    tokens_pre: tokensPre,
    tokens_post: tokensPost,
  };
}

export default function RunInspectorDrawer({
  open,
  trace,
  onClose,
}: RunInspectorDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<RunInspectorData | null>(null);

  useEffect(() => {
    if (!open || !trace?.run_id) return;

    setLoading(true);
    setError(null);
    api
      .ledger(trace.run_id)
      .then((ledger) =>
        setData(parseInspectorData(trace.run_id as string, ledger)),
      )
      .catch((err) => {
        setError(String(err));
        setData({
          run_id: trace.run_id as string,
          pinned_blocks: [],
          recalled_passages: [],
          summarized_events_count: 0,
          tokens_pre: null,
          tokens_post: null,
        });
      })
      .finally(() => setLoading(false));
  }, [open, trace?.run_id]);

  const title = useMemo(() => {
    if (!trace) return "Run Inspector";
    return trace.task ? `Run Inspector: ${trace.task}` : "Run Inspector";
  }, [trace]);

  if (!open || !trace) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-40"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className="fixed right-0 top-0 h-full w-full max-w-xl bg-neutral-950 border-l border-neutral-800 z-50 p-5 overflow-y-auto transition-transform"
        role="dialog"
        aria-modal="true"
        aria-label="Run inspector drawer"
      >
        <div className="flex items-start justify-between gap-3 pb-4 border-b border-neutral-800">
          <div>
            <h2 className="font-mono text-sm text-neutral-200 font-bold">
              {title}
            </h2>
            <p className="text-[11px] text-neutral-500 mt-1">
              Run ID: {trace.run_id || "n/a"}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close run inspector"
            onClick={onClose}
            className="text-xs px-2 py-1 border border-neutral-700 text-neutral-300 hover:text-amber-300 hover:border-amber-500/50"
          >
            Close
          </button>
        </div>

        {loading && (
          <p className="text-xs text-neutral-500 pt-4">Loading run data...</p>
        )}
        {error && <p className="text-xs text-red-400 pt-4">{error}</p>}

        {data && (
          <div className="pt-4 space-y-5">
            <section>
              <h3 className="text-[11px] uppercase tracking-widest text-neutral-500 mb-2">
                Pinned Blocks
              </h3>
              {data.pinned_blocks.length === 0 ? (
                <p className="text-xs text-neutral-600">
                  No pinned blocks recorded for this run.
                </p>
              ) : (
                <ul className="space-y-1">
                  {data.pinned_blocks.map((blockId) => (
                    <li
                      key={blockId}
                      className="text-xs text-neutral-300 break-all"
                    >
                      {blockId}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="text-[11px] uppercase tracking-widest text-neutral-500 mb-2">
                Recalled Passages
              </h3>
              {data.recalled_passages.length === 0 ? (
                <p className="text-xs text-neutral-600">
                  No recalled passages captured.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.recalled_passages.map((passage) => (
                    <li
                      key={`${passage.id}-${passage.source_ref}`}
                      className="text-xs text-neutral-300 break-all"
                    >
                      <div>{passage.id}</div>
                      {passage.source_ref ? (
                        <a
                          href={passage.source_ref}
                          target="_blank"
                          rel="noreferrer"
                          className="text-amber-300 hover:text-amber-200 underline"
                        >
                          Source
                        </a>
                      ) : (
                        <span className="text-neutral-600">No source</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h3 className="text-[11px] uppercase tracking-widest text-neutral-500 mb-2">
                Summary Metrics
              </h3>
              <dl className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <dt className="text-neutral-500">Summarized events</dt>
                  <dd className="text-neutral-200 font-mono">
                    {data.summarized_events_count}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">tokens_pre</dt>
                  <dd className="text-neutral-200 font-mono">
                    {data.tokens_pre ?? "n/a"}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-500">tokens_post</dt>
                  <dd className="text-neutral-200 font-mono">
                    {data.tokens_post ?? "n/a"}
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        )}
      </aside>
    </>
  );
}
