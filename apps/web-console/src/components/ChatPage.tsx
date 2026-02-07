import { useState, useRef, useEffect } from "react";
import type { Message } from "../api/conversations";
import type { Run } from "../api/runs";
import "./ChatPage.css";

type ChatPageProps = {
  messages: Message[];
  onSendMessage: (content: string, retryMessageId?: string) => void;
  loading?: boolean;
  /** Current conversation runs; used to render run_code_snippet completion as card. */
  runs?: Run[];
  /** Open run details drawer (e.g. from card "查看输出"). */
  onOpenRunDetails?: (runId: string) => void;
};

/** Extract user-facing reply from run.output (align with backend _extract_reply). */
function getReplyFromRunOutput(output: Record<string, unknown> | null | undefined): string {
  if (!output || typeof output !== "object") return "";
  const reply = output.reply ?? output.final_response;
  if (typeof reply === "string" && reply.trim()) return reply.trim();
  const result = output.result as Record<string, unknown> | undefined;
  if (result && typeof result === "object") {
    const r = (result.reply ?? result.final_response) as string | undefined;
    if (typeof r === "string" && r.trim()) return r.trim();
  }
  return "";
}

/** Resolve exec_id from run.output (align with RunDetailsDrawer resolveExecId). */
function getExecIdFromRunOutput(output: Record<string, unknown> | null | undefined): string | undefined {
  if (!output || typeof output !== "object") return undefined;
  const result = (output.result as Record<string, unknown> | undefined) ?? {};
  const artifacts = (output.artifacts as Record<string, unknown> | undefined) ?? {};
  const candidates = [
    result.exec_id,
    (result.observation as Record<string, unknown> | undefined)?.exec_id,
    (result.meta as Record<string, unknown> | undefined)?.exec_id,
    (artifacts.exec as Record<string, unknown> | undefined)?.exec_id,
  ];
  for (const c of candidates) {
    if (typeof c === "string" && c.trim()) return c;
  }
  return undefined;
}

const RUN_CODE_SNIPPET_TYPE = "run_code_snippet";

export const ChatPage = ({ messages, onSendMessage, loading, runs = [], onOpenRunDetails }: ChatPageProps) => {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (messagesEndRef.current?.scrollIntoView) {
      messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    onSendMessage(input.trim());
    setInput("");
    // 重置textarea高度
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  return (
    <div className="chat-page">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="empty-icon">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                <path
                  d="M24 8C15.16 8 8 15.16 8 24C8 32.84 15.16 40 24 40C32.84 40 40 32.84 40 24C40 15.16 32.84 8 24 8ZM24 36C18.48 36 14 31.52 14 26C14 20.48 18.48 16 24 16C29.52 16 34 20.48 34 26C34 31.52 29.52 36 24 36Z"
                  fill="currentColor"
                  opacity="0.3"
                />
              </svg>
            </div>
            <h2>开始对话</h2>
            <p>输入消息开始与 LonelyCat 对话</p>
          </div>
        ) : (
          messages.map((message) => {
            const isFailed = message.meta_json && typeof message.meta_json === "object" && "failed" in message.meta_json && message.meta_json.failed === true;
            const errorMessage = isFailed && message.meta_json && typeof message.meta_json === "object" && "error" in message.meta_json
              ? String(message.meta_json.error)
              : null;
            const isRetryable = isFailed && message.meta_json && typeof message.meta_json === "object" && "retryable" in message.meta_json && message.meta_json.retryable === true;
            // 检查是否是主动消息（run 完成）
            const isProactiveMessage = message.source_ref && message.source_ref.kind === "run";
            const runId = message.source_ref?.ref_id;
            const linkedRun = runId && runs.length > 0 ? runs.find((r) => r.id === runId) : undefined;
            const isRunCodeSnippetCard =
              isProactiveMessage &&
              linkedRun &&
              (linkedRun.type || "").trim().replace(/\s+/g, "_") === RUN_CODE_SNIPPET_TYPE;

            return (
              <div
                key={message.id}
                className={`message ${message.role} ${isFailed ? "message-failed" : ""} ${isProactiveMessage ? "message-proactive" : ""}`}
              >
                <div className="message-avatar">
                  {message.role === "user" ? (
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <path
                        d="M10 10C12.7614 10 15 7.76142 15 5C15 2.23858 12.7614 0 10 0C7.23858 0 5 2.23858 5 5C5 7.76142 7.23858 10 10 10Z"
                        fill="currentColor"
                      />
                      <path
                        d="M10 12C5.58172 12 2 15.5817 2 20H18C18 15.5817 14.4183 12 10 12Z"
                        fill="currentColor"
                      />
                    </svg>
                  ) : (
                    // assistant 或 system 消息使用相同的图标
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                      <path
                        d="M10 0C4.48 0 0 4.48 0 10C0 15.52 4.48 20 10 20C15.52 20 20 15.52 20 10C20 4.48 15.52 0 10 0ZM10 18C5.59 18 2 14.41 2 10C2 5.59 5.59 2 10 2C14.41 2 18 5.59 18 10C18 14.41 14.41 18 10 18ZM9 5H11V11H9V5ZM9 13H11V15H9V13Z"
                        fill="currentColor"
                      />
                    </svg>
                  )}
                </div>
                <div className="message-content">
                  {isProactiveMessage && !isRunCodeSnippetCard && (
                    <div className="message-proactive-badge">
                      <span className="message-proactive-label">任务完成</span>
                    </div>
                  )}
                  {isRunCodeSnippetCard && linkedRun ? (
                    <div className="message-run-card">
                      <div className="message-run-card-header">
                        <span
                          className={`message-run-card-status message-run-card-status--${linkedRun.status}`}
                        >
                          {linkedRun.status === "succeeded"
                            ? "成功"
                            : linkedRun.status === "failed"
                              ? "失败"
                              : linkedRun.status === "canceled"
                                ? "已取消"
                                : linkedRun.status === "running"
                                  ? "运行中"
                                  : "排队中"}
                        </span>
                        {linkedRun.title && (
                          <span className="message-run-card-title">{linkedRun.title}</span>
                        )}
                      </div>
                      <div className="message-run-card-body">
                        {getReplyFromRunOutput(linkedRun.output) || message.content || "代码执行完成。"}
                      </div>
                      {getExecIdFromRunOutput(linkedRun.output) && (
                        <div className="message-run-card-exec-id">
                          exec_id={getExecIdFromRunOutput(linkedRun.output)}
                        </div>
                      )}
                      {onOpenRunDetails && (
                        <button
                          type="button"
                          className="message-run-card-view-btn"
                          onClick={() => onOpenRunDetails(linkedRun.id)}
                          aria-label="查看输出"
                        >
                          查看输出
                        </button>
                      )}
                    </div>
                  ) : (
                    <>
                      {isProactiveMessage && (
                        <div className="message-proactive-badge">
                          <span className="message-proactive-label">任务完成</span>
                        </div>
                      )}
                      <div className="message-text">{message.content}</div>
                    </>
                  )}
                  {isFailed && errorMessage && (
                    <div className="message-error">
                      <span className="message-error-text">{errorMessage}</span>
                      {isRetryable && (
                        <button
                          className="message-retry-btn"
                          onClick={() => onSendMessage(message.content, message.id)}
                          disabled={loading}
                          aria-label="重试"
                        >
                          重试
                        </button>
                      )}
                    </div>
                  )}
                  <div className="message-time">
                    {new Date(message.created_at).toLocaleTimeString("zh-CN", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                </div>
              </div>
            );
          })
        )}
        {loading && (
          <div className="message assistant">
            <div className="message-avatar">
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path
                  d="M10 0C4.48 0 0 4.48 0 10C0 15.52 4.48 20 10 20C15.52 20 20 15.52 20 10C20 4.48 15.52 0 10 0ZM10 18C5.59 18 2 14.41 2 10C2 5.59 5.59 2 10 2C14.41 2 18 5.59 18 10C18 14.41 14.41 18 10 18ZM9 5H11V11H9V5ZM9 13H11V15H9V13Z"
                  fill="currentColor"
                />
              </svg>
            </div>
            <div className="message-content">
              <div className="message-text">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <div className="chat-input-container">
          <textarea
            ref={textareaRef}
            className="chat-input"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              adjustTextareaHeight();
            }}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Shift+Enter 换行)"
            rows={1}
            disabled={loading}
          />
          <button
            type="submit"
            className="send-btn"
            disabled={!input.trim() || loading}
            aria-label="发送"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M18 2L9 11M18 2L12 18L9 11M18 2L2 8L9 11"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
};
