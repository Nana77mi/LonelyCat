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

export type Conversation = {
  id: string;
  title: string;
  created_at: string; // ISO 8601 格式
  updated_at: string; // ISO 8601 格式
};

export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string; // ISO 8601 格式
  source_ref?: {
    kind: "chat" | "run" | "connector" | "manual";
    ref_id: string;
    excerpt: string | null;
  } | null;
  meta_json?: Record<string, unknown> | null;
  client_msg_id?: string | null;
};

/**
 * POST /conversations/{id}/messages 的返回结构
 * 
 * 当 role 不传（chat 模式）时：
 * - user_message: 创建的 user 消息
 * - assistant_message: worker 处理后的 assistant 消息（如果 worker 失败则为 system 错误消息）
 * 
 * 当 role 传入时：
 * - 根据 role 值，只有对应的字段非 null（user_message 或 assistant_message）
 * 
 * 注意：不需要再次拉取 messages 列表，直接使用返回的消息更新 UI 即可。
 */
export type SendMessageResponse = {
  user_message: Message | null;
  assistant_message: Message | null;
};

type ListConversationsResponse = {
  items: Conversation[];
};

type ListMessagesResponse = {
  items: Message[];
};

// ============================================================================
// API Functions
// ============================================================================

/**
 * 列出所有对话，按 updated_at 降序排列
 * 
 * @param limit 最大返回数量（可选）
 * @param offset 跳过的数量（可选）
 * @returns 对话列表
 */
export const listConversations = async (
  limit?: number,
  offset?: number
): Promise<ListConversationsResponse> => {
  const url = buildUrl("/conversations", {
    limit: limit?.toString(),
    offset: offset?.toString(),
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch conversations", response));
  }
  return await parseJson<ListConversationsResponse>(response);
};

/**
 * 创建新对话
 * 
 * @param title 对话标题（可选，默认为 "New chat"）
 * @returns 创建的对话对象
 */
export const createConversation = async (title?: string): Promise<Conversation> => {
  const url = buildUrl("/conversations");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || "New chat" }),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to create conversation", response));
  }
  return await parseJson<Conversation>(response);
};

/**
 * 获取指定对话的所有消息，按 created_at 升序排列
 * 
 * @param conversationId 对话 ID
 * @param limit 最大返回数量（可选）
 * @param offset 跳过的数量（可选）
 * @returns 消息列表
 */
export const listMessages = async (
  conversationId: string,
  limit?: number,
  offset?: number
): Promise<ListMessagesResponse> => {
  const url = buildUrl(`/conversations/${conversationId}/messages`, {
    limit: limit?.toString(),
    offset: offset?.toString(),
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch messages", response));
  }
  return await parseJson<ListMessagesResponse>(response);
};

/**
 * 发送消息到指定对话（chat 模式）
 * 
 * 此函数不传 role 参数，后端会自动：
 * 1. 创建 user 消息
 * 2. 调用 worker 处理消息
 * 3. 创建 assistant 消息（或 system 错误消息）
 * 
 * @param conversationId 对话 ID
 * @param content 消息内容
 * @param personaId Persona ID（可选，用于 agent worker）
 * @returns 包含 user_message 和 assistant_message 的响应对象
 */
export const sendMessage = async (
  conversationId: string,
  content: string,
  personaId?: string
): Promise<SendMessageResponse> => {
  const url = buildUrl(`/conversations/${conversationId}/messages`, {
    persona_id: personaId,
  });
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to send message", response));
  }
  return await parseJson<SendMessageResponse>(response);
};
