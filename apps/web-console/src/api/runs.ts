// Priority: VITE_CORE_API_URL > VITE_API_BASE_URL > default "/api"
const baseUrl =
  import.meta.env.VITE_CORE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "/api";

/** Normalize base (no trailing slash) and path (single leading slash). */
const joinBaseUrl = (base: string, path: string) => {
  const trimmedBase = base ? base.replace(/\/+$/, "") : "";
  const trimmedPath = path ? (path.startsWith("/") ? path.replace(/^\/+/, "/") : `/${path}`) : "/";
  return trimmedBase ? `${trimmedBase}${trimmedPath}` : trimmedPath;
};

/** Build full URL for API path (used by run list and e.g. sandbox exec links). */
export const buildUrl = (path: string, params?: Record<string, string | undefined>) => {
  const joined = joinBaseUrl(baseUrl, path);
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

/** Allowlist for exec_id (e_ + alphanumeric, no path chars). Max length 64. */
export const isValidExecId = (s: string): boolean => /^e_[a-zA-Z0-9]{1,62}$/.test(s);

/** Build sandbox observation URL only when exec_id is valid; otherwise null. */
export const buildSandboxObservationUrl = (execId: string): string | null => {
  if (!isValidExecId(execId)) return null;
  return buildUrl(`sandbox/execs/${encodeURIComponent(execId)}/observation`);
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
// Constants (same semantics as backend protocol.run_constants)
// ============================================================================

/** 32 lowercase hex; matches backend TRACE_ID_PATTERN. */
export const TRACE_ID_PATTERN = /^[a-f0-9]{32}$/;

export function isValidTraceId(s: string | null | undefined): boolean {
  return typeof s === "string" && TRACE_ID_PATTERN.test(s);
}

// ============================================================================
// Type Definitions
// ============================================================================

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export type Run = {
  id: string;
  type: string;
  title?: string | null;
  status: RunStatus;
  conversation_id?: string | null;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: string | null;
  progress?: number | null;
  attempt: number;
  worker_id?: string | null;
  lease_expires_at?: string | null;
  parent_run_id?: string | null;
  canceled_at?: string | null;
  canceled_by?: string | null;
  cancel_reason?: string | null;
  created_at: string;
  updated_at: string;
};

export type CreateRunRequest = {
  type: string;
  title?: string;
  conversation_id?: string | null;
  input?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  parent_run_id?: string;
};

export type RunResponse = { run: Run };
export type RunListResponse = { items: Run[]; limit?: number; offset?: number };

// ============================================================================
// API Functions
// ============================================================================

/**
 * 创建新 Run
 * 
 * @param request 创建 Run 的请求参数
 * @returns 创建的 Run 对象
 */
export const createRun = async (request: CreateRunRequest): Promise<Run> => {
  const url = buildUrl("/runs");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to create run", response));
  }
  const data = await parseJson<RunResponse>(response);
  return data.run;
};

/**
 * 获取指定 Run
 * 
 * @param id Run ID
 * @returns Run 对象
 */
export const getRun = async (id: string): Promise<Run> => {
  const url = buildUrl(`/runs/${id}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch run", response));
  }
  const data = await parseJson<RunResponse>(response);
  return data.run;
};

/**
 * 获取指定会话的所有 Run，按 updated_at 降序排列
 * 
 * @param conversationId 会话 ID
 * @param opts 可选参数（limit, offset）
 * @returns Run 列表
 */
export const listConversationRuns = async (
  conversationId: string,
  opts?: { limit?: number; offset?: number }
): Promise<Run[]> => {
  const url = buildUrl(`/conversations/${conversationId}/runs`, {
    limit: opts?.limit?.toString(),
    offset: opts?.offset?.toString(),
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch conversation runs", response));
  }
  const data = await parseJson<RunListResponse>(response);
  return data.items;
};

/**
 * 取消指定 Run
 * 
 * @param id Run ID
 * @param cancelReason 可选的取消原因
 * @returns 更新后的 Run 对象
 */
export const cancelRun = async (id: string, cancelReason?: string): Promise<Run> => {
  const url = buildUrl(`/runs/${id}/cancel`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cancel_reason: cancelReason }),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to cancel run", response));
  }
  const data = await parseJson<RunResponse>(response);
  return data.run;
};

/**
 * 重试指定 Run（创建新 Run，复制原 Run 的 input，设置 parent_run_id）
 * 
 * @param run 要重试的 Run 对象
 * @returns 新创建的 Run 对象
 */
export const retryRun = async (run: Run): Promise<Run> => {
  return createRun({
    type: run.type,
    title: run.title || undefined,
    conversation_id: run.conversation_id || undefined,
    input: run.input,
    parent_run_id: run.id,
  });
};

/**
 * 删除指定 Run
 * 
 * @param id Run ID
 */
export const deleteRun = async (id: string): Promise<void> => {
  const url = buildUrl(`/runs/${id}`);
  const response = await fetch(url, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to delete run", response));
  }
};
