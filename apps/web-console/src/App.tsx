import { useState, useCallback, useEffect, useRef } from "react";
import { Routes, Route, Navigate, useParams, useNavigate, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { ChatPage } from "./components/ChatPage";
import { RunsPanel } from "./components/RunsPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { MemoryPage } from "./pages/MemoryPage";
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
  const [settingsOpen, setSettingsOpen] = useState(false);
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

  // 轮询 runs（持续轮询，自动检测活跃任务）
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const previousRunsRef = useRef<Run[]>([]); // 保存上一次的 runs 状态，用于检测状态变化
  
  // 启动或重启轮询的函数
  const startPolling = useCallback((convId: string) => {
    // 如果已经有轮询在运行，先清理
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }

    // 轮询函数
    const pollRuns = async () => {
      try {
        const currentRuns = await listConversationRuns(convId);
        
        // 检查是否有 run 状态从非终态变为终态（可能产生了新消息）
        const previousRuns = previousRunsRef.current;
        const previousRunStatuses = new Map(previousRuns.map(r => [r.id, r.status]));
        const finalStatuses = new Set(["succeeded", "failed", "canceled"]);
        
        let shouldRefreshMessages = false;
        for (const run of currentRuns) {
          const previousStatus = previousRunStatuses.get(run.id);
          // 如果 run 状态从非终态变为终态，需要刷新消息
          if (previousStatus && !finalStatuses.has(previousStatus) && finalStatuses.has(run.status)) {
            shouldRefreshMessages = true;
            break;
          }
        }
        
        // 更新 runs 状态和 ref
        setRuns(currentRuns);
        previousRunsRef.current = currentRuns;
        
        // 如果有 run 完成，立即刷新消息列表（获取 run 完成后的主动消息）
        if (shouldRefreshMessages) {
          try {
            const response = await listMessages(convId);
            const sortedMessages = [...response.items].sort((a, b) => 
              new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
            );
            setMessages(sortedMessages);
          } catch (error) {
            console.error("Failed to refresh messages after run completion:", error);
          }
        }
        
        const hasActive = currentRuns.some(r => r.status === "queued" || r.status === "running");
        
        // 如果没有活跃任务，停止轮询
        if (!hasActive) {
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
          }
          return;
        }
      } catch (error) {
        console.error("Failed to poll runs:", error);
        // 轮询失败时不停止，继续尝试
      }
    };

    // 立即执行一次
    pollRuns();

    // 设置轮询（每 2 秒）
    pollingIntervalRef.current = setInterval(pollRuns, 2000);
  }, []);

  useEffect(() => {
    const pathMatch = location.pathname.match(/\/chat\/([^/]+)/);
    const currentConvId = conversationId || (pathMatch ? pathMatch[1] : null);
    
    if (!currentConvId) {
      // 清理之前的轮询
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      return;
    }

    // 启动轮询
    startPolling(currentConvId);

    // 清理函数
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
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

      try {
        // A3.2: 调用真实的 sendMessage API
        const response = await sendMessage(targetConversationId!, content);

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

        // 立即刷新任务列表（Agent Decision 可能创建了新的 run）
        // 确保轮询正在运行，并立即执行一次
        if (targetConversationId) {
          if (!pollingIntervalRef.current) {
            startPolling(targetConversationId);
          } else {
            // 如果轮询已在运行，立即执行一次
            try {
              const currentRuns = await listConversationRuns(targetConversationId);
              setRuns(currentRuns);
            } catch (error) {
              console.error("Failed to refresh runs after sending message:", error);
            }
          }
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
      if (!pollingIntervalRef.current) {
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
      if (currentConvId && !pollingIntervalRef.current) {
        startPolling(currentConvId);
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "重试任务失败";
      console.error("Failed to retry run:", error);
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
                  />
                }
              />
              <Route
                path="/"
                element={
                  <ChatPage messages={messages} onSendMessage={handleSendMessage} loading={loading} />
                }
              />
              <Route path="/memory" element={<MemoryPage />} />
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
            />
          ) : undefined
        }
        onSettingsClick={() => setSettingsOpen(true)}
      />
      <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
};

export default App;
