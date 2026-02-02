import { useEffect, useState } from "react";

import { Fact, getFact } from "../api/memory";
import "./FactDetailsDrawer.css";

type FactDetailsDrawerProps = {
  factId: string | null;
  onClose: () => void;
};

const formatValue = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);

const renderValue = (value: unknown) =>
  typeof value === "string" ? <span>{value}</span> : <pre>{formatValue(value)}</pre>;

const formatTimestamp = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString() : "Unknown";

export const FactDetailsDrawer = ({ factId, onClose }: FactDetailsDrawerProps) => {
  const [fact, setFact] = useState<Fact | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!factId) {
      setFact(null);
      setError(null);
      setLoading(false);
      return;
    }
    const load = async () => {
      setFact(null);
      setError(null);
      setLoading(true);
      try {
        const response = await getFact(factId);
        setFact(response);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load fact");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [factId]);

  if (!factId) {
    return null;
  }

  return (
    <aside className="fact-drawer-overlay" onClick={onClose}>
      <div className="fact-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="fact-drawer-header">
          <h3>Fact Details</h3>
          <button type="button" className="fact-drawer-close" onClick={onClose} aria-label="关闭">
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
        <div className="fact-drawer-content">
          {loading ? <div className="fact-drawer-loading">加载中…</div> : null}
          {error ? <div className="fact-drawer-error" role="alert">{error}</div> : null}
          {fact ? (
            <div className="fact-drawer-root">
              <div className="fact-drawer-field">
                <strong>Key:</strong> {fact.key}
              </div>
              <div className="fact-drawer-field">
                <strong>Value:</strong> {renderValue(fact.value)}
              </div>
              <div className="fact-drawer-meta">
                <span>Status: {fact.status}</span>
                <span>Scope: {fact.scope}</span>
                <span>Version: {fact.version}</span>
              </div>
              {fact.project_id ? (
                <div className="fact-drawer-field">
                  <strong>Project ID:</strong> {fact.project_id}
                </div>
              ) : null}
              {fact.session_id ? (
                <div className="fact-drawer-field">
                  <strong>Session ID:</strong> {fact.session_id}
                </div>
              ) : null}
              <div className="fact-drawer-field">
                <strong>Source:</strong> {fact.source_ref.kind} - {fact.source_ref.ref_id}
              </div>
              {fact.source_ref.excerpt ? (
                <div className="fact-drawer-field">
                  <strong>Source Excerpt:</strong> {fact.source_ref.excerpt}
                </div>
              ) : null}
              {fact.confidence !== null ? (
                <div className="fact-drawer-field">
                  <strong>Confidence:</strong> {fact.confidence.toFixed(2)}
                </div>
              ) : null}
              <div className="fact-drawer-meta">
                <span>Created: {formatTimestamp(fact.created_at)}</span>
                <span>Updated: {formatTimestamp(fact.updated_at)}</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
};
