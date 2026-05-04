const BASE = "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok)
    throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new ApiError(
      res.status,
      detail ? `${res.status} ${detail}` : `${res.status} ${res.statusText}`,
    );
  }
  return res.json();
}

export interface OverviewStats {
  total_traces: number;
  total_blocks: number;
  total_rubrics: number;
  total_environments: number;
  total_clusters: number;
  total_raw_tokens_estimate: number;
  total_saved_tokens_estimate: number;
  total_compressed_tokens_estimate: number;
  average_compression_ratio: number;
  estimated_total_cost_usd: number;
  estimated_saved_cost_usd: number;
  usd_per_1k_tokens: number;
  is_estimate: boolean;
}

export interface PlanRecord {
  trace_id: string;
  domain: string;
  task: string;
  status: string;
  plan_checks: { name: string; passed: boolean; detail?: string }[];
}

export interface ToolCall {
  name: string;
  args_hash: string;
  count: number;
  args?: Record<string, unknown>;
  result_summary?: string;
}

export interface CommandRecord {
  command: string;
  exit_code?: number | null;
  stdout?: string;
  stderr?: string;
}

export interface FileEditRecord {
  path: string;
  diff?: string;
  event?: string;
}

export interface RepeatedFailure {
  signature: string;
  count: number;
}

export interface ValidationResult {
  name: string;
  passed: boolean;
  detail?: string;
}

export interface Trace {
  id: string;
  run_id?: string;
  agent: string;
  domain?: string;
  task: string;
  status: string;
  files_touched: (string | FileEditRecord)[];
  tools_called: ToolCall[];
  commands_run: (string | CommandRecord)[];
  errors_seen: string[];
  repeated_failures: RepeatedFailure[];
  diff_summary?: string;
  output_summary?: string;
  validation_results: ValidationResult[];
  reasoning?: string[];
  created_at: string;
  note?: string;
  conversations?: ConversationEntry[];
  trace?: NestedTrace;
  raw_artifact_ids?: string[];
  _live?: boolean; // true for RunLedger sessions not yet committed to SQLite
}

export interface ConversationEntry {
  kind: string;
  at: string;
  summary: string;
  content?: string;
}

export interface NestedTrace {
  id: string;
  run_id: string;
  agent: string;
  domain: string;
  task: string;
  status: string;
  files_touched: string[];
  tools_called: { name: string; args_hash: string; count: number }[];
  commands_run: string[];
  errors_seen: string[];
  repeated_failures: string[];
  diff_summary: string;
  output_summary: string;
  validation_results: any[];
  raw_artifact_ids: string[];
  created_at: string;
}

export interface ReasonBlock {
  id: string;
  domain: string;
  title: string;
  status: string;
  // content fields
  situation: string;
  procedure: string[];
  dead_ends: string[];
  verification: string[];
  failure_signals: string[];
  when_not_to_apply: string;
  // match hints
  task_types: string[];
  triggers: string[];
  file_patterns: string[];
  tool_patterns: string[];
  // stats
  usage_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
  updated_at?: string;
}

export interface Cluster {
  id: string;
  domain: string;
  fingerprint: string;
  trace_ids: string[];
  sample_errors: string[];
  suggested_block_title: string;
  suggested_rubric_check: string;
  suggested_eval_case: string;
  suggested_prompt: string;
  severity: string;
}

export interface Environment {
  id: string;
  name: string;
  status: string;
  details?: Record<string, unknown>;
  rubric_id?: string;
}

export interface EnvironmentSummary {
  environment: Environment;
  rubric?: {
    id: string;
    domain: string;
    required_checks: string[];
  };
}

export interface SavingsPerOp {
  op_key: string;
  domain?: string;
  task_sample?: string;
  baseline_cost_usd: number;
  last_cost_usd: number;
  current_cost_usd: number;
  delta_vs_last_usd: number;
  delta_vs_base_usd: number;
  pct_vs_base: number;
  calls_count: number;
}

export interface SavingsSummary {
  operations_tracked: number;
  total_calls: number;
  would_have_cost_usd: number;
  actually_cost_usd: number;
  saved_usd: number;
  saved_pct: number;
  per_operation: SavingsPerOp[];
}

export interface SavingsByDay {
  day: string;
  naive: number;
  actual: number;
}

export interface SavingsSummaryV2 {
  window_days: number;
  total_naive_tokens: number;
  total_actual_tokens: number;
  reduction_pct: number;
  per_lever: Record<string, number>;
  by_day: SavingsByDay[];
  saved_usd?: number;
  saved_pct?: number;
  would_have_cost_usd?: number;
  actually_cost_usd?: number;
  total_calls?: number;
}

export interface CallEntry {
  run_id: string;
  domain?: string;
  task?: string;
  operation: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  lessons_used: string[];
  op_key: string;
  at: string;
}

export interface Rubric {
  id: string;
  domain: string;
  name: string;
  required_checks: string[];
  created_at: string;
  updated_at?: string;
}

export interface MCPStatus {
  tool_name: string;
  available: boolean;
  description?: string;
}

export interface HostAdapter {
  name: string;
  status: "installed" | "not_installed" | "partial";
  config_path?: string;
  mcp_connected: boolean;
}

export interface Skill {
  name: string;
  description: string;
  content: string;
}

export interface MemoryBlock {
  id: string;
  agent_id: string;
  label: string;
  value: string;
  limit_chars: number;
  description: string;
  read_only: boolean;
  metadata: Record<string, unknown>;
  pinned: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MemoryUpsertBlockResult {
  id: string;
  version: number;
}

export interface MemoryRecallPassage {
  id: string;
  text: string;
  source_ref: string;
  tags: string[];
}

export interface MemoryRecallResult {
  passages: MemoryRecallPassage[];
  recall_id: string;
}

export interface RunInspectorData {
  run_id: string;
  pinned_blocks: string[];
  recalled_passages: Array<{ id: string; source_ref: string }>;
  summarized_events_count: number;
  tokens_pre: number | null;
  tokens_post: number | null;
}

export const api = {
  overview: () => get<OverviewStats>("/overview"),
  plans: (limit = 50) => get<PlanRecord[]>(`/plans?limit=${limit}`),
  traces: (limit = 50, offset = 0) =>
    get<Trace[]>(`/traces?limit=${limit}&offset=${offset}`),
  trace: (id: string) => get<Trace>(`/v1/traces/${id}`),
  ledger: (run_id: string) => get<any>(`/ledgers/${run_id}`),
  clusters: () => get<Cluster[]>("/clusters"),
  environments: () => get<EnvironmentSummary[]>("/environments"),
  blocks: () => get<ReasonBlock[]>("/blocks"),
  block: (id: string) => get<ReasonBlock>(`/blocks/${id}`),
  savings: () => get<SavingsSummary>("/savings"),
  savingsSummary: (windowDays = 14) =>
    get<SavingsSummaryV2>(`/v1/savings/summary?window_days=${windowDays}`),
  calls: (limit = 200) => get<CallEntry[]>(`/calls?limit=${limit}`),
  rubrics: () => get<Rubric[]>("/v1/rubrics"),
  rubric: (id: string) => get<Rubric>(`/v1/rubrics/${id}`),
  mcp_status: () => get<MCPStatus[]>("/mcp/status"),
  hosts: () => get<HostAdapter[]>("/hosts"),
  skills: () => get<Skill[]>("/skills"),
  skill: (name: string) => get<Skill>(`/skills/${name}`),
  memoryBlocks: (agentId?: string, label?: string) => {
    const params = new URLSearchParams();
    if (agentId) params.set("agent_id", agentId);
    if (label) params.set("label", label);
    const suffix = params.size ? `?${params.toString()}` : "";
    return get<MemoryBlock[] | MemoryBlock>(`/v1/memory/blocks${suffix}`);
  },
  memoryUpsertBlock: (payload: {
    agent_id: string;
    label: string;
    value: string;
    expected_version: number;
    pinned: boolean;
    description?: string;
    read_only?: boolean;
    limit_chars?: number;
    actor?: string;
  }) => post<MemoryUpsertBlockResult>("/v1/memory/blocks", payload),
  memoryRecall: (payload: {
    agent_id: string;
    query: string;
    top_k?: number;
    tags?: string[];
    since?: string;
  }) => post<MemoryRecallResult>("/v1/memory/recall", payload),
};
