import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ExecutionDetail,
  ArtifactInfo,
  ExecutionLineage,
  SimilarExecutionItem,
  getExecution,
  getExecutionArtifacts,
  getExecutionLineage,
  getSimilarExecutions,
} from "../api/executions";

export const ExecutionDetailPage = () => {
  const { executionId } = useParams<{ executionId: string }>();
  const navigate = useNavigate();

  const [execution, setExecution] = useState<ExecutionDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactInfo | null>(null);
  const [lineage, setLineage] = useState<ExecutionLineage | null>(null);
  const [similarList, setSimilarList] = useState<SimilarExecutionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExecutionData = useCallback(async () => {
    if (!executionId) return;

    setLoading(true);
    setError(null);
    try {
      const [execData, artifactsData, lineageData, similarData] = await Promise.all([
        getExecution(executionId),
        getExecutionArtifacts(executionId).catch(() => null),
        getExecutionLineage(executionId).catch(() => null),
        getSimilarExecutions(executionId, 5).then((r) => r.similar).catch(() => []),
      ]);
      setExecution(execData);
      setArtifacts(artifactsData);
      setLineage(lineageData);
      setSimilarList(similarData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load execution");
    } finally {
      setLoading(false);
    }
  }, [executionId]);

  useEffect(() => {
    loadExecutionData();
  }, [loadExecutionData]);

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return "—";
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    return `${seconds.toFixed(2)}s`;
  };

  const formatTimestamp = (timestamp: string | null) => {
    if (!timestamp) return "—";
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp;
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300";
      case "failed":
        return "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300";
      case "rolled_back":
        return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300";
      case "pending":
        return "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300";
      default:
        return "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300";
    }
  };

  const getRiskLevelColor = (riskLevel: string) => {
    switch (riskLevel) {
      case "low":
        return "text-green-600 dark:text-green-400";
      case "medium":
        return "text-yellow-600 dark:text-yellow-400";
      case "high":
        return "text-orange-600 dark:text-orange-400";
      case "critical":
        return "text-red-600 dark:text-red-400";
      default:
        return "text-gray-600 dark:text-gray-400";
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-white dark:bg-gray-900">
        <div className="text-gray-600 dark:text-gray-400">Loading execution details...</div>
      </div>
    );
  }

  if (error || !execution) {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-white dark:bg-gray-900">
        <div className="text-red-600 dark:text-red-400 mb-4">{error || "Execution not found"}</div>
        <button
          onClick={() => navigate("/executions")}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium transition-colors"
        >
          Back to Executions
        </button>
      </div>
    );
  }

  const { execution: exec, steps } = execution;

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="flex items-center gap-4 mb-2 flex-wrap">
          <button
            onClick={() => navigate("/executions")}
            className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
          >
            ← Back to Executions
          </button>
          {exec.correlation_id && (
            <button
              type="button"
              onClick={() => navigate(`/executions?correlation_id=${encodeURIComponent(exec.correlation_id)}`)}
              className="text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400"
            >
              View same chain
            </button>
          )}
        </div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white font-mono">
          {exec.execution_id}
        </h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Summary Card */}
          <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Execution Summary
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">Status</div>
                <span
                  className={`inline-flex mt-1 px-2 py-1 text-xs font-semibold rounded-full ${getStatusBadgeColor(
                    exec.status
                  )}`}
                >
                  {exec.status}
                </span>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">Verdict</div>
                <div className="text-sm text-gray-900 dark:text-white mt-1">{exec.verdict}</div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Risk Level
                </div>
                <div className={`text-sm font-medium mt-1 ${getRiskLevelColor(exec.risk_level)}`}>
                  {exec.risk_level}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Started At
                </div>
                <div className="text-sm text-gray-900 dark:text-white mt-1">
                  {formatTimestamp(exec.started_at)}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Ended At
                </div>
                <div className="text-sm text-gray-900 dark:text-white mt-1">
                  {formatTimestamp(exec.ended_at)}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Duration
                </div>
                <div className="text-sm text-gray-900 dark:text-white font-mono mt-1">
                  {formatDuration(exec.duration_seconds)}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Files Changed
                </div>
                <div className="text-sm text-gray-900 dark:text-white mt-1">{exec.files_changed}</div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Verification
                </div>
                <div className="text-sm mt-1">
                  {exec.verification_passed ? (
                    <span className="text-green-600 dark:text-green-400">✓ Passed</span>
                  ) : (
                    <span className="text-red-600 dark:text-red-400">✗ Failed</span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  Health Checks
                </div>
                <div className="text-sm mt-1">
                  {exec.health_checks_passed ? (
                    <span className="text-green-600 dark:text-green-400">✓ Passed</span>
                  ) : (
                    <span className="text-red-600 dark:text-red-400">✗ Failed</span>
                  )}
                </div>
              </div>
              {exec.rolled_back && (
                <div className="col-span-2 md:col-span-3">
                  <div className="text-sm font-medium text-yellow-600 dark:text-yellow-400">
                    ⚠ This execution was rolled back
                  </div>
                </div>
              )}
              {exec.error_message && (
                <div className="col-span-2 md:col-span-3">
                  <div className="text-sm font-medium text-gray-500 dark:text-gray-400">Error</div>
                  <div className="text-sm text-red-600 dark:text-red-400 mt-1 font-mono bg-red-50 dark:bg-red-900/20 p-2 rounded">
                    {exec.error_step && <span className="font-bold">[{exec.error_step}]</span>}{" "}
                    {exec.error_message}
                  </div>
                </div>
              )}
            </div>
            <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Plan ID:</span>{" "}
                  <span className="font-mono text-gray-900 dark:text-white">{exec.plan_id}</span>
                </div>
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Changeset ID:</span>{" "}
                  <span className="font-mono text-gray-900 dark:text-white">
                    {exec.changeset_id}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Lineage (Phase 2.4-A) */}
          {lineage && (
            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Lineage
              </h2>
              <div className="space-y-4">
                {/* Path: root → … → current */}
                {(lineage.ancestors.length > 0 || lineage.descendants.length > 0 || lineage.siblings.length > 0) && (
                  <>
                    {lineage.ancestors.length > 0 && (
                      <div>
                        <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                          Ancestors (root → current)
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {lineage.ancestors.map((anc) => (
                            <span key={anc.execution_id} className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => navigate(`/executions/${anc.execution_id}`)}
                                className="text-xs font-mono px-2 py-1 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-blue-600 dark:text-blue-400 hover:underline"
                              >
                                {anc.execution_id}
                              </button>
                              <span className="text-gray-400">→</span>
                            </span>
                          ))}
                          <span className="text-xs font-mono px-2 py-1 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                            {lineage.execution.execution_id} (current)
                          </span>
                        </div>
                      </div>
                    )}
                    {lineage.siblings.length > 0 && (
                      <div>
                        <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                          Siblings
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {lineage.siblings.map((sib) => (
                            <button
                              key={sib.execution_id}
                              type="button"
                              onClick={() => navigate(`/executions/${sib.execution_id}`)}
                              className="text-xs font-mono px-2 py-1 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              {sib.execution_id}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {lineage.descendants.length > 0 && (
                      <div>
                        <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                          Descendants
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {lineage.descendants.map((desc) => (
                            <button
                              key={desc.execution_id}
                              type="button"
                              onClick={() => navigate(`/executions/${desc.execution_id}`)}
                              className="text-xs font-mono px-2 py-1 rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              {desc.execution_id}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
                {lineage.ancestors.length === 0 &&
                  lineage.descendants.length === 0 &&
                  lineage.siblings.length === 0 && (
                    <div className="text-sm text-gray-600 dark:text-gray-400">
                      No parent, siblings, or children. This execution is the only one in its chain.
                    </div>
                  )}
              </div>
            </div>
          )}

          {/* Similar Executions (Phase 2.4-D) */}
          {similarList.length > 0 && (
            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Similar Executions
              </h2>
              <div className="space-y-3">
                {similarList.map((item) => (
                  <div
                    key={item.execution.execution_id}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-900"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => navigate(`/executions/${item.execution.execution_id}`)}
                          className="text-sm font-mono text-blue-600 dark:text-blue-400 hover:underline truncate block"
                        >
                          {item.execution.execution_id}
                        </button>
                        <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          {item.why_similar.join(" · ")}
                        </div>
                      </div>
                      <span className="text-xs font-mono text-gray-500 dark:text-gray-400 shrink-0">
                        score {(item.score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Steps Timeline */}
          <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              Execution Steps
            </h2>
            {steps.length === 0 ? (
              <div className="text-sm text-gray-600 dark:text-gray-400">No steps recorded</div>
            ) : (
              <div className="space-y-3">
                {steps.map((step) => (
                  <div
                    key={step.id}
                    className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-900"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <span className="text-xs font-mono text-gray-500 dark:text-gray-400">
                            #{step.step_num}
                          </span>
                          <span className="text-sm font-medium text-gray-900 dark:text-white">
                            {step.step_name}
                          </span>
                          <span
                            className={`text-xs px-2 py-0.5 rounded ${getStatusBadgeColor(
                              step.status
                            )}`}
                          >
                            {step.status}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-gray-600 dark:text-gray-400 space-y-1">
                          <div>
                            <span className="font-medium">Started:</span>{" "}
                            {formatTimestamp(step.started_at)}
                          </div>
                          {step.ended_at && (
                            <div>
                              <span className="font-medium">Ended:</span>{" "}
                              {formatTimestamp(step.ended_at)}
                            </div>
                          )}
                          {step.duration_seconds !== null && (
                            <div>
                              <span className="font-medium">Duration:</span>{" "}
                              <span className="font-mono">
                                {formatDuration(step.duration_seconds)}
                              </span>
                            </div>
                          )}
                          {step.log_ref && (
                            <div>
                              <span className="font-medium">Log:</span>{" "}
                              <span className="font-mono text-blue-600 dark:text-blue-400">
                                {step.log_ref}
                              </span>
                            </div>
                          )}
                        </div>
                        {step.error_message && (
                          <div className="mt-2 text-xs text-red-600 dark:text-red-400 font-mono bg-red-50 dark:bg-red-900/20 p-2 rounded">
                            {step.error_code && <span className="font-bold">[{step.error_code}]</span>}{" "}
                            {step.error_message}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Artifacts Panel */}
          {artifacts && (
            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Artifacts
              </h2>
              <div className="space-y-4">
                <div>
                  <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                    Path
                  </div>
                  <div className="text-xs font-mono text-gray-900 dark:text-white bg-white dark:bg-gray-900 p-2 rounded border border-gray-200 dark:border-gray-700">
                    {artifacts.artifact_path}
                  </div>
                </div>

                <div>
                  <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                    4件套 Completeness
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {Object.entries(artifacts.four_piece_set).map(([file, exists]) => (
                      <div
                        key={file}
                        className="flex items-center gap-2 text-xs bg-white dark:bg-gray-900 p-2 rounded border border-gray-200 dark:border-gray-700"
                      >
                        <span className={exists ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
                          {exists ? "✓" : "✗"}
                        </span>
                        <span className="font-mono text-gray-900 dark:text-white">{file}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 text-xs">
                    {artifacts.artifacts_complete ? (
                      <span className="text-green-600 dark:text-green-400">✓ All artifacts present</span>
                    ) : (
                      <span className="text-yellow-600 dark:text-yellow-400">
                        ⚠ Some artifacts missing
                      </span>
                    )}
                  </div>
                </div>

                {artifacts.step_logs.length > 0 && (
                  <div>
                    <div className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                      Step Logs ({artifacts.step_logs.length})
                    </div>
                    <div className="space-y-1">
                      {artifacts.step_logs.map((log) => (
                        <div
                          key={log}
                          className="text-xs font-mono text-gray-900 dark:text-white bg-white dark:bg-gray-900 px-2 py-1 rounded border border-gray-200 dark:border-gray-700"
                        >
                          {log}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-4 text-xs">
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">stdout:</span>{" "}
                    {artifacts.has_stdout ? (
                      <span className="text-green-600 dark:text-green-400">✓</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">stderr:</span>{" "}
                    {artifacts.has_stderr ? (
                      <span className="text-green-600 dark:text-green-400">✓</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">backups:</span>{" "}
                    {artifacts.has_backups ? (
                      <span className="text-green-600 dark:text-green-400">✓</span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
