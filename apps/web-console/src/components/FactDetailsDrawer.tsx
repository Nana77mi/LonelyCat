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
    let cancelled = false;
    const load = async () => {
      setChain(null);
      setError(null);
      setLoading(true);
      try {
        const response = await fetchFactChain(factId);
        if (cancelled) {
          return;
        }
        setChain(response);
      } catch (err) {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load chain");
      } finally {
        if (cancelled) {
          return;
        }
        setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
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
          <p>Sequence: {root.seq}</p>
          <p>Created: {new Date(root.created_at * 1000).toLocaleString()}</p>
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
                <li key={item.id}>
                  <div>
                    <div>
                      <strong>{item.status}</strong> · seq {item.seq} · {item.id.slice(0, 8)}
                    </div>
                    <div>
                      {item.predicate}: {renderObject(item.object)}
                    </div>
                    <div>{new Date(item.created_at * 1000).toLocaleString()}</div>
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
