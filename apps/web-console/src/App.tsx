import { useState, useCallback, useEffect } from "react";
import { Routes, Route, Navigate, useParams, useNavigate, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { ChatPage } from "./components/ChatPage";
import { SettingsPanel } from "./components/SettingsPanel";
import { MemoryPage } from "./pages/MemoryPage";
import { listConversations, createConversation, listMessages, sendMessage, deleteConversation, updateConversation } from "./api/conversations";
import type { Conversation, Message } from "./api/conversations";
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

  const handleSelectConversation = useCallback((id: string) => {
    // URL 驱动：导航到对应路由，消息加载由 useEffect 处理
    navigate(`/chat/${id}`);
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
                  <ChatPage messages={messages} onSendMessage={handleSendMessage} loading={loading || messagesLoading} />
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
        onSettingsClick={() => setSettingsOpen(true)}
      />
      <SettingsPanel isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
};

export default App;
