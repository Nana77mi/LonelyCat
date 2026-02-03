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
  created_at: string;
  updated_at: string;
};

export type CreateRunRequest = {
  type: string;
  title?: string;
  conversation_id?: string | null;
  input?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
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
