import { useState } from "react";
import type { Run } from "../api/runs";
import { formatTime } from "../utils/time";
import { RunDetailsDrawer } from "./RunDetailsDrawer";
import "./RunsPanel.css";

type RunsPanelProps = {
  runs: Run[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onCreateRun?: () => void;
  onDeleteRun?: (runId: string) => void;
  onRetryRun?: (run: Run) => void;
  onCancelRun?: (runId: string) => void;
  onApplyEditDocs?: (run: Run) => void;
  onCancelEditDocs?: (run: Run) => void;
};

export const RunsPanel = ({
  runs,
  loading = false,
  error = null,
  onRetry,
  onCreateRun,
  onDeleteRun,
  onRetryRun,
  onCancelRun,
  onApplyEditDocs,
  onCancelEditDocs,
}: RunsPanelProps) => {
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(new Set());
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);

  const toggleErrorExpansion = (runId: string) => {
    setExpandedErrors((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const copyErrorToClipboard = async (error: string) => {
    try {
      await navigator.clipboard.writeText(error);
    } catch (err) {
      // Fallback for older browsers
      const textArea = document.createElement("textarea");
      textArea.value = error;
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand("copy");
      } catch (e) {
        // Ignore
      }
      document.body.removeChild(textArea);
    }
  };

  const getStatusColor = (status: Run["status"]): string => {
    switch (status) {
      case "queued":
        return "#9ca3af"; // 灰色
      case "running":
        return "#3b82f6"; // 蓝色
      case "succeeded":
        return "#10b981"; // 绿色
      case "failed":
        return "#ef4444"; // 红色
      case "canceled":
        return "#6b7280"; // 深灰色
      default:
        return "#9ca3af";
    }
  };

  const getStatusText = (status: Run["status"]): string => {
    switch (status) {
      case "queued":
        return "排队中";
      case "running":
        return "运行中";
      case "succeeded":
        return "成功";
      case "failed":
        return "失败";
      case "canceled":
        return "已取消";
      default:
        return status;
    }
  };

  const truncateError = (error: string | null | undefined): string => {
    if (!error) return "";
    return error.length > 100 ? `${error.slice(0, 100)}…` : error;
  };

  return (
    <div className="runs-panel">
      <div className="runs-panel-header">
        <h3 className="runs-panel-title">Tasks</h3>
        {onCreateRun && (
          <button className="runs-panel-create-btn" onClick={onCreateRun} aria-label="创建任务">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M8 3v10M3 8h10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        )}
      </div>

      <div className="runs-panel-content">
        {loading ? (
          <div className="runs-panel-empty">
            <p>Loading tasks…</p>
          </div>
        ) : error ? (
          <div className="runs-panel-empty">
            <p>Failed to load tasks</p>
            {onRetry && (
              <button className="runs-panel-retry-btn" onClick={onRetry}>
                重试
              </button>
            )}
          </div>
        ) : runs.length === 0 ? (
          <div className="runs-panel-empty">
            <p>No tasks yet</p>
          </div>
        ) : (
          <div className="runs-list">
            {runs.map((run) => (
              <div
                key={run.id}
                className="run-item run-item-clickable"
                role="button"
                tabIndex={0}
                onClick={() => setSelectedRun(run)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSelectedRun(run);
                  }
                }}
              >
                <div className="run-item-header">
                  <span
                    className="run-status-badge"
                    style={{ backgroundColor: getStatusColor(run.status) }}
                  >
                    {getStatusText(run.status)}
                  </span>
                  <span className="run-title">
                    {run.title || run.type}
                  </span>
                  <span className="run-time">{formatTime(run.updated_at)}</span>
                  {/* 运行中状态显示取消按钮 */}
                  {(run.status === "queued" || run.status === "running") && onCancelRun && (
                    <button
                      className="run-action-btn run-cancel-btn run-header-action-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedRun(null);
                        onCancelRun(run.id);
                      }}
                      aria-label="取消任务"
                      title="取消任务"
                    >
                      取消
                    </button>
                  )}
                  {/* 终态显示删除按钮 */}
                  {(run.status === "succeeded" || run.status === "failed" || run.status === "canceled") && onDeleteRun && (
                    <button
                      className="run-delete-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedRun(null);
                        onDeleteRun(run.id);
                      }}
                      aria-label="删除任务"
                      title="删除任务"
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
                {run.progress !== null && run.progress !== undefined && (
                  <div className="run-progress">
                    <div className="run-progress-bar">
                      <div
                        className="run-progress-fill"
                        style={{ width: `${run.progress}%` }}
                      />
                    </div>
                    <span className="run-progress-text">{run.progress}%</span>
                  </div>
                )}
                {(run.status === "failed" || run.status === "canceled") && run.error && (
                  <div className="run-error">
                    <div className="run-error-content">
                      {expandedErrors.has(run.id) ? run.error : truncateError(run.error)}
                      {(run.error.includes("Errno 2") || run.error.includes("No such file or directory")) && (
                        <div className="run-error-hint">环境/证书路径问题：请重启 up.ps1 或改用 stub 模式。</div>
                      )}
                      {run.error.length > 100 && (
                      <button
                            className="run-error-toggle"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleErrorExpansion(run.id);
                            }}
                          >
                          {expandedErrors.has(run.id) ? "收起" : "展开"}
                        </button>
                      )}
                    </div>
                    <div className="run-error-actions">
                      {run.status === "failed" && onRetryRun && (
                        <button
                          className="run-action-btn run-retry-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            onRetryRun(run);
                          }}
                        >
                          重试
                        </button>
                      )}
                      <button
                        className="run-action-btn run-copy-error-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          copyErrorToClipboard(run.error || "");
                        }}
                        title="复制错误信息"
                      >
                        复制错误
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      <RunDetailsDrawer
        run={selectedRun}
        onClose={() => setSelectedRun(null)}
        onRetryRun={onRetryRun}
        onApplyEditDocs={onApplyEditDocs}
        onCancelEditDocs={onCancelEditDocs}
      />
    </div>
  );
};
