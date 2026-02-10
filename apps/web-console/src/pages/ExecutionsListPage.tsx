import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ExecutionSummary, listExecutions } from "../api/executions";

const STATUS_OPTIONS = ["all", "completed", "failed", "rolled_back", "pending"] as const;
const VERDICT_OPTIONS = ["all", "allow", "need_approval", "deny"] as const;
const RISK_LEVEL_OPTIONS = ["all", "low", "medium", "high", "critical"] as const;

type StatusFilter = (typeof STATUS_OPTIONS)[number];
type VerdictFilter = (typeof VERDICT_OPTIONS)[number];
type RiskLevelFilter = (typeof RISK_LEVEL_OPTIONS)[number];

export const ExecutionsListPage = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const correlationIdFromUrl = searchParams.get("correlation_id") ?? undefined;

  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("all");
  const [riskLevelFilter, setRiskLevelFilter] = useState<RiskLevelFilter>("all");

  // Pagination
  const [limit] = useState(20);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const loadExecutions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listExecutions({
        limit,
        offset,
        status: statusFilter === "all" ? undefined : statusFilter,
        verdict: verdictFilter === "all" ? undefined : verdictFilter,
        risk_level: riskLevelFilter === "all" ? undefined : riskLevelFilter,
        correlation_id: correlationIdFromUrl,
      });
      setExecutions(response.executions);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load executions");
    } finally {
      setLoading(false);
    }
  }, [limit, offset, statusFilter, verdictFilter, riskLevelFilter, correlationIdFromUrl]);

  useEffect(() => {
    loadExecutions();
  }, [loadExecutions]);

  const handleExecutionClick = (executionId: string) => {
    navigate(`/executions/${executionId}`);
  };

  const handlePreviousPage = () => {
    setOffset(Math.max(0, offset - limit));
  };

  const handleNextPage = () => {
    setOffset(offset + limit);
  };

  const formatDuration = (seconds: number | null) => {
    if (seconds === null) return "—";
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    return `${seconds.toFixed(2)}s`;
  };

  const formatTimestamp = (timestamp: string) => {
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

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);
  const hasNextPage = offset + limit < total;

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 p-4">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Execution History</h1>
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
          View and monitor code execution history
        </p>
      </div>

      {/* Filters */}
      <div className="border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="flex flex-wrap gap-4">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Status:
            </label>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value as StatusFilter);
                setOffset(0);
              }}
              className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === "all" ? "All" : opt}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Verdict:
            </label>
            <select
              value={verdictFilter}
              onChange={(e) => {
                setVerdictFilter(e.target.value as VerdictFilter);
                setOffset(0);
              }}
              className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            >
              {VERDICT_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === "all" ? "All" : opt}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
              Risk Level:
            </label>
            <select
              value={riskLevelFilter}
              onChange={(e) => {
                setRiskLevelFilter(e.target.value as RiskLevelFilter);
                setOffset(0);
              }}
              className="px-3 py-1 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
            >
              {RISK_LEVEL_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt === "all" ? "All" : opt}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={loadExecutions}
            className="ml-auto px-4 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium transition-colors"
          >
            Refresh
          </button>
        </div>
        {correlationIdFromUrl && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Filtering by correlation_id: <span className="font-mono">{correlationIdFromUrl}</span>
            </span>
            <button
              type="button"
              onClick={() => {
                setSearchParams((prev) => {
                  const next = new URLSearchParams(prev);
                  next.delete("correlation_id");
                  return next;
                });
                setOffset(0);
              }}
              className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              Clear
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-gray-600 dark:text-gray-400">Loading executions...</div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-red-600 dark:text-red-400">{error}</div>
          </div>
        ) : executions.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-gray-600 dark:text-gray-400">No executions found</div>
          </div>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Execution ID
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Verdict
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Risk
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Started At
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Duration
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Files
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Verification
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  Health
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
              {executions.map((exec) => (
                <tr
                  key={exec.execution_id}
                  onClick={() => handleExecutionClick(exec.execution_id)}
                  className="hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 text-sm">
                    <div className="text-blue-600 dark:text-blue-400 font-mono">
                      {exec.execution_id}
                    </div>
                    {exec.error_message && (
                      <div className="text-xs text-red-600 dark:text-red-400 mt-1 truncate max-w-md">
                        {exec.error_message}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${getStatusBadgeColor(
                        exec.status
                      )}`}
                    >
                      {exec.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-100">
                    {exec.verdict}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`font-medium ${getRiskLevelColor(exec.risk_level)}`}>
                      {exec.risk_level}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {formatTimestamp(exec.started_at)}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-100 font-mono">
                    {formatDuration(exec.duration_seconds)}
                  </td>
                  <td className="px-4 py-3 text-sm text-center text-gray-900 dark:text-gray-100">
                    {exec.files_changed}
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    {exec.verification_passed ? (
                      <span className="text-green-600 dark:text-green-400">✓</span>
                    ) : (
                      <span className="text-red-600 dark:text-red-400">✗</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    {exec.health_checks_passed ? (
                      <span className="text-green-600 dark:text-green-400">✓</span>
                    ) : (
                      <span className="text-red-600 dark:text-red-400">✗</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {!loading && !error && executions.length > 0 && (
        <div className="border-t border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Showing {offset + 1} to {Math.min(offset + limit, total)} of {total} executions
            </div>
            <div className="flex gap-2">
              <button
                onClick={handlePreviousPage}
                disabled={offset === 0}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <span className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">
                Page {currentPage} of {totalPages || 1}
              </span>
              <button
                onClick={handleNextPage}
                disabled={!hasNextPage}
                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
