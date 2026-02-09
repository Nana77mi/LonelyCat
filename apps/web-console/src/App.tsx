import { useState, useCallback, useEffect, useRef } from "react";
import { Routes, Route, Navigate, useParams, useNavigate, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { ChatPage } from "./components/ChatPage";
import { RunsPanel } from "./components/RunsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { MemoryPage } from "./pages/MemoryPage";
import { ExecutionsListPage } from "./pages/ExecutionsListPage";
import { ExecutionDetailPage } from "./pages/ExecutionDetailPage";
import { listConversations, createConversation, listMessages, sendMessage, deleteConversation, updateConversation, markConversationRead } from "./api/conversations";
import { listConversationRuns, createRun, deleteRun, cancelRun, retryRun } from "./api/runs";
import type { Conversation, Message } from "./api/conversations";
import type { Run } from "./api/runs";
import "./App.css";

const App = () => {
  const navigate = useNavigate();
  const location = useLocation();
  
  // 从 URL 中提取 conversationId（因为 useParams 在 Routes 外部无法工作）
  const conversationIdMatch = location.pathname.match(/\/chat\/([^/]+)/);
  const conversationId = conversationIdMatch ? conversationIdMatch[1] : undefined;
  
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runIdToOpenForDrawer, setRunIdToOpenForDrawer] = useState<string | null>(null);
  const [memoryDrawerOpen, setMemoryDrawerOpen] = useState(false);
  const [settingsDrawerOpen, setSettingsDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // A2.1: 加载对话列表
  useEffect(() => {
    const loadConversations = async () => {
      setConversationsLoading(true);
      setConversationsError(null);
      try {
        const response = await listConversations();
        setConversations(response.items);
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "加载对话列表失败";
        setConversationsError(errorMessage);
        console.error("Failed to load conversations:", error);
      } finally {
        setConversationsLoading(false);
      }
    };
    loadConversations();
  }, []);

  // A3.1: 根据 URL 中的 conversationId 加载消息
  useEffect(() => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    
    if (!currentConvId) {
      setMessages([]);
      setMessagesError(null);
      return;
    }

    const loadMessages = async () => {
      setMessagesLoading(true);
      setMessagesError(null);
      try {
        const response = await listMessages(currentConvId);
        // 确保消息按 created_at 升序排列（后端已保证，这里做双重保险）
        const sortedMessages = [...response.items].sort((a, b) => 
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
        setMessages(sortedMessages);
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "加载消息失败";
        setMessagesError(errorMessage);
        console.error("Failed to load messages:", error);
        setMessages([]);
      } finally {
        setMessagesLoading(false);
      }
    };
    loadMessages();
  }, [conversationId, location.pathname]);

  // 加载 runs
  useEffect(() => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    
    if (!currentConvId) {
      setRuns([]);
      setRunsError(null);
      return;
    }

    const loadRuns = async () => {
      setRunsLoading(true);
      setRunsError(null);
      try {
        const runsList = await listConversationRuns(currentConvId);
        setRuns(runsList);
        previousRunsRef.current = runsList; // 初始化 previousRunsRef
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : "加载任务失败";
        setRunsError(errorMessage);
        console.error("Failed to load runs:", error);
        setRuns([]);
        previousRunsRef.current = []; // 重置 previousRunsRef
      } finally {
        setRunsLoading(false);
      }
    };
    loadRuns();
  }, [conversationId, location.pathname]);

  // 兜底：消息列表末尾已是 assistant 时关闭“发送中”loading，避免三个点残留（含 2s 刷新后的更新）
  useEffect(() => {
    if (!loading) return;
    if (messages.length > 0 && messages[messages.length - 1].role === "assistant") {
      setLoading(false);
    }
  }, [loading, messages]);

  // 当前展示的对话 id（用于轮询/延迟刷新时只更新“当前对话”的消息，避免切对话后旧请求覆盖）
  const currentConvIdRef = useRef<string | null>(null);
  /** 本轮发送的 client_turn_id；用于丢弃迟到/错轮的响应，避免“上一轮超时”插进下一轮 */
  const pendingTurnIdRef = useRef<string | null>(null);
  // 轮询 runs（持续轮询，有活跃任务时 2 秒一次，无活跃任务时 5 秒一次，不停止）
  const pollingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const previousRunsRef = useRef<Run[]>([]); // 保存上一次的 runs 状态，用于检测状态变化
  const postSendRefreshTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  
  // 启动或重启轮询的函数
  const startPolling = useCallback((convId: string) => {
    // 如果已经有轮询在运行，先清理
    if (pollingTimeoutRef.current) {
      clearTimeout(pollingTimeoutRef.current);
      pollingTimeoutRef.current = null;
    }

    const scheduleNext = (delayMs: number) => {
      pollingTimeoutRef.current = setTimeout(() => {
        pollingTimeoutRef.current = null;
        pollRuns();
      }, delayMs);
    };

    // 轮询函数
    const pollRuns = async () => {
      try {
        const currentRuns = await listConversationRuns(convId);
        // 若用户已切换到其他对话，不要用旧对话的数据覆盖当前对话
        if (currentConvIdRef.current !== convId) return;
        
        // 检查是否有 run 状态从非终态变为终态，或出现“新 run 已是终态”（快速完成/失败），需要刷新消息
        const previousRuns = previousRunsRef.current;
        const previousRunStatuses = new Map(previousRuns.map(r => [r.id, r.status]));
        const finalStatuses = new Set(["succeeded", "failed", "canceled"]);
        
        let shouldRefreshMessages = false;
        for (const run of currentRuns) {
          const previousStatus = previousRunStatuses.get(run.id);
          // 状态从非终态变为终态 → 刷新消息
          if (previousStatus && !finalStatuses.has(previousStatus) && finalStatuses.has(run.status)) {
            shouldRefreshMessages = true;
            break;
          }
          // 新出现的 run 且已是终态（快速完成或快速失败）→ 也刷新消息，保证对话框里能看到完成/失败提示
          if (previousStatus === undefined && finalStatuses.has(run.status)) {
            shouldRefreshMessages = true;
            break;
          }
        }
        
        // 更新 runs 状态和 ref（仅当前对话）
        setRuns(currentRuns);
        previousRunsRef.current = currentRuns;
        
        // 如果有 run 完成，立即刷新消息列表；再延迟刷新一次以拉取 worker 异步写入的完成消息（避免竞态）
        if (shouldRefreshMessages && currentConvIdRef.current === convId) {
          const refreshMessages = async () => {
            try {
              const response = await listMessages(convId);
              if (currentConvIdRef.current !== convId) return;
              const sortedMessages = [...response.items].sort((a, b) =>
                new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
              );
              setMessages(sortedMessages);
            } catch (error) {
              console.error("Failed to refresh messages after run completion:", error);
            }
          };
          await refreshMessages();
          setTimeout(() => {
            if (currentConvIdRef.current === convId) void refreshMessages();
          }, 1800);
        }

        const hasActive = currentRuns.some(r => r.status === "queued" || r.status === "running");
        // 有活跃任务时 2 秒轮询，无活跃任务时 5 秒轮询，不停止（这样发新消息后新 run 也能被轮询到并刷新完成消息）
        scheduleNext(hasActive ? 2000 : 5000);
      } catch (error) {
        console.error("Failed to poll runs:", error);
        // 轮询失败时 5 秒后重试
        scheduleNext(5000);
      }
    };

    // 立即执行一次
    pollRuns();
  }, []);

  useEffect(() => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    currentConvIdRef.current = currentConvId;
    
    if (!currentConvId) {
      if (pollingTimeoutRef.current) {
        clearTimeout(pollingTimeoutRef.current);
        pollingTimeoutRef.current = null;
      }
      if (postSendRefreshTimeoutRef.current) {
        clearTimeout(postSendRefreshTimeoutRef.current);
        postSendRefreshTimeoutRef.current = null;
      }
      return;
    }

    startPolling(currentConvId);

    return () => {
      if (pollingTimeoutRef.current) {
        clearTimeout(pollingTimeoutRef.current);
        pollingTimeoutRef.current = null;
      }
      if (postSendRefreshTimeoutRef.current) {
        clearTimeout(postSendRefreshTimeoutRef.current);
        postSendRefreshTimeoutRef.current = null;
      }
    };
  }, [conversationId, location.pathname, startPolling]);

  const handleNewConversation = useCallback(async () => {
    try {
      const newConversation = await createConversation("新对话");
      // 重新加载对话列表以确保顺序正确
      const response = await listConversations();
      setConversations(response.items);
      // 导航到新对话
      navigate(`/chat/${newConversation.id}`);
      setMessages([]);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "创建对话失败";
      console.error("Failed to create conversation:", error);
      alert(errorMessage);
    }
  }, [navigate]);

  const handleSelectConversation = useCallback(async (id: string) => {
    // URL 驱动：导航到对应路由，消息加载由 useEffect 处理
    navigate(`/chat/${id}`);
    
    // 标记对话为已读
    try {
      const updatedConversation = await markConversationRead(id);
      // 更新 conversations 列表以反映 has_unread 变化
      setConversations((prev) =>
        prev.map((conv) => (conv.id === id ? updatedConversation : conv))
      );
    } catch (error) {
      // 静默失败，不影响导航
      console.error("Failed to mark conversation as read:", error);
    }
  }, [navigate]);

  const handleDeleteConversation = useCallback(async (id: string) => {
    try {
      // 调用后端 API 删除对话
      await deleteConversation(id);
      // 从前端列表中移除
      setConversations((prev) => prev.filter((conv) => conv.id !== id));
      if (conversationId === id) {
        // 如果删除的是当前对话，导航到首页
        navigate("/");
        setMessages([]);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "删除对话失败";
      console.error("Failed to delete conversation:", error);
      alert(errorMessage);
    }
  }, [conversationId, navigate]);

  const handleSendMessage = useCallback(
    async (content: string, retryMessageId?: string) => {
      // 从当前 location 中获取 conversationId
      const currentPathMatch = location.pathname.match(/\/chat\/([^/]+)/);
      const currentConversationId = conversationId || (currentPathMatch ? currentPathMatch[1] : null);
      let targetConversationId = currentConversationId;
      
      if (!targetConversationId) {
        // 如果没有当前对话，创建一个新对话
        try {
          const newConversation = await createConversation("新对话");
          // 添加到对话列表（不重新加载，避免重复请求）
          setConversations((prev) => [newConversation, ...prev]);
          // 导航到新对话
          navigate(`/chat/${newConversation.id}`, { replace: true });
          setMessages([]);
          targetConversationId = newConversation.id;
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : "创建对话失败";
          console.error("Failed to create conversation:", error);
          alert(errorMessage);
          return;
        }
      }

      const tempId = retryMessageId || `temp-${Date.now()}`;
      const now = new Date().toISOString();

      // A3.2: 乐观更新 - 先插入临时 user 消息
      const tempUserMessage: Message = {
        id: tempId,
        conversation_id: targetConversationId!,
        role: "user",
        content,
        created_at: now,
        meta_json: retryMessageId ? undefined : { optimistic: true },
      };

      // 如果是重试，移除失败标记；否则添加临时消息
      if (retryMessageId) {
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === retryMessageId
              ? {
                  ...msg,
                  meta_json: {
                    ...(msg.meta_json || {}),
                    failed: false,
                    error: undefined,
                  },
                }
              : msg
          )
        );
      } else {
        setMessages((prev) => [...prev, tempUserMessage]);
      }

      setLoading(true);
      const turnId = crypto.randomUUID();
      pendingTurnIdRef.current = turnId;

      try {
        // A3.2: 调用真实的 sendMessage API（带 client_turn_id 做轮次隔离）
        const response = await sendMessage(targetConversationId!, content, { client_turn_id: turnId });

        // 轮次隔离：若响应对应的不是当前 pending 轮次，丢弃，避免“上一轮超时”插进下一轮
        const responseTurnId =
          response.assistant_message?.meta_json && typeof response.assistant_message.meta_json === "object"
            ? (response.assistant_message.meta_json as Record<string, unknown>).client_turn_id as string | undefined
            : undefined;
        if (pendingTurnIdRef.current != null && responseTurnId !== undefined && responseTurnId !== pendingTurnIdRef.current) {
          setLoading(false);
          return;
        }

        // 检查更新前的消息数量（排除临时消息），用于判断是否需要更新标题
        const previousMessageCount = messages.filter((msg) => msg.id !== tempId && !msg.meta_json?.optimistic).length;

        // 移除临时消息，添加服务端返回的真实消息
        setMessages((prev) => {
          const filtered = prev.filter((msg) => msg.id !== tempId);
          const newMessages: Message[] = [];

          // 添加 user_message（如果存在）
          if (response.user_message) {
            // 检查是否已存在（通过 ID 匹配）
            const existingUserIndex = filtered.findIndex((msg) => msg.id === response.user_message!.id);
            if (existingUserIndex >= 0) {
              filtered[existingUserIndex] = response.user_message;
            } else {
              newMessages.push(response.user_message);
            }
          }

          // 添加 assistant_message（如果存在）
          if (response.assistant_message) {
            // 检查是否已存在（通过 ID 匹配）
            const existingAssistantIndex = filtered.findIndex(
              (msg) => msg.id === response.assistant_message!.id
            );
            if (existingAssistantIndex >= 0) {
              filtered[existingAssistantIndex] = response.assistant_message;
            } else {
              newMessages.push(response.assistant_message);
            }
          }

          // 按 created_at 排序
          const allMessages = [...filtered, ...newMessages].sort(
            (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
          );

          return allMessages;
        });

        // 收到响应并合并消息后立即关闭 loading，避免“三个点”打字指示器残留
        setLoading(false);

        // 立即刷新任务列表（Agent Decision 可能创建了新的 run），并确保轮询在跑
        if (targetConversationId) {
          if (!pollingTimeoutRef.current) {
            startPolling(targetConversationId);
          } else {
            try {
              const currentRuns = await listConversationRuns(targetConversationId);
              setRuns(currentRuns);
              previousRunsRef.current = currentRuns;
            } catch (error) {
              console.error("Failed to refresh runs after sending message:", error);
            }
          }
          // 发消息后约 2 秒再拉一次消息，仅当仍在该对话时更新，避免切对话后覆盖
          if (postSendRefreshTimeoutRef.current) {
            clearTimeout(postSendRefreshTimeoutRef.current);
          }
          postSendRefreshTimeoutRef.current = setTimeout(async () => {
            postSendRefreshTimeoutRef.current = null;
            if (currentConvIdRef.current !== targetConversationId) return;
            try {
              const response = await listMessages(targetConversationId);
              if (currentConvIdRef.current !== targetConversationId) return;
              const sorted = [...response.items].sort((a, b) =>
                new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
              );
              setMessages(sorted);
            } catch {
              // 忽略单次刷新失败
            }
          }, 2000);
        }

        // A3.4: 更新会话标题（第一条消息后）- 在 setMessages 外部处理异步操作
        if (previousMessageCount === 0 && response.user_message) {
          const title = content.slice(0, 20);
          // 调用后端 API 更新标题
          try {
            const updatedConversation = await updateConversation(targetConversationId!, title);
            setConversations((convPrev) =>
              convPrev.map((conv) =>
                conv.id === targetConversationId ? updatedConversation : conv
              )
            );
          } catch (error) {
            console.error("Failed to update conversation title:", error);
            // 如果更新失败，至少更新前端显示
            setConversations((convPrev) =>
              convPrev.map((conv) =>
                conv.id === targetConversationId
                  ? { ...conv, title, updated_at: response.user_message?.created_at || now }
                  : conv
              )
            );
          }
        } else if (response.assistant_message) {
          // 更新会话的 updated_at
          setConversations((convPrev) =>
            convPrev.map((conv) =>
              conv.id === targetConversationId
                ? { ...conv, updated_at: response.assistant_message!.created_at }
                : conv
            )
          );
        }
      } catch (error) {
        // A3.3: 错误处理 - 标记失败消息
        const errorMessage = error instanceof Error ? error.message : "发送消息失败";
        console.error("Failed to send message:", error);

        // 如果消息不存在（可能已经被清理），创建一个失败消息
        setMessages((prev) => {
          const existingIndex = prev.findIndex((msg) => msg.id === tempId);
          if (existingIndex >= 0) {
            // 更新现有消息为失败状态
            return prev.map((msg) =>
              msg.id === tempId
                ? {
                    ...msg,
                    meta_json: {
                      ...(msg.meta_json || {}),
                      failed: true,
                      error: errorMessage,
                      retryable: true,
                    },
                  }
                : msg
            );
          } else {
            // 如果消息不存在，创建一个失败消息（这种情况不应该发生，但作为保险）
            const failedMessage: Message = {
              id: tempId,
              conversation_id: targetConversationId!,
              role: "user",
              content,
              created_at: now,
              meta_json: {
                failed: true,
                error: errorMessage,
                retryable: true,
              },
            };
            return [...prev, failedMessage];
          }
        });
      } finally {
        setLoading(false);
      }
    },
    [conversationId, navigate, location]
  );

  const handleCreateRun = useCallback(async () => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    
    if (!currentConvId) {
      alert("请先选择一个对话");
      return;
    }

    try {
      const newRun = await createRun({
        type: "sleep",
        title: "Sleep 5s",
        conversation_id: currentConvId,
        input: { seconds: 5 },
      });
      // 乐观更新：将新 run 插入列表顶部
      setRuns((prev) => [newRun, ...prev]);
      
      // 如果有新任务创建，确保轮询正在运行
      if (!pollingTimeoutRef.current) {
        startPolling(currentConvId);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "创建任务失败";
      console.error("Failed to create run:", error);
      alert(errorMessage);
    }
  }, [conversationId, location.pathname, startPolling]);

  const handleDeleteRun = useCallback(async (runId: string) => {
    try {
      await deleteRun(runId);
      // 从列表中移除
      setRuns((prev) => prev.filter((run) => run.id !== runId));
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "删除任务失败";
      console.error("Failed to delete run:", error);
      alert(errorMessage);
    }
  }, []);

  const handleRetryRun = useCallback(async (run: Run) => {
    try {
      const newRun = await retryRun(run);
      // 将新 run 插入列表顶部
      setRuns((prev) => [newRun, ...prev]);
      
      // 如果有新任务创建，确保轮询正在运行
      const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
      const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
      if (currentConvId && !pollingTimeoutRef.current) {
        startPolling(currentConvId);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "重试任务失败";
      console.error("Failed to retry run:", error);
      alert(errorMessage);
    }
  }, [conversationId, location.pathname, startPolling]);

  const handleCancelEditDocs = useCallback(async (run: Run) => {
    const output = run.output as Record<string, unknown> | undefined;
    const artifacts = (output?.artifacts as Record<string, unknown> | undefined) ?? {};
    const patchId = (artifacts.patch_id as string) ?? (artifacts.patch_id_short as string);
    if (!patchId) return;
    try {
      await createRun({
        type: "edit_docs_cancel",
        title: "Cancel patch",
        conversation_id: run.conversation_id ?? undefined,
        input: { parent_run_id: run.id, patch_id: patchId },
        parent_run_id: run.id,
      });
      const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
      const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
      if (currentConvId) {
        const list = await listConversationRuns(currentConvId);
        setRuns(list);
      }
    } catch {
      // optional: ignore
    }
  }, [conversationId, location.pathname]);

  const handleApplyEditDocs = useCallback(async (run: Run) => {
    const output = run.output as Record<string, unknown> | undefined;
    const artifacts = (output?.artifacts as Record<string, unknown> | undefined) ?? {};
    const patchId = artifacts.patch_id as string | undefined;
    if (!patchId) {
      console.error("Apply edit: patch_id missing in run output");
      return;
    }
    try {
      const newRun = await createRun({
        type: "edit_docs_apply",
        title: "Apply patch",
        conversation_id: run.conversation_id ?? undefined,
        input: { parent_run_id: run.id, patch_id: patchId },
        parent_run_id: run.id,
      });
      setRuns((prev) => [newRun, ...prev]);
      const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
      const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
      if (currentConvId && !pollingTimeoutRef.current) {
        startPolling(currentConvId);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "创建 Apply 任务失败";
      console.error("Failed to create edit_docs_apply run:", error);
      alert(errorMessage);
    }
  }, [conversationId, location.pathname, startPolling]);

  const handleCancelRun = useCallback(async (runId: string) => {
    // 乐观更新：立即更新本地 state
    const originalRuns = [...runs];
    setRuns((prev) =>
      prev.map((run) =>
        run.id === runId
          ? {
              ...run,
              status: "canceled" as const,
              canceled_at: new Date().toISOString(),
              canceled_by: "user",
            }
          : run
      )
    );

    try {
      const updatedRun = await cancelRun(runId);
      // 更新为服务器返回的实际状态
      setRuns((prev) =>
        prev.map((run) => (run.id === runId ? updatedRun : run))
      );
    } catch (error) {
      // 回滚状态
      setRuns(originalRuns);
      const errorMessage = error instanceof Error ? error.message : "取消任务失败";
      console.error("Failed to cancel run:", error);
      alert(errorMessage);
    }
  }, [runs]);

  const handleRetryRuns = useCallback(async () => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    
    if (!currentConvId) {
      return;
    }

    setRunsLoading(true);
    setRunsError(null);
    try {
      const runsList = await listConversationRuns(currentConvId);
      setRuns(runsList);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "加载任务失败";
      setRunsError(errorMessage);
      console.error("Failed to load runs:", error);
    } finally {
      setRunsLoading(false);
    }
  }, [conversationId, location.pathname]);

  return (
    <>
      <Layout
        sidebar={
          <Sidebar
            conversations={conversations}
            currentConversationId={conversationId || null}
            onNewConversation={handleNewConversation}
            onSelectConversation={handleSelectConversation}
            onDeleteConversation={handleDeleteConversation}
            loading={conversationsLoading}
            error={conversationsError}
          />
        }
        mainContent={
          <div className="main-content-wrapper">
            <Routes>
              <Route
                path="/chat/:conversationId"
                element={
                  <ChatPage 
                    messages={messages} 
                    onSendMessage={handleSendMessage} 
                    loading={loading || messagesLoading}
                    runs={runs}
                    onOpenRunDetails={conversationId ? (runId) => setRunIdToOpenForDrawer(runId) : undefined}
                  />
                }
              />
              <Route
                path="/"
                element={
                  <ChatPage
                    messages={messages}
                    onSendMessage={handleSendMessage}
                    loading={loading}
                    runs={[]}
                  />
                }
              />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/executions" element={<ExecutionsListPage />} />
              <Route path="/executions/:executionId" element={<ExecutionDetailPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        }
        tasksPanel={
          conversationId ? (
            <RunsPanel
              runs={runs}
              loading={runsLoading}
              error={runsError}
              onRetry={handleRetryRuns}
              onCreateRun={handleCreateRun}
              onDeleteRun={handleDeleteRun}
              onRetryRun={handleRetryRun}
              onCancelRun={handleCancelRun}
              onApplyEditDocs={handleApplyEditDocs}
              onCancelEditDocs={handleCancelEditDocs}
              runIdToOpen={runIdToOpenForDrawer}
              onDrawerClose={() => setRunIdToOpenForDrawer(null)}
            />
          ) : undefined
        }
        onMemoryClick={() => setMemoryDrawerOpen(true)}
        onSettingsClick={() => setSettingsDrawerOpen(true)}
      />
      <SettingsPanel isOpen={memoryDrawerOpen} onClose={() => setMemoryDrawerOpen(false)} />
      <SettingsDrawer isOpen={settingsDrawerOpen} onClose={() => setSettingsDrawerOpen(false)} />
    </>
  );
};

export default App;
