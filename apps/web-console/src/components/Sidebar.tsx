import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type { Conversation } from "../api/conversations";
import { formatTime } from "../utils/time";
import "./Sidebar.css";

export type { Conversation };

type SidebarProps = {
  conversations: Conversation[];
  currentConversationId: string | null;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
  loading?: boolean;
  error?: string | null;
};

export const Sidebar = ({
  conversations,
  currentConversationId,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
  loading = false,
  error = null,
}: SidebarProps) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();

  const isOnExecutions = location.pathname.startsWith('/executions');
  const isOnMemory = location.pathname.startsWith('/memory');
  const isOnChat = !isOnExecutions && !isOnMemory;

  return (
    <div className="sidebar-content">
      {/* Navigation Links */}
      <div style={{ marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid var(--border-color)' }}>
        <button
          className={`new-chat-btn ${isOnChat ? 'active' : ''}`}
          onClick={() => navigate('/')}
          style={{ marginBottom: '8px' }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M2 5.5C2 4.67157 2.67157 4 3.5 4H12.5C13.3284 4 14 4.67157 14 5.5V11.5C14 12.3284 13.3284 13 12.5 13H3.5C2.67157 13 2 12.3284 2 11.5V5.5Z"
              stroke="currentColor"
              strokeWidth="1.5"
            />
            <path
              d="M2 7H14"
              stroke="currentColor"
              strokeWidth="1.5"
            />
          </svg>
          <span>Chat</span>
        </button>
        <button
          className={`new-chat-btn ${isOnExecutions ? 'active' : ''}`}
          onClick={() => navigate('/executions')}
          style={{ marginBottom: '8px' }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 2V8L12 10"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span>Executions</span>
        </button>
        <button
          className={`new-chat-btn ${isOnMemory ? 'active' : ''}`}
          onClick={() => navigate('/memory')}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3a3 3 0 013 3v1.5a3 3 0 01-6 0V6a3 3 0 013-3z"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M4 7.5h8M5.5 10.5h5"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
          <span>Memory</span>
        </button>
      </div>

      {/* 新对话按钮 */}
      {isOnChat && (
        <button className="new-chat-btn" onClick={onNewConversation}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M8 3v10M3 8h10"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          <span>新对话</span>
        </button>
      )}

      {/* 对话列表 */}
      {isOnChat && (
        <div className="conversations-list">
          {loading ? (
            <div className="empty-state">
              <p>加载中...</p>
            </div>
          ) : error ? (
            <div className="empty-state">
              <p>加载失败</p>
              <p className="empty-hint">{error}</p>
            </div>
          ) : conversations.length === 0 ? (
            <div className="empty-state">
              <p>还没有对话记录</p>
              <p className="empty-hint">开始一个新对话吧</p>
            </div>
          ) : (
            conversations.map((conv) => {
              const isActive = currentConversationId === conv.id;
              const hasUnread = conv.has_unread === true && !isActive;
              const isSystemRun = conv.meta_json && typeof conv.meta_json === "object" && conv.meta_json.kind === "system_run";

              return (
                <div
                  key={conv.id}
                  className={`conversation-item ${isActive ? "active" : ""}`}
                  onClick={() => onSelectConversation(conv.id)}
                  onMouseEnter={() => setHoveredId(conv.id)}
                  onMouseLeave={() => setHoveredId(null)}
                >
                  {/* 系统对话图标 */}
                  {isSystemRun && (
                    <span className="conversation-icon" title="系统任务">
                      ⚙️
                    </span>
                  )}
                  <div className="conversation-content">
                    <div className="conversation-title-row">
                      <span className="conversation-title">{conv.title}</span>
                      {hasUnread && (
                        <span className="conversation-unread-badge" title="未读消息">
                          ●
                        </span>
                      )}
                    </div>
                    <span className="conversation-time">
                      {formatTime(conv.updated_at)}
                    </span>
                  </div>
                  {hoveredId === conv.id && onDeleteConversation && (
                    <button
                      className="delete-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteConversation(conv.id);
                      }}
                      aria-label="删除对话"
                    >
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path
                          d="M3.5 3.5l7 7M10.5 3.5l-7 7"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                        />
                      </svg>
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};
