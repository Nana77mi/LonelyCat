// Priority: VITE_CORE_API_URL > VITE_API_BASE_URL > default "/api"
const baseUrl =
  import.meta.env.VITE_CORE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "/api";

const joinBaseUrl = (base: string, path: string) => {
  if (!base) {
    return path.startsWith("/") ? path : `/${path}`;
  }
  const trimmedBase = base.replace(/\/+$/, "");
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
};

const buildUrl = (path: string, params?: Record<string, string | undefined>) => {
  const joined = joinBaseUrl(baseUrl, path);
  // If baseUrl is absolute (http:// or https://), use it directly
  // Otherwise, treat as relative path (will use window.location.origin)
  const url = new URL(joined, baseUrl.startsWith("http") ? undefined : window.location.origin);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value) {
        url.searchParams.set(key, value);
      }
    });
  }
  return url.toString();
};

const parseJson = async <T>(response: Response): Promise<T> => {
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new Error(
      error instanceof Error ? `Failed to parse response: ${error.message}` : "Failed to parse response"
    );
  }
};

const readErrorBody = async (response: Response): Promise<string> => {
  const contentType = response.headers.get("content-type") ?? "";
  let body = "";
  try {
    if (contentType.includes("application/json")) {
      const data = await response.json();
      body = JSON.stringify(data);
    } else {
      body = await response.text();
    }
  } catch {
    body = "";
  }
  const trimmed = body.replace(/\s+/g, " ").trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.length > 200 ? `${trimmed.slice(0, 200)}…` : trimmed;
};

const buildErrorMessage = async (prefix: string, response: Response): Promise<string> => {
  const detail = await readErrorBody(response);
  if (!detail) {
    return `${prefix} (${response.status})`;
  }
  return `${prefix} (${response.status}): ${detail}`;
};

// ============================================================================
// Type Definitions
// ============================================================================

export type ExecutionSummary = {
  execution_id: string;
  plan_id: string;
  changeset_id: string;
  status: string;
  verdict: string;
  risk_level: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  files_changed: number;
  verification_passed: boolean;
  health_checks_passed: boolean;
  rolled_back: boolean;
  error_step: string | null;
  error_message: string | null;
  /** Phase 2.4-A: execution graph */
  correlation_id?: string | null;
  parent_execution_id?: string | null;
  trigger_kind?: string | null;
  run_id?: string | null;
  /** Phase 2.5-D: repair in graph */
  is_repair?: boolean;
  repair_for_execution_id?: string | null;
};

export type StepDetail = {
  id: number;
  step_num: number;
  step_name: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  error_code: string | null;
  error_message: string | null;
  log_ref: string | null;
};

export type ExecutionDetail = {
  execution: ExecutionSummary;
  steps: StepDetail[];
  artifact_path: string;
};

export type ArtifactInfo = {
  artifact_path: string;
  artifacts_complete: boolean;
  four_piece_set: {
    "plan.json": boolean;
    "changeset.json": boolean;
    "decision.json": boolean;
    "execution.json": boolean;
  };
  step_logs: string[];
  has_stdout: boolean;
  has_stderr: boolean;
  has_backups: boolean;
};

export type ExecutionListResponse = {
  executions: ExecutionSummary[];
  total: number;
  limit: number;
  offset: number;
};

/** Phase 2.4-A: lineage record (API returns to_dict()) */
export type ExecutionLineageRecord = Record<string, unknown> & {
  execution_id: string;
  status?: string;
  verdict?: string;
  parent_execution_id?: string | null;
  correlation_id?: string | null;
  trigger_kind?: string | null;
};

export type ExecutionLineage = {
  execution: ExecutionLineageRecord;
  ancestors: ExecutionLineageRecord[];
  descendants: ExecutionLineageRecord[];
  siblings: ExecutionLineageRecord[];
  /** Phase 2.5-A2: same correlation, latest by started_at */
  latest_in_correlation?: ExecutionLineageRecord | null;
};

export type ExecutionStatistics = {
  total_executions: number;
  by_status: Record<string, number>;
  by_verdict: Record<string, number>;
  by_risk_level: Record<string, number>;
  success_rate_percent: number;
  avg_duration_seconds: number;
};

export type ExecutionReplay = {
  execution_id: string;
  plan: {
    id: string;
    intent: string;
    risk_level: string;
    affected_paths: string[];
  };
  changeset: {
    id: string;
    changes_count: number;
    checksum: string;
  };
  decision: {
    id: string;
    verdict: string;
    risk_level_effective: string;
    reasons: string[];
    reflection_hints_used?: boolean;
    hints_digest?: string;
    suggestions?: string[];
  };
  execution: {
    status: string;
    success: boolean;
    message: string;
    files_changed: number;
    verification_passed: boolean;
    health_checks_passed: boolean;
  };
};

/** Phase 2.4-B: single event from events.jsonl */
export type ExecutionEvent = {
  event?: string;
  step_num?: number;
  step_name?: string;
  status?: string;
  duration_seconds?: number;
  timestamp?: string;
  error_code?: string;
  error_message?: string;
};

export type ExecutionEventsResponse = {
  events: ExecutionEvent[];
  total: number;
};

/**
 * Get execution events stream (Phase 2.4-B).
 *
 * @param executionId 执行ID
 * @param tail 最后 N 条，默认 500
 */
export const getExecutionEvents = async (
  executionId: string,
  tail: number = 500
): Promise<ExecutionEventsResponse> => {
  const url = buildUrl(`/executions/${executionId}/events`, { tail: tail.toString() });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch execution events", response));
  }
  return await parseJson<ExecutionEventsResponse>(response);
};

// ============================================================================
// API Functions
// ============================================================================

/**
 * 列出执行历史，按时间降序排列
 *
 * @param opts 可选参数（limit, offset, status, verdict, risk_level, since）
 * @returns 执行列表响应
 */
export const listExecutions = async (opts?: {
  limit?: number;
  offset?: number;
  status?: string;
  verdict?: string;
  risk_level?: string;
  since?: string;
  correlation_id?: string;
}): Promise<ExecutionListResponse> => {
  const url = buildUrl("/executions", {
    limit: opts?.limit?.toString(),
    offset: opts?.offset?.toString(),
    status: opts?.status,
    verdict: opts?.verdict,
    risk_level: opts?.risk_level,
    since: opts?.since,
    correlation_id: opts?.correlation_id,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch executions", response));
  }
  return await parseJson<ExecutionListResponse>(response);
};

/**
 * 获取执行详情（包含步骤timeline）
 *
 * @param executionId 执行ID
 * @returns 执行详情
 */
export const getExecution = async (executionId: string): Promise<ExecutionDetail> => {
  const url = buildUrl(`/executions/${executionId}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch execution", response));
  }
  return await parseJson<ExecutionDetail>(response);
};

/**
 * 获取执行artifact元数据
 *
 * @param executionId 执行ID
 * @returns artifact信息
 */
export const getExecutionArtifacts = async (executionId: string): Promise<ArtifactInfo> => {
  const url = buildUrl(`/executions/${executionId}/artifacts`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch execution artifacts", response));
  }
  return await parseJson<ArtifactInfo>(response);
};

/**
 * 重放执行（从artifacts）
 *
 * @param executionId 执行ID
 * @returns 重放摘要
 */
export const replayExecution = async (executionId: string): Promise<ExecutionReplay> => {
  const url = buildUrl(`/executions/${executionId}/replay`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to replay execution", response));
  }
  return await parseJson<ExecutionReplay>(response);
};

/**
 * 获取执行统计信息
 *
 * @returns 统计数据
 */
export const getExecutionStatistics = async (): Promise<ExecutionStatistics> => {
  const url = buildUrl("/executions/statistics");
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch execution statistics", response));
  }
  return await parseJson<ExecutionStatistics>(response);
};

/**
 * Get execution lineage (Phase 2.4-A): ancestors, descendants, siblings.
 *
 * @param executionId 执行ID
 * @param depth 最大深度，默认 20
 */
export const getExecutionLineage = async (
  executionId: string,
  depth: number = 20
): Promise<ExecutionLineage> => {
  const url = buildUrl(`/executions/${executionId}/lineage`, { depth: depth.toString() });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch execution lineage", response));
  }
  return await parseJson<ExecutionLineage>(response);
};

/** Phase 2.4-D: similar execution item with explainable why_similar */
export type SimilarExecutionItem = {
  execution: ExecutionLineageRecord;
  why_similar: string[];
  score: number;
};

export type SimilarExecutionsResponse = {
  similar: SimilarExecutionItem[];
};

/**
 * Get executions similar to this one (Phase 2.4-D).
 *
 * @param executionId 执行ID
 * @param limit 最多返回条数，默认 5
 */
export const getSimilarExecutions = async (
  executionId: string,
  limit: number = 5
): Promise<SimilarExecutionsResponse> => {
  const url = buildUrl(`/executions/${executionId}/similar`, {
    limit: limit.toString(),
    exclude_same_correlation: "true",
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch similar executions", response));
  }
  return await parseJson<SimilarExecutionsResponse>(response);
};

/** Phase 2.5-C2: reflection hints (hints_7d.json) */
export type ReflectionHintsResponse = {
  hot_error_steps: string[];
  false_allow_patterns: string[];
  slow_steps: string[];
  suggested_policy: string[];
  evidence_execution_ids: string[];
  window: string | null;
};

export const getReflectionHints = async (): Promise<ReflectionHintsResponse> => {
  const url = buildUrl("/reflection/hints");
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch reflection hints", response));
  }
  return await parseJson<ReflectionHintsResponse>(response);
};
