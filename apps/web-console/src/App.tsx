import { useState, useCallback } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar } from "./components/Sidebar";
import { ChatPage } from "./components/ChatPage";
import { SettingsPanel } from "./components/SettingsPanel";
import { MemoryPage } from "./pages/MemoryPage";
import type { Conversation, Message } from "./api/conversations";
import "./App.css";

const App = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleNewConversation = useCallback(() => {
    // TODO: 调用 createConversation API
    // 这里暂时使用本地生成的 ID，后续会替换为 API 调用
    const newId = `conv-${Date.now()}`;
    const now = new Date().toISOString();
    const newConversation: Conversation = {
      id: newId,
      title: "新对话",
      created_at: now,
      updated_at: now,
    };
    setConversations((prev) => [newConversation, ...prev]);
    setCurrentConversationId(newId);
    setMessages([]);
  }, []);

  const handleSelectConversation = useCallback((id: string) => {
    setCurrentConversationId(id);
    // TODO: 从存储中加载对话消息
    // 这里暂时使用空消息列表
    setMessages([]);
  }, []);

  const handleDeleteConversation = useCallback((id: string) => {
    setConversations((prev) => prev.filter((conv) => conv.id !== id));
    if (currentConversationId === id) {
      setCurrentConversationId(null);
      setMessages([]);
    }
  }, [currentConversationId]);

  const handleSendMessage = useCallback(
    async (content: string) => {
      if (!currentConversationId) {
        // 如果没有当前对话，创建一个新对话
        handleNewConversation();
        // 等待状态更新
        await new Promise((resolve) => setTimeout(resolve, 0));
      }

      setLoading(true);

      try {
        // TODO: 调用 sendMessage API
        // 这里暂时模拟响应，后续会替换为实际的 API 调用
        await new Promise((resolve) => setTimeout(resolve, 1000));

        const now = new Date().toISOString();
        const userMessage: Message = {
          id: `msg-${Date.now()}-user`,
          conversation_id: currentConversationId!,
          role: "user",
          content,
          created_at: now,
        };

        const assistantMessage: Message = {
          id: `msg-${Date.now()}-assistant`,
          conversation_id: currentConversationId!,
          role: "assistant",
          content: `这是对 "${content}" 的回复。实际功能需要连接后端API。`,
          created_at: now,
        };

        setMessages((prev) => [...prev, userMessage, assistantMessage]);

        // 更新对话标题（使用第一条用户消息）
        if (messages.length === 0) {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === currentConversationId
                ? { ...conv, title: content.slice(0, 30), updated_at: now }
                : conv
            )
          );
        } else {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === currentConversationId ? { ...conv, updated_at: now } : conv
            )
          );
        }
      } catch (error) {
        console.error("Failed to send message:", error);
        const now = new Date().toISOString();
        const errorMessage: Message = {
          id: `msg-${Date.now()}-error`,
          conversation_id: currentConversationId!,
          role: "assistant",
          content: "抱歉，发送消息时出现错误。",
          created_at: now,
        };
        setMessages((prev) => [...prev, errorMessage]);
      } finally {
        setLoading(false);
      }
    },
    [currentConversationId, messages.length, handleNewConversation]
  );

  return (
    <>
      <Layout
        sidebar={
          <Sidebar
            conversations={conversations}
            currentConversationId={currentConversationId}
            onNewConversation={handleNewConversation}
            onSelectConversation={handleSelectConversation}
            onDeleteConversation={handleDeleteConversation}
          />
        }
        mainContent={
          <div className="main-content-wrapper">
            <Routes>
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
