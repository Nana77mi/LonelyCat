import { useEffect, useState } from "react";

import { FactRecord, fetchFactChain } from "../api/memory";
import "./FactDetailsDrawer.css";

type FactChainResponse = {
  root_id: string;
  items: FactRecord[];
  truncated: boolean;
};

type FactDetailsDrawerProps = {
  factId: string | null;
  onClose: () => void;
};

const formatObject = (value: unknown) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);

const renderObject = (value: unknown) =>
  typeof value === "string" ? <span>{value}</span> : <pre>{formatObject(value)}</pre>;

const formatTimestamp = (value: number | null | undefined) =>
  typeof value === "number" ? new Date(value * 1000).toLocaleString() : "Unknown";

export const FactDetailsDrawer = ({ factId, onClose }: FactDetailsDrawerProps) => {
  const [chain, setChain] = useState<FactChainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!factId) {
      setChain(null);
      setError(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const load = async () => {
      setChain(null);
      setError(null);
      setLoading(true);
      try {
        const response = await fetchFactChain(factId, 20, controller.signal);
        setChain(response);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load chain");
      } finally {
        setLoading(false);
      }
    };
    void load();
    return () => {
      controller.abort();
    };
  }, [factId]);

  if (!factId) {
    return null;
  }

  const root = chain?.items?.[0];
  const rootOverrides =
    root?.overrides ?? (root?.status === "ACTIVE" ? chain?.items?.[1]?.id ?? null : null);
  const hasItems = Boolean(chain?.items?.length);

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
          {root ? (
            <div className="fact-drawer-root">
              <div className="fact-drawer-predicate">
                <strong>{root.predicate}</strong>
              </div>
              <div className="fact-drawer-object">{renderObject(root.object)}</div>
              <div className="fact-drawer-meta">
                <span>Status: {root.status}</span>
                <span>Sequence: {root.seq ?? "Unknown"}</span>
                <span>Created: {formatTimestamp(root.created_at)}</span>
              </div>
              {rootOverrides ? (
                <div className="fact-drawer-field">
                  <strong>Overrides:</strong> {rootOverrides}
                </div>
              ) : null}
              {root.retracted_reason ? (
                <div className="fact-drawer-field">
                  <strong>Retracted reason:</strong> {root.retracted_reason}
                </div>
              ) : null}
            </div>
          ) : null}

          {chain && !hasItems ? (
            <div className="fact-drawer-empty">No facts available for this chain.</div>
          ) : null}

          {chain && hasItems ? (
            <div className="fact-drawer-chain">
              <h4>Overrides chain</h4>
              <div className="fact-chain-list">
                {chain.items.map((item, index) => {
                  const overriddenBy = chain.items[index - 1]?.id ?? null;
                  const overrides =
                    item.overrides ??
                    (item.status === "ACTIVE" ? chain.items[index + 1]?.id ?? null : null);
                  return (
                    <div key={item.id ?? `fact-${index}`} className="fact-chain-item">
                      <div className="fact-chain-header">
                        <strong>{item.status ?? "UNKNOWN"}</strong>
                        <span>seq {item.seq ?? "Unknown"}</span>
                        <span className="fact-chain-id">#{(item.id ?? "unknown").slice(0, 8)}</span>
                      </div>
                      <div className="fact-chain-content">
                        {item.predicate ?? "Unknown"}: {renderObject(item.object)}
                      </div>
                      <div className="fact-chain-meta">
                        <span>{formatTimestamp(item.created_at)}</span>
                        {overriddenBy ? <span>Overridden by: {overriddenBy}</span> : null}
                        {overrides ? <span>Overrides: {overrides}</span> : null}
                      </div>
                      {item.retracted_reason ? (
                        <div className="fact-chain-retracted">
                          Retracted reason: {item.retracted_reason}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
              {chain.truncated ? (
                <div className="fact-drawer-truncated">Chain truncated.</div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </aside>
  );
};
