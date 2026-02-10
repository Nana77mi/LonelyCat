import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ExecutionDetail,
  ArtifactInfo,
  ExecutionLineage,
  SimilarExecutionItem,
  ExecutionReplay,
  ExecutionEvent,
  ReflectionHintsResponse,
  getExecution,
  getExecutionArtifacts,
  getExecutionLineage,
  getSimilarExecutions,
  replayExecution,
  getExecutionEvents,
  getReflectionHints,
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

  // 2.5-A1: Compare modal (left = current execution, right = similar)
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareRightId, setCompareRightId] = useState<string | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareData, setCompareData] = useState<{
    plan_diff: { left: Record<string, unknown>; right: Record<string, unknown> };
    decision_diff: { left: Record<string, unknown>; right: Record<string, unknown> };
    step_duration_comparison: { step_name: string; left_seconds: number; right_seconds: number; delta_seconds: number }[];
  } | null>(null);

  // 2.5-C2: replay for current execution (decision/suggestions) + reflection hints modal
  const [replayData, setReplayData] = useState<ExecutionReplay | null>(null);
  const [hintsModalOpen, setHintsModalOpen] = useState(false);
  const [hintsData, setHintsData] = useState<ReflectionHintsResponse | null>(null);
  const [hintsLoading, setHintsLoading] = useState(false);
  const [hintsError, setHintsError] = useState<string | null>(null);

  const loadExecutionData = useCallback(async () => {
    if (!executionId) return;

    setLoading(true);
    setError(null);
    setReplayData(null);
    try {
      const [execData, artifactsData, lineageData, similarData, replayResp] = await Promise.all([
        getExecution(executionId),
        getExecutionArtifacts(executionId).catch(() => null),
        getExecutionLineage(executionId).catch(() => null),
        getSimilarExecutions(executionId, 5).then((r) => r.similar).catch(() => []),
        replayExecution(executionId).catch(() => null),
      ]);
      setExecution(execData);
      setArtifacts(artifactsData);
      setLineage(lineageData);
      setSimilarList(similarData);
      setReplayData(replayResp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load execution");
    } finally {
      setLoading(false);
    }
  }, [executionId]);

  const openCompare = useCallback(
    async (rightId: string) => {
      if (!executionId) return;
      setCompareRightId(rightId);
      setCompareModalOpen(true);
      setCompareLoading(true);
      setCompareError(null);
      setCompareData(null);
      try {
        const [replayLeft, replayRight, eventsLeft, eventsRight] = await Promise.all([
          replayExecution(executionId),
          replayExecution(rightId),
          getExecutionEvents(executionId, 500),
          getExecutionEvents(rightId, 500),
        ]);
        const plan_diff = {
          left: {
            intent: replayLeft.plan?.intent ?? "—",
            affected_paths: replayLeft.plan?.affected_paths ?? [],
            risk_level: replayLeft.plan?.risk_level ?? "—",
            files_changed: replayLeft.execution?.files_changed ?? 0,
          },
          right: {
            intent: replayRight.plan?.intent ?? "—",
            affected_paths: replayRight.plan?.affected_paths ?? [],
            risk_level: replayRight.plan?.risk_level ?? "—",
            files_changed: replayRight.execution?.files_changed ?? 0,
          },
        };
        const decision_diff = {
          left: {
            reasons: replayLeft.decision?.reasons ?? [],
            suggestions: (replayLeft.decision as { suggestions?: string[] })?.suggestions ?? [],
            reflection_hints_used: (replayLeft.decision as { reflection_hints_used?: boolean })?.reflection_hints_used,
            hints_digest: (replayLeft.decision as { hints_digest?: string })?.hints_digest,
          },
          right: {
            reasons: replayRight.decision?.reasons ?? [],
            suggestions: (replayRight.decision as { suggestions?: string[] })?.suggestions ?? [],
            reflection_hints_used: (replayRight.decision as { reflection_hints_used?: boolean })?.reflection_hints_used,
            hints_digest: (replayRight.decision as { hints_digest?: string })?.hints_digest,
          },
        };
        const stepDurations = (events: ExecutionEvent[]) => {
          const byStep: Record<string, number> = {};
          for (const e of events) {
            if (e.event === "step_end" && e.step_name != null && e.duration_seconds != null) {
              byStep[e.step_name] = e.duration_seconds;
            }
          }
          return byStep;
        };
        const leftSteps = stepDurations(eventsLeft.events ?? []);
        const rightSteps = stepDurations(eventsRight.events ?? []);
        const allStepNames = Array.from(new Set([...Object.keys(leftSteps), ...Object.keys(rightSteps)]));
        const step_duration_comparison = allStepNames.map((step_name) => {
          const left_seconds = leftSteps[step_name] ?? 0;
          const right_seconds = rightSteps[step_name] ?? 0;
          return {
            step_name,
            left_seconds,
            right_seconds,
            delta_seconds: right_seconds - left_seconds,
          };
        });
        setCompareData({ plan_diff, decision_diff, step_duration_comparison });
      } catch (err) {
        setCompareError(err instanceof Error ? err.message : "Compare failed");
      } finally {
        setCompareLoading(false);
      }
    },
    [executionId]
  );

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
        {(exec.is_repair || exec.repair_for_execution_id) && (
          <div className="flex items-center gap-2 mt-2">
            <span className="text-xs px-2 py-1 rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border border-amber-300 dark:border-amber-700">
              Repair
            </span>
            {exec.repair_for_execution_id && (
              <span className="text-xs">
                for{" "}
                <button
                  type="button"
                  onClick={() => navigate(`/executions/${exec.repair_for_execution_id}`)}
                  className="font-mono text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {exec.repair_for_execution_id}
                </button>
              </span>
            )}
          </div>
        )}
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

          {/* Governance decision & suggestions (Phase 2.5-C2) */}
          {replayData?.decision && (
            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Governance Decision
              </h2>
              <div className="space-y-3 text-sm">
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Verdict:</span>{" "}
                  <span className="font-medium text-gray-900 dark:text-white">
                    {replayData.decision.verdict}
                  </span>
                </div>
                {(replayData.decision.reasons as string[])?.length > 0 && (
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Reasons:</span>{" "}
                    <span className="text-gray-900 dark:text-white">
                      {(replayData.decision.reasons as string[]).join("; ")}
                    </span>
                  </div>
                )}
                {(replayData.decision as { suggestions?: string[] }).suggestions?.length > 0 && (
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Suggestions:</span>{" "}
                    <ul className="list-disc list-inside mt-1 text-gray-900 dark:text-white">
                      {(replayData.decision as { suggestions?: string[] }).suggestions!.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="pt-2">
                  <button
                    type="button"
                    onClick={async () => {
                      setHintsModalOpen(true);
                      setHintsLoading(true);
                      setHintsError(null);
                      setHintsData(null);
                      try {
                        const h = await getReflectionHints();
                        setHintsData(h);
                      } catch (e) {
                        setHintsError(e instanceof Error ? e.message : "Failed to load hints");
                      } finally {
                        setHintsLoading(false);
                      }
                    }}
                    className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    View reflection hints
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Lineage (Phase 2.4-A, 2.5-A2 Jump) */}
          {lineage && (
            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Lineage
                </h2>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const rootId = lineage.ancestors?.length ? lineage.ancestors[0].execution_id : executionId;
                      if (rootId) navigate(`/executions/${rootId}`);
                    }}
                    className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    Jump to root
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const latestId = lineage.latest_in_correlation?.execution_id ?? executionId;
                      if (latestId) navigate(`/executions/${latestId}`);
                    }}
                    className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                  >
                    Jump to latest
                  </button>
                </div>
              </div>
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
                      <div className="flex items-center gap-2 shrink-0">
                        <button
                          type="button"
                          onClick={() => openCompare(item.execution.execution_id)}
                          className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                        >
                          Compare
                        </button>
                        <span className="text-xs font-mono text-gray-500 dark:text-gray-400">
                          score {(item.score * 100).toFixed(0)}%
                        </span>
                      </div>
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

      {/* 2.5-A1: Compare modal */}
      {compareModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setCompareModalOpen(false)}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-auto m-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                Compare: {executionId} vs {compareRightId}
              </h3>
              <button
                type="button"
                onClick={() => setCompareModalOpen(false)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                Close
              </button>
            </div>
            <div className="p-4 space-y-6">
              {compareLoading && (
                <div className="text-gray-600 dark:text-gray-400">Loading compare data...</div>
              )}
              {compareError && (
                <div className="text-red-600 dark:text-red-400">{compareError}</div>
              )}
              {compareData && !compareLoading && (
                <>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Plan</h4>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div className="border border-gray-200 dark:border-gray-700 rounded p-3">
                        <div className="font-mono text-xs text-gray-500 dark:text-gray-400 mb-1">Current (left)</div>
                        <div><span className="text-gray-500 dark:text-gray-400">intent:</span> {String(compareData.plan_diff.left.intent)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">risk_level:</span> {String(compareData.plan_diff.left.risk_level)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">files_changed:</span> {String(compareData.plan_diff.left.files_changed)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">affected_paths:</span> {(compareData.plan_diff.left.affected_paths as string[])?.join(", ") || "—"}</div>
                      </div>
                      <div className="border border-gray-200 dark:border-gray-700 rounded p-3">
                        <div className="font-mono text-xs text-gray-500 dark:text-gray-400 mb-1">Similar (right)</div>
                        <div><span className="text-gray-500 dark:text-gray-400">intent:</span> {String(compareData.plan_diff.right.intent)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">risk_level:</span> {String(compareData.plan_diff.right.risk_level)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">files_changed:</span> {String(compareData.plan_diff.right.files_changed)}</div>
                        <div><span className="text-gray-500 dark:text-gray-400">affected_paths:</span> {(compareData.plan_diff.right.affected_paths as string[])?.join(", ") || "—"}</div>
                      </div>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Decision</h4>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div className="border border-gray-200 dark:border-gray-700 rounded p-3">
                        <div className="font-mono text-xs text-gray-500 dark:text-gray-400 mb-1">Current (left)</div>
                        <div><span className="text-gray-500 dark:text-gray-400">reasons:</span> {(compareData.decision_diff.left.reasons as string[])?.join("; ") || "—"}</div>
                        {(compareData.decision_diff.left.suggestions as string[])?.length > 0 && (
                          <div><span className="text-gray-500 dark:text-gray-400">suggestions:</span> {(compareData.decision_diff.left.suggestions as string[]).join("; ")}</div>
                        )}
                      </div>
                      <div className="border border-gray-200 dark:border-gray-700 rounded p-3">
                        <div className="font-mono text-xs text-gray-500 dark:text-gray-400 mb-1">Similar (right)</div>
                        <div><span className="text-gray-500 dark:text-gray-400">reasons:</span> {(compareData.decision_diff.right.reasons as string[])?.join("; ") || "—"}</div>
                        {(compareData.decision_diff.right.suggestions as string[])?.length > 0 && (
                          <div><span className="text-gray-500 dark:text-gray-400">suggestions:</span> {(compareData.decision_diff.right.suggestions as string[]).join("; ")}</div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Step duration (s)</h4>
                    <table className="w-full text-sm border border-gray-200 dark:border-gray-700">
                      <thead>
                        <tr className="bg-gray-50 dark:bg-gray-800">
                          <th className="text-left p-2">step_name</th>
                          <th className="text-right p-2">Left</th>
                          <th className="text-right p-2">Right</th>
                          <th className="text-right p-2">Δ (right−left)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {compareData.step_duration_comparison.map((row) => (
                          <tr key={row.step_name} className="border-t border-gray-200 dark:border-gray-700">
                            <td className="p-2 font-mono">{row.step_name}</td>
                            <td className="p-2 text-right font-mono">{row.left_seconds.toFixed(3)}</td>
                            <td className="p-2 text-right font-mono">{row.right_seconds.toFixed(3)}</td>
                            <td className={`p-2 text-right font-mono ${row.delta_seconds >= 0 ? "text-orange-600 dark:text-orange-400" : "text-green-600 dark:text-green-400"}`}>
                              {row.delta_seconds >= 0 ? "+" : ""}{row.delta_seconds.toFixed(3)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 2.5-C2: Reflection hints modal */}
      {hintsModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => setHintsModalOpen(false)}
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-auto m-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Reflection hints</h3>
              <button
                type="button"
                onClick={() => setHintsModalOpen(false)}
                className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
              >
                Close
              </button>
            </div>
            <div className="p-4 space-y-4 text-sm">
              {hintsLoading && <div className="text-gray-600 dark:text-gray-400">Loading…</div>}
              {hintsError && <div className="text-red-600 dark:text-red-400">{hintsError}</div>}
              {hintsData && !hintsLoading && (
                <>
                  {hintsData.window && (
                    <div><span className="text-gray-500 dark:text-gray-400">Window:</span> {hintsData.window}</div>
                  )}
                  {hintsData.suggested_policy?.length > 0 && (
                    <div>
                      <div className="font-medium text-gray-700 dark:text-gray-300 mb-1">Suggested policy</div>
                      <ul className="list-disc list-inside text-gray-900 dark:text-white">{hintsData.suggested_policy.map((s, i) => <li key={i}>{s}</li>)}</ul>
                    </div>
                  )}
                  {hintsData.false_allow_patterns?.length > 0 && (
                    <div>
                      <div className="font-medium text-gray-700 dark:text-gray-300 mb-1">False allow patterns</div>
                      <ul className="list-disc list-inside text-gray-900 dark:text-white">{hintsData.false_allow_patterns.map((s, i) => <li key={i}>{s}</li>)}</ul>
                    </div>
                  )}
                  {hintsData.hot_error_steps?.length > 0 && (
                    <div><span className="text-gray-500 dark:text-gray-400">Hot error steps:</span> {hintsData.hot_error_steps.join(", ")}</div>
                  )}
                  {hintsData.slow_steps?.length > 0 && (
                    <div><span className="text-gray-500 dark:text-gray-400">Slow steps:</span> {hintsData.slow_steps.join(", ")}</div>
                  )}
                  {hintsData.evidence_execution_ids?.length > 0 && (
                    <div>
                      <div className="font-medium text-gray-700 dark:text-gray-300 mb-1">Evidence (executions)</div>
                      <div className="flex flex-wrap gap-2">
                        {hintsData.evidence_execution_ids.map((id) => (
                          <button
                            key={id}
                            type="button"
                            onClick={() => { setHintsModalOpen(false); navigate(`/executions/${id}`); }}
                            className="text-xs font-mono px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-blue-600 dark:text-blue-400 hover:underline"
                          >
                            {id}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
