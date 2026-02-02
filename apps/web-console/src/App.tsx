import { useState, useCallback, useEffect } from "react";
import { Routes, Route, Navigate, useParams, useNavigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { ChatPage } from "./components/ChatPage";
import { SettingsPanel } from "./components/SettingsPanel";
import { MemoryPage } from "./pages/MemoryPage";
import { listConversations, createConversation, listMessages } from "./api/conversations";
import type { Conversation, Message } from "./api/conversations";
import "./App.css";

const App = () => {
  const navigate = useNavigate();
  const { conversationId } = useParams<{ conversationId?: string }>();
  
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationsLoading, setConversationsLoading] = useState(false);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
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

  // A2.3: 根据 URL 中的 conversationId 加载消息
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }

    const loadMessages = async () => {
      setMessagesLoading(true);
      try {
        const response = await listMessages(conversationId);
        setMessages(response.items);
      } catch (error) {
        console.error("Failed to load messages:", error);
        setMessages([]);
      } finally {
        setMessagesLoading(false);
      }
    };
    loadMessages();
  }, [conversationId]);

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

  const handleDeleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((conv) => conv.id !== id));
    if (conversationId === id) {
      // 如果删除的是当前对话，导航到首页
      navigate("/");
      setMessages([]);
    }
  }, [conversationId, navigate]);

  const handleSendMessage = useCallback(
    async (content: string) => {
      if (!conversationId) {
        // 如果没有当前对话，创建一个新对话
        await handleNewConversation();
        // 等待导航完成
        return;
      }

      setLoading(true);

      try {
        // TODO: 调用 sendMessage API
        // 这里暂时模拟响应，后续会替换为实际的 API 调用
        await new Promise((resolve) => setTimeout(resolve, 1000));

        const now = new Date().toISOString();
        const userMessage: Message = {
          id: `msg-${Date.now()}-user`,
          conversation_id: conversationId!,
          role: "user",
          content,
          created_at: now,
        };

        const assistantMessage: Message = {
          id: `msg-${Date.now()}-assistant`,
          conversation_id: conversationId!,
          role: "assistant",
          content: `这是对 "${content}" 的回复。实际功能需要连接后端API。`,
          created_at: now,
        };

        setMessages((prev) => [...prev, userMessage, assistantMessage]);

        // 更新对话标题（使用第一条用户消息）
        if (messages.length === 0) {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === conversationId
                ? { ...conv, title: content.slice(0, 30), updated_at: now }
                : conv
            )
          );
        } else {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === conversationId ? { ...conv, updated_at: now } : conv
            )
          );
        }
      } catch (error) {
        console.error("Failed to send message:", error);
        const now = new Date().toISOString();
        const errorMessage: Message = {
          id: `msg-${Date.now()}-error`,
          conversation_id: conversationId!,
          role: "assistant",
          content: "抱歉，发送消息时出现错误。",
          created_at: now,
        };
        setMessages((prev) => [...prev, errorMessage]);
      } finally {
        setLoading(false);
      }
    },
    [conversationId, messages.length, handleNewConversation]
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
