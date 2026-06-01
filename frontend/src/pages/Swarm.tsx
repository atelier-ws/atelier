import { useEffect, useMemo, useState } from "react";
import { GitBranch, RefreshCw, SquareTerminal } from "lucide-react";
import {
  api,
  ApiError,
  type SwarmAcceptedCommit,
  type SwarmArtifactRef,
  type SwarmRunDetailResponse,
  type SwarmRunListItem,
} from "../api";
import {
  Button,
  Card,
  Chip,
  FieldLabel,
  MetricCard,
  PageHero,
  SectionHeader,
  Select,
  SnippetCard,
  cx,
} from "../components/WorkbenchUI";

function fmtDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function statusTone(
  value: string
): "emerald" | "amber" | "red" | "purple" | "neutral" {
  if (value === "success") return "emerald";
  if (value === "running" || value === "pending") return "amber";
  if (value === "failed" || value === "stopped") return "red";
  if (value === "applying") return "purple";
  return "neutral";
}

function planningTone(
  value?: string | null
): "cyan" | "amber" | "neutral" | "purple" {
  if (value === "open-ended") return "purple";
  if (value === "bounded") return "cyan";
  if (value === "adaptive") return "amber";
  return "neutral";
}

function artifactSummary(artifacts: SwarmArtifactRef[]): string {
  if (!artifacts.length) return "No exported artifacts";
  return artifacts.map((artifact) => artifact.label).join(", ");
}

function commitLabel(commit: SwarmAcceptedCommit): string {
  if (commit.commit_ref) return commit.commit_ref;
  if (commit.patch_path) return commit.patch_path;
  return commit.child_id;
}

export default function Swarm() {
  const [runs, setRuns] = useState<SwarmRunListItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SwarmRunDetailResponse | null>(null);
  const [logs, setLogs] = useState("");
  const [selectedChildId, setSelectedChildId] = useState<string>("");
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [refreshingLogs, setRefreshingLogs] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = async (preferredRunId?: string | null) => {
    setLoadingRuns(true);
    try {
      const payload = await api.swarmRuns();
      setRuns(payload);
      setSelectedRunId((current) => {
        const candidate = preferredRunId ?? current;
        if (candidate && payload.some((item) => item.run_id === candidate)) {
          return candidate;
        }
        return payload[0]?.run_id ?? null;
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load swarm runs");
      setRuns([]);
      setSelectedRunId(null);
      setDetail(null);
      setLogs("");
    } finally {
      setLoadingRuns(false);
    }
  };

  const loadRunDetail = async (runId: string) => {
    setLoadingDetail(true);
    try {
      const payload = await api.swarmRun(runId);
      setDetail(payload);
      const defaultChild =
        payload.run.children.find((child) => child.status === "running")?.child_id ??
        payload.run.children[0]?.child_id ??
        "";
      setSelectedChildId((current) => {
        if (current && payload.run.children.some((child) => child.child_id === current)) {
          return current;
        }
        return defaultChild;
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load swarm detail");
      setDetail(null);
      setLogs("");
    } finally {
      setLoadingDetail(false);
    }
  };

  const loadLogs = async (runId: string, childId: string) => {
    setRefreshingLogs(true);
    try {
      const payload = await api.swarmLogs(runId, childId || undefined);
      setLogs(payload.content || "");
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setLogs("No logs captured yet for this run.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to load logs");
      }
    } finally {
      setRefreshingLogs(false);
    }
  };

  useEffect(() => {
    void loadRuns();
    const intervalId = window.setInterval(() => {
      void loadRuns(selectedRunId);
    }, 15000);
    return () => window.clearInterval(intervalId);
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    void loadRunDetail(selectedRunId);
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !detail) return;
    void loadLogs(selectedRunId, selectedChildId);
  }, [selectedRunId, selectedChildId, detail]);

  const selectedRun = useMemo(
    () => runs.find((item) => item.run_id === selectedRunId) ?? null,
    [runs, selectedRunId]
  );

  const handleStop = async () => {
    if (!selectedRunId) return;
    setStopping(true);
    try {
      await api.stopSwarmRun(selectedRunId);
      await loadRuns(selectedRunId);
      await loadRunDetail(selectedRunId);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop swarm run");
    } finally {
      setStopping(false);
    }
  };

  const totalAccepted = runs.reduce(
    (count, item) => count + item.accepted_child_ids.length,
    0
  );
  const activeRuns = runs.filter((item) => item.status === "running").length;

  return (
    <div className="space-y-8 px-6 py-8">
      <PageHero
        eyebrow="Swarm"
        title="Adaptive swarm control plane"
        description="Inspect live swarm waves, export the accepted manifests, and copy apply commands without leaving the dashboard."
        tone="purple"
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <MetricCard
            label="Runs discovered"
            value={loadingRuns ? "…" : String(runs.length)}
            detail="local swarm history"
          />
          <MetricCard
            label="Active runs"
            value={String(activeRuns)}
            detail={`${totalAccepted} accepted candidates`}
            tone={activeRuns > 0 ? "amber" : "neutral"}
          />
        </div>
      </PageHero>

      {error && (
        <Card className="border-red-900/40 bg-red-950/20 p-4 text-sm text-red-100">
          {error}
        </Card>
      )}

      <section className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <Card className="border-neutral-800 bg-neutral-950/60 p-5">
          <SectionHeader
            eyebrow="Control"
            title="Swarm runs"
            description="Recent swarm executions discovered from the local runtime state."
            action={
              <Button size="sm" onClick={() => void loadRuns(selectedRunId)}>
                <RefreshCw size={14} className="mr-2" />
                Refresh
              </Button>
            }
          />

          <div className="mt-5 space-y-3">
            {loadingRuns && <div className="text-sm text-neutral-500">Loading swarm runs…</div>}
            {!loadingRuns && runs.length === 0 && (
              <div className="border border-dashed border-neutral-800 p-4 text-sm text-neutral-500">
                No swarm runs found yet. Start a swarm run from the CLI to populate this dashboard.
              </div>
            )}
            {runs.map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => setSelectedRunId(run.run_id)}
                className={cx(
                  "w-full border p-4 text-left transition",
                  run.run_id === selectedRunId
                    ? "border-purple-500/60 bg-purple-500/10"
                    : "border-neutral-800 bg-black/20 hover:border-neutral-600"
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="truncate text-sm font-semibold text-neutral-100">
                    {run.run_id}
                  </div>
                  <Chip tone={statusTone(run.status)}>{run.status}</Chip>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-neutral-500">
                  <span>{run.runner_name}</span>
                  {run.runner_model && <span>{run.runner_model}</span>}
                  <Chip tone={planningTone(run.planning_mode)}>
                    {run.planning_mode || "legacy"}
                  </Chip>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-neutral-400">
                  <div>
                    <FieldLabel>Wave</FieldLabel>
                    <div className="mt-1">
                      {run.current_wave} · {run.planned_runs}/{run.max_runs}
                    </div>
                  </div>
                  <div>
                    <FieldLabel>Winner</FieldLabel>
                    <div className="mt-1 truncate">
                      {run.primary_winner_child_id || "Pending"}
                    </div>
                  </div>
                </div>
                {run.running_children[0] && (
                  <div className="mt-3 text-xs text-neutral-500">
                    {run.running_children[0].child_id}:{" "}
                    {run.running_children[0].activity || "Running"}
                  </div>
                )}
              </button>
            ))}
          </div>
        </Card>

        <div className="space-y-6">
          {!selectedRunId && (
            <Card className="border-dashed border-neutral-800 bg-neutral-950/60 p-8 text-sm text-neutral-500">
              Pick a swarm run to inspect its waves, accepted commits, and apply/export artifacts.
            </Card>
          )}

          {selectedRunId && loadingDetail && !detail && (
            <Card className="border-neutral-800 bg-neutral-950/60 p-8 text-sm text-neutral-500">
              Loading swarm run detail…
            </Card>
          )}

          {detail && (
            <>
              <Card className="border-neutral-800 bg-neutral-950/60 p-5">
                <SectionHeader
                  eyebrow="Run detail"
                  title={detail.run.run_id}
                  description={`Base snapshot ${detail.run.base_snapshot_ref || detail.run.base_ref}`}
                  action={
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" onClick={() => void loadRunDetail(detail.run.run_id)}>
                        <RefreshCw size={14} className="mr-2" />
                        Refresh detail
                      </Button>
                      {detail.run.status === "running" && (
                        <Button size="sm" variant="danger" onClick={handleStop} disabled={stopping}>
                          <SquareTerminal size={14} className="mr-2" />
                          {stopping ? "Stopping…" : "Stop run"}
                        </Button>
                      )}
                    </div>
                  }
                />

                <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <MetricCard
                    label="Status"
                    value={detail.run.status}
                    detail={detail.run.mode}
                    tone={statusTone(detail.run.status)}
                  />
                  <MetricCard
                    label="Runner"
                    value={detail.run.runner_model || detail.run.runner_name}
                    detail={detail.run.runner_name}
                  />
                  <MetricCard
                    label="Fan-out"
                    value={`${selectedRun?.planned_runs ?? 0}/${detail.run.max_runs ?? detail.run.runs}`}
                    detail={detail.run.planning_mode || selectedRun?.planning_mode || "legacy"}
                    tone={planningTone(detail.run.planning_mode || selectedRun?.planning_mode)}
                  />
                  <MetricCard
                    label="Accepted"
                    value={String(detail.run.accepted_child_ids.length)}
                    detail={detail.run.primary_winner_child_id || "winner pending"}
                    tone={detail.run.accepted_child_ids.length > 0 ? "emerald" : "neutral"}
                  />
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-2">
                  <div className="border border-neutral-800 bg-black/20 p-4 text-sm text-neutral-300">
                    <FieldLabel>Execution</FieldLabel>
                    <dl className="mt-3 grid gap-2">
                      <div className="flex justify-between gap-3">
                        <dt className="text-neutral-500">Created</dt>
                        <dd>{fmtDate(detail.run.created_at)}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-neutral-500">Updated</dt>
                        <dd>{fmtDate(detail.run.updated_at)}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-neutral-500">Integration base</dt>
                        <dd className="truncate">{detail.run.integration_base_ref || "—"}</dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-neutral-500">Stop reason</dt>
                        <dd>{detail.run.stop_reason || "—"}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="border border-neutral-800 bg-black/20 p-4 text-sm text-neutral-300">
                    <FieldLabel>Export bundle</FieldLabel>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Chip tone="purple">
                        {detail.export.base_snapshot_artifact?.label || "base snapshot"}
                      </Chip>
                      {detail.export.waves.map((wave) => (
                        <Chip key={wave.wave_index} tone={planningTone(wave.planning_mode)}>
                          wave {wave.wave_index} · {wave.planning_mode}
                        </Chip>
                      ))}
                    </div>
                    <div className="mt-3 text-xs text-neutral-500">
                      {artifactSummary(detail.export.artifacts)}
                    </div>
                  </div>
                </div>
              </Card>

              <Card className="border-neutral-800 bg-neutral-950/60 p-5">
                <SectionHeader
                  eyebrow="Waves"
                  title="Adaptive fan-out summary"
                  description="Each wave records the planned fan-out, accepted children, and durable manifest artifact."
                />
                <div className="mt-5 overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="text-xs uppercase tracking-widest text-neutral-500">
                      <tr>
                        <th className="pb-3 pr-4">Wave</th>
                        <th className="pb-3 pr-4">Mode</th>
                        <th className="pb-3 pr-4">Planned</th>
                        <th className="pb-3 pr-4">Accepted</th>
                        <th className="pb-3 pr-4">Winner</th>
                        <th className="pb-3">Manifest</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.export.waves.map((wave) => (
                        <tr key={wave.wave_index} className="border-t border-neutral-900">
                          <td className="py-3 pr-4 text-neutral-200">{wave.wave_index}</td>
                          <td className="py-3 pr-4">
                            <Chip tone={planningTone(wave.planning_mode)}>
                              {wave.planning_mode}
                            </Chip>
                          </td>
                          <td className="py-3 pr-4 text-neutral-300">
                            {wave.planned_runs}/{wave.max_runs}
                          </td>
                          <td className="py-3 pr-4 text-neutral-300">
                            {wave.accepted_child_ids.join(", ") || "—"}
                          </td>
                          <td className="py-3 pr-4 text-neutral-300">
                            {wave.primary_winner_child_id || "—"}
                          </td>
                          <td className="py-3 text-neutral-500">
                            {wave.manifest_artifact?.path || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <div className="grid gap-6 xl:grid-cols-2">
                <Card className="border-neutral-800 bg-neutral-950/60 p-5">
                  <SectionHeader
                    eyebrow="Accepted commits"
                    title="Winner exports"
                    description="Commits and patch artifacts that can be transplanted into the integration worktree."
                  />
                  <div className="mt-5 space-y-3">
                    {detail.export.accepted_commits.length === 0 && (
                      <div className="text-sm text-neutral-500">
                        No accepted commits were exported for this run.
                      </div>
                    )}
                    {detail.export.accepted_commits.map((commit) => (
                      <div
                        key={`${commit.child_id}-${commit.order}`}
                        className="border border-neutral-800 bg-black/20 p-4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-sm font-semibold text-neutral-100">
                            {commitLabel(commit)}
                          </div>
                          <Chip tone="emerald">{commit.child_id}</Chip>
                        </div>
                        <div className="mt-2 text-xs text-neutral-500">
                          {artifactSummary(commit.artifacts)}
                        </div>
                        {commit.patch_path && (
                          <div className="mt-2 text-xs text-neutral-400">
                            patch: {commit.patch_path}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </Card>

                <Card className="border-neutral-800 bg-neutral-950/60 p-5">
                  <SectionHeader
                    eyebrow="Live children"
                    title="Activity and logs"
                    description="Inspect the current child branch activity and tail the latest log output."
                  />
                  <div className="mt-5 flex flex-wrap items-center gap-3">
                    <Select
                      value={selectedChildId}
                      onChange={(event) => setSelectedChildId(event.target.value)}
                      className="min-w-[260px]"
                      aria-label="Swarm child log selector"
                    >
                      <option value="">Run log</option>
                      {detail.run.children.map((child) => (
                        <option key={child.child_id} value={child.child_id}>
                          {child.child_id} · {child.status}
                        </option>
                      ))}
                    </Select>
                    <Button
                      size="sm"
                      onClick={() => void loadLogs(detail.run.run_id, selectedChildId)}
                    >
                      <RefreshCw size={14} className="mr-2" />
                      {refreshingLogs ? "Refreshing…" : "Refresh logs"}
                    </Button>
                  </div>

                  <div className="mt-5 space-y-3">
                    {detail.run.children.map((child) => (
                      <div
                        key={child.child_id}
                        className="flex items-start justify-between gap-3 border border-neutral-800 bg-black/20 p-4"
                      >
                        <div>
                          <div className="flex items-center gap-2 text-sm font-semibold text-neutral-100">
                            <GitBranch size={14} />
                            {child.child_id}
                          </div>
                          <div className="mt-2 text-xs text-neutral-500">
                            {child.current_activity || "No activity reported yet"}
                          </div>
                        </div>
                        <div className="text-right">
                          <Chip tone={statusTone(child.status)}>{child.status}</Chip>
                          <div className="mt-2 text-[11px] text-neutral-500">
                            {fmtDate(child.last_output_at || child.completed_at || child.started_at)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <pre className="mt-5 overflow-x-auto border border-neutral-800 bg-black/40 p-4 text-xs leading-relaxed text-neutral-300">
                    {logs || "No logs captured yet for this run."}
                  </pre>
                </Card>
              </div>

              <div className="grid gap-6 xl:grid-cols-2">
                <SnippetCard
                  title="Apply commands"
                  body={detail.apply.commands.join("\n") || "# No apply commands available"}
                  caption="Copy the exact commands used to transplant accepted commits."
                />
                <SnippetCard
                  title="Export manifest"
                  body={JSON.stringify(detail.export, null, 2)}
                  caption="Durable export payload exposed by the backend API."
                />
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
