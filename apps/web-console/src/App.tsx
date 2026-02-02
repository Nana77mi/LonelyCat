import { useState, useCallback } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Sidebar, Conversation } from "./components/Sidebar";
import { ChatPage, Message } from "./components/ChatPage";
import { SettingsPanel } from "./components/SettingsPanel";
import { MemoryPage } from "./pages/MemoryPage";
import "./App.css";

const App = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleNewConversation = useCallback(() => {
    const newId = `conv-${Date.now()}`;
    const newConversation: Conversation = {
      id: newId,
      title: "新对话",
      updatedAt: Date.now(),
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

      const userMessage: Message = {
        id: `msg-${Date.now()}-user`,
        role: "user",
        content,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setLoading(true);

      try {
        // TODO: 调用实际的API发送消息
        // 这里模拟一个延迟响应
        await new Promise((resolve) => setTimeout(resolve, 1000));

        const assistantMessage: Message = {
          id: `msg-${Date.now()}-assistant`,
          role: "assistant",
          content: `这是对 "${content}" 的回复。实际功能需要连接后端API。`,
          timestamp: Date.now(),
        };

        setMessages((prev) => [...prev, assistantMessage]);

        // 更新对话标题（使用第一条用户消息）
        if (messages.length === 0) {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === currentConversationId
                ? { ...conv, title: content.slice(0, 30), updatedAt: Date.now() }
                : conv
            )
          );
        } else {
          setConversations((prev) =>
            prev.map((conv) =>
              conv.id === currentConversationId ? { ...conv, updatedAt: Date.now() } : conv
            )
          );
        }
      } catch (error) {
        console.error("Failed to send message:", error);
        const errorMessage: Message = {
          id: `msg-${Date.now()}-error`,
          role: "assistant",
          content: "抱歉，发送消息时出现错误。",
          timestamp: Date.now(),
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
