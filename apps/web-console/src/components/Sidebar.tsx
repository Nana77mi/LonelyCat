import { useState } from "react";
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

  return (
    <div className="sidebar-content">
      {/* 新对话按钮 */}
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

      {/* 对话列表 */}
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
    </div>
  );
};
