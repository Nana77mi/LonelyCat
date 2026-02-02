import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { Conversation } from "../api/conversations";
import "./Sidebar.css";

export type { Conversation };

type SidebarProps = {
  conversations: Conversation[];
  currentConversationId: string | null;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation?: (id: string) => void;
};

export const Sidebar = ({
  conversations,
  currentConversationId,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
}: SidebarProps) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const location = useLocation();
  const isMemoryPage = location.pathname === "/memory";

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

      {/* Memory 导航入口 */}
      <Link
        to="/memory"
        className={`memory-nav-btn ${isMemoryPage ? "active" : ""}`}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path
            d="M8 2C4.69 2 2 4.69 2 8C2 11.31 4.69 14 8 14C11.31 14 14 11.31 14 8C14 4.69 11.31 2 8 2ZM8 12C5.79 12 4 10.21 4 8C4 5.79 5.79 4 8 4C10.21 4 12 5.79 12 8C12 10.21 10.21 12 8 12Z"
            fill="currentColor"
          />
          <path
            d="M8 5.5C7.59 5.5 7.25 5.84 7.25 6.25V8.25C7.25 8.66 7.59 9 8 9C8.41 9 8.75 8.66 8.75 8.25V6.25C8.75 5.84 8.41 5.5 8 5.5Z"
            fill="currentColor"
          />
          <path
            d="M8 10.5C7.59 10.5 7.25 10.84 7.25 11.25C7.25 11.66 7.59 12 8 12C8.41 12 8.75 11.66 8.75 11.25C8.75 10.84 8.41 10.5 8 10.5Z"
            fill="currentColor"
          />
        </svg>
        <span>Memory</span>
      </Link>

      {/* 对话列表 */}
      <div className="conversations-list">
        {conversations.length === 0 ? (
          <div className="empty-state">
            <p>还没有对话记录</p>
            <p className="empty-hint">开始一个新对话吧</p>
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                currentConversationId === conv.id ? "active" : ""
              }`}
              onClick={() => onSelectConversation(conv.id)}
              onMouseEnter={() => setHoveredId(conv.id)}
              onMouseLeave={() => setHoveredId(null)}
            >
              <div className="conversation-content">
                <span className="conversation-title">{conv.title}</span>
                <span className="conversation-time">
                  {formatTime(new Date(conv.updated_at).getTime())}
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
          ))
        )}
      </div>
    </div>
  );
};

function formatTime(timestamp: number): string {
  const now = Date.now();
  const diff = now - timestamp;
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  if (days < 7) return `${days}天前`;

  const date = new Date(timestamp);
  return date.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
}
