import { useEffect, useState } from "react";

import { FactRecord, fetchFactChain } from "../api/memory";

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
    <aside>
      <div>
        <h3>Fact Details</h3>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {loading ? <p>Loading…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {root ? (
        <div>
          <div>
            <strong>{root.predicate}</strong> →
          </div>
          <div>{renderObject(root.object)}</div>
          <p>Status: {root.status}</p>
          <p>Sequence: {root.seq ?? "Unknown"}</p>
          <p>Created: {formatTimestamp(root.created_at)}</p>
          {rootOverrides ? <p>Overrides: {rootOverrides}</p> : null}
          {root.retracted_reason ? <p>Retracted reason: {root.retracted_reason}</p> : null}
        </div>
      ) : null}

      {chain && !hasItems ? <p>No facts available for this chain.</p> : null}

      {chain && hasItems ? (
        <div>
          <h4>Overrides chain</h4>
          <ul>
            {chain.items.map((item, index) => {
              const overriddenBy = chain.items[index - 1]?.id ?? null;
              const overrides =
                item.overrides ?? (item.status === "ACTIVE" ? chain.items[index + 1]?.id ?? null : null);
              return (
                <li key={item.id ?? `fact-${index}`}>
                  <div>
                    <div>
                      <strong>{item.status ?? "UNKNOWN"}</strong> · seq {item.seq ?? "Unknown"} ·{" "}
                      {(item.id ?? "unknown").slice(0, 8)}
                    </div>
                    <div>
                      {item.predicate ?? "Unknown"}: {renderObject(item.object)}
                    </div>
                    <div>{formatTimestamp(item.created_at)}</div>
                    {overriddenBy ? <div>Overridden by: {overriddenBy}</div> : null}
                    {overrides ? <div>Overrides: {overrides}</div> : null}
                    {item.retracted_reason ? (
                      <div>Retracted reason: {item.retracted_reason}</div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
          {chain.truncated ? <p>Chain truncated.</p> : null}
        </div>
      ) : null}
    </aside>
  );
};
