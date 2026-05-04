import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  type MemoryBlock,
  type MemoryRecallPassage,
  type Trace,
} from "../api";
import MemoryBlockCard from "../components/MemoryBlockCard";
import ArchivalSearchBox from "../components/ArchivalSearchBox";

interface EditDraft {
  block: MemoryBlock;
  nextValue: string;
}

export default function Memory() {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [blocks, setBlocks] = useState<MemoryBlock[]>([]);
  const [activeAgentId, setActiveAgentId] = useState("");
  const [recallResults, setRecallResults] = useState<MemoryRecallPassage[]>([]);
  const [loadingBlocks, setLoadingBlocks] = useState(false);
  const [loadingRecall, setLoadingRecall] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [conflictMessage, setConflictMessage] = useState<string | null>(null);

  useEffect(() => {
    api
      .traces(200, 0)
      .then((data) => {
        setTraces(data);
        const firstAgent =
          data.find((trace) => trace.agent)?.agent || "atelier:code";
        setActiveAgentId(firstAgent);
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (!activeAgentId) return;

    setLoadingBlocks(true);
    setConflictMessage(null);
    api
      .memoryBlocks(activeAgentId)
      .then((result) => {
        setBlocks(Array.isArray(result) ? result : [result]);
        setLoadingBlocks(false);
      })
      .catch((err) => {
        setError(String(err));
        setBlocks([]);
        setLoadingBlocks(false);
      });
  }, [activeAgentId]);

  const distinctAgentIds = useMemo(() => {
    const fromTraces = traces.map((trace) => trace.agent).filter(Boolean);
    if (activeAgentId && !fromTraces.includes(activeAgentId)) {
      fromTraces.unshift(activeAgentId);
    }
    return [...new Set(fromTraces)];
  }, [traces, activeAgentId]);

  const pinnedBlocks = useMemo(
    () => blocks.filter((block) => block.pinned),
    [blocks],
  );

  const recentBlocks = useMemo(
    () =>
      [...blocks]
        .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
        .slice(0, 10),
    [blocks],
  );

  const runRecallSearch = (query: string) => {
    if (!query || !activeAgentId) {
      setRecallResults([]);
      return;
    }

    setLoadingRecall(true);
    api
      .memoryRecall({
        agent_id: activeAgentId,
        query,
        top_k: 10,
      })
      .then((result) => {
        setRecallResults(result.passages);
        setLoadingRecall(false);
      })
      .catch((err) => {
        setError(String(err));
        setRecallResults([]);
        setLoadingRecall(false);
      });
  };

  const openEdit = (block: MemoryBlock) => {
    setConflictMessage(null);
    setEditDraft({ block, nextValue: block.value });
  };

  const submitEdit = async () => {
    if (!editDraft) return;

    try {
      const result = await api.memoryUpsertBlock({
        agent_id: editDraft.block.agent_id,
        label: editDraft.block.label,
        value: editDraft.nextValue,
        expected_version: editDraft.block.version,
        pinned: editDraft.block.pinned,
        description: editDraft.block.description,
        read_only: editDraft.block.read_only,
        limit_chars: editDraft.block.limit_chars,
      });

      setBlocks((prev) =>
        prev.map((block) =>
          block.id === editDraft.block.id
            ? {
                ...block,
                value: editDraft.nextValue,
                version: result.version,
                updated_at: new Date().toISOString(),
              }
            : block,
        ),
      );
      setEditDraft(null);
      setConflictMessage(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflictMessage(
          "Version conflict detected (409). Refresh memory blocks and retry your edit.",
        );
        return;
      }
      setError(String(err));
    }
  };

  return (
    <div className="space-y-6">
      <header className="pb-3 border-b border-neutral-800">
        <h1 className="font-mono text-base text-neutral-200 font-bold">
          Memory
        </h1>
        <p className="text-xs text-neutral-500 mt-1">
          Core memory blocks and archival recall for the active agent.
        </p>
      </header>

      {error && <p className="text-xs text-red-400">{error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <section>
          <div className="flex items-center justify-between gap-3 pb-3 border-b border-neutral-800">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-500">
              Core Blocks
            </h2>
            <label className="text-xs text-neutral-400 flex items-center gap-2">
              Agent
              <select
                aria-label="Filter memory by agent"
                value={activeAgentId}
                onChange={(event) => setActiveAgentId(event.target.value)}
                className="bg-transparent border border-neutral-700 px-2 py-1 text-xs text-neutral-200"
              >
                {distinctAgentIds.map((agentId) => (
                  <option key={agentId} value={agentId}>
                    {agentId}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {loadingBlocks && (
            <p className="text-xs text-neutral-500 pt-3">
              Loading memory blocks...
            </p>
          )}

          {!loadingBlocks && (
            <div className="pt-3 space-y-4">
              <div>
                <h3 className="text-[11px] uppercase tracking-widest text-neutral-600">
                  Pinned
                </h3>
                {pinnedBlocks.length === 0 ? (
                  <p className="text-xs text-neutral-600 mt-2">
                    No pinned blocks for this agent.
                  </p>
                ) : (
                  pinnedBlocks.map((block) => (
                    <MemoryBlockCard
                      key={block.id}
                      block={block}
                      onEdit={openEdit}
                    />
                  ))
                )}
              </div>

              <div>
                <h3 className="text-[11px] uppercase tracking-widest text-neutral-600">
                  Recent
                </h3>
                {recentBlocks.length === 0 ? (
                  <p className="text-xs text-neutral-600 mt-2">
                    No recent blocks.
                  </p>
                ) : (
                  recentBlocks.map((block) => (
                    <MemoryBlockCard
                      key={block.id}
                      block={block}
                      onEdit={openEdit}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </section>

        <section>
          <div className="pb-3 border-b border-neutral-800">
            <h2 className="text-[11px] uppercase tracking-widest text-neutral-500 mb-3">
              Archival Search
            </h2>
            <ArchivalSearchBox
              loading={loadingRecall}
              onSearch={runRecallSearch}
            />
          </div>

          <div className="pt-3">
            {recallResults.length === 0 ? (
              <p className="text-xs text-neutral-600">
                No archival passages yet.
              </p>
            ) : (
              <ul className="space-y-3">
                {recallResults.map((passage) => (
                  <li
                    key={passage.id}
                    className="py-2 border-b border-neutral-800"
                  >
                    <p className="text-xs text-neutral-300 whitespace-pre-wrap leading-relaxed">
                      {passage.text}
                    </p>
                    <div className="mt-1">
                      {passage.source_ref ? (
                        <a
                          href={passage.source_ref}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-amber-300 underline"
                        >
                          Source
                        </a>
                      ) : (
                        <span className="text-xs text-neutral-600">
                          No source
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      {editDraft && (
        <div
          className="fixed inset-0 bg-black/60 z-40 flex items-center justify-center px-4"
          role="dialog"
          aria-modal="true"
          aria-label="Memory block diff modal"
        >
          <div className="w-full max-w-3xl bg-neutral-950 border border-neutral-700 p-4">
            <h2 className="text-sm font-bold text-neutral-200 font-mono">
              Review memory block update
            </h2>
            <p className="text-xs text-neutral-500 mt-1">
              Label: {editDraft.block.label}
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div>
                <h3 className="text-[11px] uppercase tracking-widest text-neutral-500 mb-1">
                  Current
                </h3>
                <pre className="text-xs text-neutral-300 border border-neutral-800 p-3 whitespace-pre-wrap min-h-40">
                  {editDraft.block.value}
                </pre>
              </div>
              <div>
                <label
                  htmlFor="memory-next-value"
                  className="text-[11px] uppercase tracking-widest text-neutral-500 mb-1 block"
                >
                  New
                </label>
                <textarea
                  id="memory-next-value"
                  aria-label="Edit memory block value"
                  value={editDraft.nextValue}
                  onChange={(event) =>
                    setEditDraft((prev) =>
                      prev ? { ...prev, nextValue: event.target.value } : prev,
                    )
                  }
                  className="w-full text-xs text-neutral-200 border border-neutral-800 bg-transparent p-3 min-h-40 focus:outline-none focus:border-amber-500/60"
                />
              </div>
            </div>

            {conflictMessage && (
              <p className="text-xs text-red-400 mt-3">{conflictMessage}</p>
            )}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                aria-label="Cancel memory block edit"
                onClick={() => setEditDraft(null)}
                className="text-xs px-3 py-2 border border-neutral-700 text-neutral-300"
              >
                Cancel
              </button>
              <button
                type="button"
                aria-label="Save memory block edit"
                onClick={submitEdit}
                className="text-xs px-3 py-2 border border-amber-500/50 text-amber-300"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
