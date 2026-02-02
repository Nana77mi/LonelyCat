import { useState } from "react";
import "./Sidebar.css";

export type Conversation = {
  id: string;
  title: string;
  updatedAt: number;
};

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
                  {formatTime(conv.updatedAt)}
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
