import { useCallback, useEffect, useMemo, useState } from "react";

import {
  Proposal,
  Fact,
  Scope,
  SourceKind,
  acceptProposal,
  fetchFacts,
  fetchProposals,
  proposeFact,
  rejectProposal,
  expireProposal,
  revokeFact,
  archiveFact,
  reactivateFact,
  ProposalCreateRequest,
} from "../api/memory";
import { FactDetailsDrawer } from "../components/FactDetailsDrawer";

const STATUS_OPTIONS = ["all", "active", "revoked", "archived"] as const;
const SCOPE_OPTIONS: Scope[] = ["global", "project", "session"];

type StatusFilter = (typeof STATUS_OPTIONS)[number];

type RejectReasonMap = Record<string, string>;

const defaultProposal: ProposalCreateRequest = {
  payload: {
    key: "",
    value: "",
    tags: [],
    ttl_seconds: null,
  },
  source_ref: {
    kind: "manual",
    ref_id: "web-console",
    excerpt: null,
  },
  confidence: 0.8,
  scope_hint: "global",
};

const renderValue = (value: unknown) => {
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
};

export const MemoryPage = () => {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [scope, setScope] = useState<Scope | "">("");
  const [proposal, setProposal] = useState<ProposalCreateRequest>(defaultProposal);
  const [rejectReasons, setRejectReasons] = useState<RejectReasonMap>({});
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposalsError, setProposalsError] = useState<string | null>(null);

  const fetchParams = useMemo(
    () => ({
      scope: scope || undefined,
      status: status === "all" ? undefined : status,
    }),
    [scope, status]
  );

  const loadFacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchFacts(fetchParams);
      setFacts(response.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load facts");
    } finally {
      setLoading(false);
    }
  }, [fetchParams]);

  const loadProposals = useCallback(async () => {
    try {
      setProposalsError(null);
      const response = await fetchProposals({ status: "pending" });
      setProposals(response.items);
      setRejectReasons((current) => {
        const next: RejectReasonMap = {};
        response.items.forEach((item) => {
          if (current[item.id]) {
            next[item.id] = current[item.id];
          }
        });
        return next;
      });
    } catch (err) {
      if (err instanceof Error) {
        const requestUrl = (err as Error & { requestUrl?: string }).requestUrl;
        if (requestUrl) {
          console.log(`Proposals request failed: ${requestUrl}`);
        }
        setProposalsError(err.message);
      } else {
        setProposalsError("Failed to load proposals");
      }
    }
  }, []);

  const sortedFacts = useMemo(() => {
    return [...facts].sort((a, b) => {
      const keyCompare = a.key.localeCompare(b.key);
      if (keyCompare !== 0) {
        return keyCompare;
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [facts]);

  useEffect(() => {
    void loadFacts();
    void loadProposals();
  }, [loadFacts, loadProposals]);

  const handleAddProposal = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!proposal.payload.key.trim() || !String(proposal.payload.value).trim()) {
      setError("Key and value are required.");
      return;
    }
    setError(null);
    try {
      await proposeFact(proposal);
      setProposal(defaultProposal);
      await loadFacts();
      await loadProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add proposal");
    }
  };

  const handleRevokeFact = async (id: string) => {
    setError(null);
    try {
      await revokeFact(id);
      await loadFacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke fact");
    }
  };

  const handleArchiveFact = async (id: string) => {
    setError(null);
    try {
      await archiveFact(id);
      await loadFacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to archive fact");
    }
  };

  const handleReactivateFact = async (id: string) => {
    setError(null);
    try {
      await reactivateFact(id);
      await loadFacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reactivate fact");
    }
  };

  const handleAcceptProposal = async (id: string) => {
    setError(null);
    try {
      await acceptProposal(id);
      await loadFacts();
      await loadProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept proposal");
    }
  };

  const handleRejectProposal = async (id: string) => {
    setError(null);
    try {
      await rejectProposal(id, rejectReasons[id]?.trim() || undefined);
      setRejectReasons((current) => ({ ...current, [id]: "" }));
      await loadProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reject proposal");
    }
  };

  const handleExpireProposal = async (id: string) => {
    setError(null);
    try {
      await expireProposal(id);
      await loadProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to expire proposal");
    }
  };

  return (
    <section>
      <div
        role="status"
        style={{
          padding: "14px 18px",
          marginBottom: "20px",
          background: "#fef3c7",
          border: "1px solid #f59e0b",
          borderRadius: "8px",
          color: "#92400e",
          fontSize: "14px",
        }}
      >
        此页面将废弃，请使用右上角 <strong>Memory 管理</strong>（脑形图标）打开 Drawer 进行事实与提案管理。
      </div>
      <h2>Memory</h2>
      <p>Review proposals and manage long-term facts stored for the assistant.</p>

      {error ? <p role="alert">{error}</p> : null}
      {loading ? <p>Loading…</p> : null}

      <h3>Proposals</h3>
      <p>Review incoming memory proposals before accepting them into active facts.</p>
      <button type="button" onClick={() => void loadProposals()}>
        Refresh Proposals
      </button>
      {proposalsError ? <p role="alert">{proposalsError}</p> : null}
      <table>
        <thead>
          <tr>
            <th>Proposal ID</th>
            <th>Key</th>
            <th>Value</th>
            <th>Confidence</th>
            <th>Scope Hint</th>
            <th>Source</th>
            <th>Status</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {proposalsError ? (
            <tr>
              <td colSpan={9}>Unable to load proposals.</td>
            </tr>
          ) : proposals.length === 0 ? (
            <tr>
              <td colSpan={9}>No pending proposals.</td>
            </tr>
          ) : (
            proposals.map((p) => (
              <tr key={p.id}>
                <td>{p.id.slice(0, 8)}...</td>
                <td>{p.payload.key}</td>
                <td>
                  {typeof p.payload.value === "string" ? (
                    renderValue(p.payload.value)
                  ) : (
                    <pre>{renderValue(p.payload.value)}</pre>
                  )}
                </td>
                <td>{p.confidence?.toFixed(2) ?? "—"}</td>
                <td>{p.scope_hint ?? "—"}</td>
                <td>
                  {p.source_ref.kind}: {p.source_ref.ref_id}
                </td>
                <td>{p.status}</td>
                <td>{new Date(p.created_at).toLocaleString()}</td>
                <td>
                  <input
                    type="text"
                    placeholder="Reject reason (optional)"
                    value={rejectReasons[p.id] ?? ""}
                    onChange={(event) =>
                      setRejectReasons((current) => ({
                        ...current,
                        [p.id]: event.target.value,
                      }))
                    }
                  />
                  <div>
                    <button type="button" onClick={() => void handleAcceptProposal(p.id)}>
                      Accept
                    </button>
                    <button type="button" onClick={() => void handleRejectProposal(p.id)}>
                      Reject
                    </button>
                    <button type="button" onClick={() => void handleExpireProposal(p.id)}>
                      Expire
                    </button>
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <h3>Facts</h3>
      <div>
        <label>
          Scope
          <select value={scope} onChange={(event) => setScope(event.target.value as Scope | "")}>
            <option value="">All</option>
            {SCOPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>

        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
            {STATUS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <button type="button" onClick={() => void loadFacts()} disabled={loading}>
          Refresh
        </button>
      </div>

      <form onSubmit={handleAddProposal}>
        <h3>Add Proposal</h3>
        <label>
          Key
          <input
            type="text"
            value={proposal.payload.key}
            onChange={(event) =>
              setProposal({
                ...proposal,
                payload: { ...proposal.payload, key: event.target.value },
              })
            }
          />
        </label>
        <label>
          Value
          <input
            type="text"
            value={String(proposal.payload.value)}
            onChange={(event) =>
              setProposal({
                ...proposal,
                payload: { ...proposal.payload, value: event.target.value },
              })
            }
          />
        </label>
        <label>
          Confidence
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={proposal.confidence ?? 0.8}
            onChange={(event) =>
              setProposal({
                ...proposal,
                confidence: Number.parseFloat(event.target.value || "0"),
              })
            }
          />
        </label>
        <label>
          Scope Hint
          <select
            value={proposal.scope_hint ?? "global"}
            onChange={(event) =>
              setProposal({
                ...proposal,
                scope_hint: event.target.value as Scope,
              })
            }
          >
            {SCOPE_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={loading}>
          Add Proposal
        </button>
      </form>

      <table>
        <thead>
          <tr>
            <th>Key</th>
            <th>Value</th>
            <th>Scope</th>
            <th>Status</th>
            <th>Version</th>
            <th>Source</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sortedFacts.length === 0 ? (
            <tr>
              <td colSpan={8}>No facts yet.</td>
            </tr>
          ) : (
            sortedFacts.map((fact) => (
              <tr key={fact.id} onClick={() => setSelectedFactId(fact.id)}>
                <td>{fact.key}</td>
                <td>
                  {typeof fact.value === "string" ? (
                    renderValue(fact.value)
                  ) : (
                    <pre>{renderValue(fact.value)}</pre>
                  )}
                </td>
                <td>{fact.scope}</td>
                <td>{fact.status}</td>
                <td>{fact.version}</td>
                <td>
                  {fact.source_ref.kind}: {fact.source_ref.ref_id}
                </td>
                <td>{new Date(fact.created_at).toLocaleString()}</td>
                <td>
                  <div>
                    {fact.status === "active" ? (
                      <>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleRevokeFact(fact.id);
                          }}
                          disabled={loading}
                        >
                          Revoke
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleArchiveFact(fact.id);
                          }}
                          disabled={loading}
                        >
                          Archive
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleReactivateFact(fact.id);
                        }}
                        disabled={loading}
                      >
                        Reactivate
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <FactDetailsDrawer
        factId={selectedFactId}
        onClose={() => setSelectedFactId(null)}
      />
    </section>
  );
};
