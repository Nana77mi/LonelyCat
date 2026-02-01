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
  typeof value === "string" ? value : JSON.stringify(value);

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
      setLoading(true);
      setError(null);
      try {
        const response = await fetchFactChain(factId);
        if (!cancelled) {
          setChain(response);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load chain");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
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
          <p>
            <strong>{root.predicate}</strong> → {formatObject(root.object)}
          </p>
          <p>Status: {root.status}</p>
          <p>Sequence: {root.seq}</p>
          <p>Created: {new Date(root.created_at * 1000).toLocaleString()}</p>
        </div>
      ) : null}

      {chain ? (
        <div>
          <h4>Overrides chain</h4>
          <ul>
            {chain.items.map((item) => (
              <li key={item.id}>
                <div>
                  <div>
                    <strong>{item.status}</strong> · seq {item.seq} · {item.id.slice(0, 8)}
                  </div>
                  <div>
                    {item.predicate}: {formatObject(item.object)}
                  </div>
                  <div>{new Date(item.created_at * 1000).toLocaleString()}</div>
                </div>
              </li>
            ))}
          </ul>
          {chain.truncated ? <p>Chain truncated.</p> : null}
        </div>
      ) : null}
    </aside>
  );
};
