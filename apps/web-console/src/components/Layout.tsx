import { ReactNode, useState } from "react";
import "./Layout.css";

type LayoutProps = {
  sidebar: ReactNode;
  mainContent: ReactNode;
  tasksPanel?: ReactNode; // 右侧固定 Tasks Panel（可选）
  onMemoryClick: () => void;
  onSettingsClick: () => void;
};

export const Layout = ({ sidebar, mainContent, tasksPanel, onMemoryClick, onSettingsClick }: LayoutProps) => {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  return (
    <div className="layout">
      {/* 侧边栏 - 固定左侧 */}
      <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
        <div className="sidebar-header">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label="切换侧边栏"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M3 5h14M3 10h14M3 15h14"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          {sidebarOpen && <h2 className="sidebar-title">LonelyCat</h2>}
        </div>
        {sidebar}
      </aside>

      {/* 主内容区 - 中间弹性区域 */}
      <main className="main-content">
        {/* 顶部栏 */}
        <header className="top-bar">
          {/* 当 sidebar 关闭时显示此按钮 */}
          {!sidebarOpen && (
            <button
              className="sidebar-show-btn"
              onClick={() => setSidebarOpen(true)}
              aria-label="显示侧边栏"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path
                  d="M3 5h14M3 10h14M3 15h14"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          )}
          {/* 移动端菜单按钮（仅在移动端显示，通过 CSS media query 控制） */}
          <button
            className="mobile-menu-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label="打开菜单"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M3 5h14M3 10h14M3 15h14"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <div className="top-bar-spacer"></div>
          <button
            className="top-bar-icon-btn memory-btn"
            onClick={onMemoryClick}
            aria-label="Memory 管理"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M10 4a4 4 0 014 4v2a4 4 0 01-8 0V8a4 4 0 014-4z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M5 10h10M7 14h6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <button
            className="top-bar-icon-btn settings-btn"
            onClick={onSettingsClick}
            aria-label="设置"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M10 12a2 2 0 100-4 2 2 0 000 4z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M16.5 10a1.5 1.5 0 01.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-1.12.6 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 0116.5 10zm-13 0a1.5 1.5 0 01-.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-.6 1.12 1.5 1.5 0 01-.72.15 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 013.5 10zm13-6.5a1.5 1.5 0 01.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-1.12.6 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 0116.5 3.5zm-13 0a1.5 1.5 0 01-.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-.6 1.12 1.5 1.5 0 01-.72.15 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 013.5 3.5zm13 13a1.5 1.5 0 01.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-1.12.6 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 0116.5 16.5zm-13 0a1.5 1.5 0 01-.3 1.65l-.04.08a1.8 1.8 0 01-.15.27 1.5 1.5 0 01-.6 1.12 1.5 1.5 0 01-.72.15 1.5 1.5 0 01-.72-.15l-.12-.07a1.5 1.5 0 01-.42-.42l-.07-.12a1.5 1.5 0 01-.15-.72 1.5 1.5 0 01.6-1.12 1.8 1.8 0 01.27-.15l.08-.04A1.5 1.5 0 013.5 16.5z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </header>
        {mainContent}
      </main>

      {/* Tasks Panel - 固定右侧 */}
      {tasksPanel && <aside className="tasks-panel">{tasksPanel}</aside>}
    </div>
  );
};
