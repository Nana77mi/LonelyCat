import { useState } from "react";
import type { Run } from "../api/runs";
import "./RunDetailsDrawer.css";

type RunDetailsDrawerProps = {
  run: Run | null;
  onClose: () => void;
  onRetryRun?: (run: Run) => void;
  onApplyEditDocs?: (run: Run) => void;
  onCancelEditDocs?: (run: Run) => void;
};

type StepItem = {
  name?: string;
  ok?: boolean;
  duration_ms?: number;
  error_code?: string | null;
  meta?: Record<string, unknown>;
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
      return String(status);
  }
};

function buildDebugBundle(run: Run): string {
  const input = (run.input || {}) as Record<string, unknown>;
  const output = (run.output || {}) as Record<string, unknown>;
  const traceId = (output.trace_id as string) ?? (input.trace_id as string) ?? "—";
  const steps = (output.steps as StepItem[] | undefined) ?? [];
  const factsArt = (output.artifacts as Record<string, unknown> | undefined)?.facts as { snapshot_id?: string; source?: string } | undefined;
  const factsSnapshotId = factsArt?.snapshot_id ?? "—";
  const factsSnapshotSource = factsArt?.source ?? "—";
  const errorStr = run.error ?? (typeof output.error === "string" ? output.error : output.error ? JSON.stringify(output.error) : "—");
  const lines: string[] = [
    `run_id: ${run.id}`,
    `trace_id: ${traceId}`,
    `type: ${run.type}`,
    `status: ${run.status}`,
    `facts_snapshot_id: ${factsSnapshotId}`,
    `facts_snapshot_source: ${factsSnapshotSource}`,
  ];
  const settingsSnapshot = input.settings_snapshot as Record<string, unknown> | undefined;
  const webSettings = settingsSnapshot?.web as Record<string, unknown> | undefined;
  const fetchSettings = webSettings?.fetch as Record<string, unknown> | undefined;
  if (run.type === "research_report" && (webSettings || fetchSettings)) {
    lines.push("web_config:");
    lines.push(`  proxy: ${fetchSettings?.proxy ?? "(unset)"}`);
    lines.push(`  timeout_ms: ${fetchSettings?.timeout_ms ?? "(default)"}`);
    lines.push(`  max_bytes: ${fetchSettings?.max_bytes ?? "(default)"}`);
    lines.push(`  user_agent: ${fetchSettings?.user_agent ? "(set)" : "(default)"}`);
  }
  const artifacts = (output.artifacts as Record<string, unknown> | undefined) ?? {};
  const fetchSummaries = artifacts.fetch_summaries as Array<{ url?: string; ok?: boolean; final_url?: string; status_code?: number; truncated?: boolean; cache_hit?: boolean }> | undefined;
  if (run.type === "research_report" && fetchSummaries?.length) {
    lines.push("fetch_summary:");
    fetchSummaries.forEach((f, i) => {
      lines.push(`  [${i + 1}] ${f.url ?? "—"} ok=${f.ok ?? "?"} status_code=${f.status_code ?? "—"} final_url=${f.final_url ?? "—"} truncated=${f.truncated ?? "?"} cache_hit=${f.cache_hit ?? false}`);
    });
  }
  lines.push("steps:");
  lines.push(...steps.map((s) => `  ${s.name ?? "—"} ok=${s.ok ?? "?"} duration_ms=${s.duration_ms ?? "?"} error_code=${s.error_code ?? "—"}`));
  const hasNetworkError = steps.some(
    (s) =>
      s.error_code === "NetworkError" ||
      s.error_code === "network_unreachable" ||
      s.error_code === "connect_failed"
  );
  if (hasNetworkError) {
    const proxySet = !!fetchSettings?.proxy;
    if (!proxySet) {
      lines.push("");
      lines.push("诊断提示: 检测到网络不可达，可能需要配置 web.proxy 或系统代理（HTTP_PROXY/HTTPS_PROXY）");
    } else {
      lines.push("");
      lines.push("诊断提示: 代理已配置但仍失败，可能为代理不可用/鉴权失败/连接超时");
    }
  }
  lines.push(`error: ${errorStr}`);
  return lines.join("\n");
}

export const RunDetailsDrawer = ({ run, onClose, onRetryRun, onApplyEditDocs, onCancelEditDocs }: RunDetailsDrawerProps) => {
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);

  if (!run) {
    return null;
  }

  const input = (run.input || {}) as Record<string, unknown>;
  const output = (run.output || {}) as Record<string, unknown>;
  const result = (output.result as Record<string, unknown> | undefined) ?? {};
  const traceId = (output.trace_id as string) ?? (input.trace_id as string) ?? "—";
  const steps = (output.steps as StepItem[] | undefined) ?? [];
  const artifacts = (output.artifacts as Record<string, unknown> | undefined) ?? {};
  const summaryArt = (artifacts.summary as { text?: string; format?: string } | undefined) ?? {};
  const reportArt = (artifacts.report as { text?: string; format?: string } | undefined) ?? {};
  const sourcesList = (artifacts.sources as Array<{ title?: string; url?: string; snippet?: string; provider?: string }> | undefined) ?? [];
  const diffText = artifacts.diff as string | undefined;
  const patchIdFull = artifacts.patch_id as string | undefined;
  const patchIdShort = artifacts.patch_id_short as string | undefined;
  const patchIdDisplay = patchIdShort ?? patchIdFull ?? patchIdFull?.slice(0, 16);
  const waitConfirm = run.status === "succeeded" && result.task_state === "WAIT_CONFIRM" && diffText;
  const factsArt = (artifacts.facts as { snapshot_id?: string; source?: string } | undefined) ?? {};
  const factsSnapshotId = factsArt.snapshot_id ?? "—";
  const factsSnapshotSource = factsArt.source ?? "—";

  const handleCopyDebugBundle = async () => {
    try {
      await navigator.clipboard.writeText(buildDebugBundle(run));
      setCopyFeedback("已复制");
      setTimeout(() => setCopyFeedback(null), 2000);
    } catch {
      setCopyFeedback("复制失败");
      setTimeout(() => setCopyFeedback(null), 2000);
    }
  };

  const isFinalStatus =
    run.status === "succeeded" || run.status === "failed" || run.status === "canceled";

  return (
    <aside className="run-drawer-overlay" onClick={onClose}>
      <div className="run-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="run-drawer-header">
          <h3>Run 详情</h3>
          <div className="run-drawer-header-actions">
            <button
              type="button"
              className="run-drawer-btn run-drawer-copy-btn"
              onClick={handleCopyDebugBundle}
              aria-label="复制诊断信息"
            >
              {copyFeedback ?? "Copy Debug Bundle"}
            </button>
            {isFinalStatus && onRetryRun && (
              <button
                type="button"
                className="run-drawer-btn run-drawer-rerun-btn"
                onClick={() => {
                  onRetryRun(run);
                  onClose();
                }}
                aria-label="重跑任务"
              >
                Rerun
              </button>
            )}
            <button type="button" className="run-drawer-close" onClick={onClose} aria-label="关闭">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
              <path
                d="M15 5L5 15M5 5l10 10"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
          </div>
        </div>
        <div className="run-drawer-content">
          <div className="run-drawer-section">
            <div className="run-drawer-field">
              <strong>Type:</strong> {run.type}
            </div>
            <div className="run-drawer-field">
              <strong>Status:</strong> {getStatusText(run.status)}
            </div>
            <div className="run-drawer-field">
              <strong>Trace ID:</strong>
              <code className="run-drawer-code">{traceId}</code>
            </div>
          </div>

          <div className="run-drawer-section">
            <h4 className="run-drawer-section-title">Facts Snapshot</h4>
            <div className="run-drawer-field">
              <strong>snapshot_id:</strong>
              <code className="run-drawer-code">{factsSnapshotId}</code>
            </div>
            <div className="run-drawer-field">
              <strong>source:</strong> {factsSnapshotSource}
            </div>
          </div>

          {summaryArt.text !== undefined && summaryArt.text !== "" && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Artifacts — Summary</h4>
              <div className="run-drawer-block run-drawer-summary">
                {summaryArt.text}
              </div>
            </div>
          )}

          {reportArt.text !== undefined && reportArt.text !== "" && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Artifacts — Report</h4>
              <div className="run-drawer-block run-drawer-summary">
                {reportArt.text}
              </div>
            </div>
          )}

          {sourcesList.length > 0 && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Artifacts — Sources</h4>
              <ul className="run-drawer-sources">
                {sourcesList.map((src, i) => (
                  <li key={i} className="run-drawer-source-item">
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="run-drawer-source-link"
                    >
                      {src.title ?? src.url ?? "—"}
                    </a>
                    {src.snippet && (
                      <p className="run-drawer-source-snippet">{src.snippet}</p>
                    )}
                    {src.provider && (
                      <span className="run-drawer-source-provider">{src.provider}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {waitConfirm && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Diff（待确认）</h4>
              {patchIdDisplay && (
                <div className="run-drawer-field run-drawer-patch-id">
                  <strong>Patch ID:</strong> <code className="run-drawer-code">{patchIdDisplay}</code>
                </div>
              )}
              <pre className="run-drawer-diff">{diffText}</pre>
              <div className="run-drawer-wait-confirm-actions">
                {onApplyEditDocs && patchIdFull && (
                  <button
                    type="button"
                    className="run-drawer-btn run-drawer-apply-btn"
                    onClick={() => {
                      onApplyEditDocs(run);
                      onClose();
                    }}
                    aria-label="应用变更"
                  >
                    Apply
                  </button>
                )}
                <button
                  type="button"
                  className="run-drawer-btn run-drawer-cancel-edit-btn"
                  onClick={() => {
                    if (onCancelEditDocs && patchIdFull) {
                      onCancelEditDocs(run);
                    }
                    onClose();
                  }}
                  aria-label="取消"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {steps.length > 0 && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Steps</h4>
              <ul className="run-drawer-steps">
                {steps.map((step, i) => (
                  <li key={i} className="run-drawer-step-item">
                    <span className="run-drawer-step-name">{step.name ?? "—"}</span>
                    <span className="run-drawer-step-meta">
                      {step.duration_ms != null ? `${step.duration_ms} ms` : ""}
                      {step.ok === false && step.error_code ? ` · ${step.error_code}` : ""}
                    </span>
                    {step.ok === false && (
                      <span className="run-drawer-step-bad">failed</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {run.error && (
            <div className="run-drawer-section">
              <h4 className="run-drawer-section-title">Error</h4>
              <div className="run-drawer-error">{run.error}</div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
