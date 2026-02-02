import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Proposal,
  Fact,
  acceptProposal,
  fetchFacts,
  fetchProposals,
  proposeFact,
  rejectProposal,
  revokeFact,
} from "../api/memory";
import { FactDetailsDrawer } from "./FactDetailsDrawer";
import "./SettingsPanel.css";

const STATUS_OPTIONS = ["all", "active", "revoked", "archived"] as const;

type StatusFilter = (typeof STATUS_OPTIONS)[number];

type RetractReasonMap = Record<string, string>;
type RejectReasonMap = Record<string, string>;

const defaultCandidate = {
  subject: "user",
  predicate: "",
  object: "",
  confidence: 0.8,
};

const renderObjectValue = (value: unknown) => {
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
};

type SettingsPanelProps = {
  isOpen: boolean;
  onClose: () => void;
};

export const SettingsPanel = ({ isOpen, onClose }: SettingsPanelProps) => {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [predicateContains, setPredicateContains] = useState("");
  const [candidate, setCandidate] = useState(defaultCandidate);
  const [retractReasons, setRetractReasons] = useState<RetractReasonMap>({});
  const [rejectReasons, setRejectReasons] = useState<RejectReasonMap>({});
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposalsError, setProposalsError] = useState<string | null>(null);

  const fetchParams = useMemo(
    () => ({
      scope: "global" as const,
      status: status === "all" ? undefined : status as "active" | "revoked" | "archived",
    }),
    [status]
  );

  const loadFacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchFacts(fetchParams);
      setFacts(response.items);
      setRetractReasons((current) => {
        const next: RetractReasonMap = {};
        response.items.forEach((item) => {
          if (current[item.id]) {
            next[item.id] = current[item.id];
          }
        });
        return next;
      });
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
      return b.version - a.version; // Sort by version descending
    });
  }, [facts]);

  useEffect(() => {
    if (isOpen) {
      void loadFacts();
      void loadProposals();
    }
  }, [isOpen, loadFacts, loadProposals]);

  const handleAddFact = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!candidate.predicate.trim() || !String(candidate.object).trim()) {
      setError("Predicate and object are required.");
      return;
    }
    setError(null);
    try {
      // Build key from subject.predicate format
      const key = candidate.subject === "user" 
        ? candidate.predicate.trim()
        : `${candidate.subject}.${candidate.predicate.trim()}`;
      
      await proposeFact({
        payload: {
          key,
          value: candidate.object,
          tags: [],
          ttl_seconds: null,
        },
        source_ref: {
          kind: "manual",
          ref_id: "web-console",
          excerpt: null,
        },
        confidence: candidate.confidence,
        scope_hint: "global",
      });
      setCandidate(defaultCandidate);
      await loadFacts();
      await loadProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add fact");
    }
  };

  const handleRetract = async (id: string) => {
    const reason = retractReasons[id] || "";
    if (!reason.trim()) {
      setError("Provide a reason to retract.");
      return;
    }
    setError(null);
    try {
      // Note: Backend API doesn't support reason parameter yet
      await revokeFact(id);
      setRetractReasons((current) => ({ ...current, [id]: "" }));
      await loadFacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retract fact");
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

  if (!isOpen) return null;

  return (
    <>
      <div className="settings-overlay" onClick={onClose} />
      <div className="settings-panel">
        <div className="settings-header">
          <h2>Memory 管理</h2>
          <button className="settings-close-btn" onClick={onClose} aria-label="关闭">
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

        <div className="settings-content">
          {error ? <div className="error-message" role="alert">{error}</div> : null}
          {loading ? <div className="loading-message">加载中…</div> : null}

          {/* Proposals Section */}
          <section className="settings-section">
            <div className="section-header">
              <h3>待审核提案</h3>
              <button type="button" className="refresh-btn" onClick={() => void loadProposals()}>
                刷新
              </button>
            </div>
            {proposalsError ? (
              <div className="error-message" role="alert">{proposalsError}</div>
            ) : null}
            {proposals.length === 0 ? (
              <div className="empty-message">暂无待审核提案</div>
            ) : (
              <div className="proposals-list">
                {proposals.map((proposal) => (
                  <div key={proposal.id} className="proposal-card">
                    <div className="proposal-header">
                      <span className="proposal-id">#{proposal.id.slice(0, 8)}</span>
                      <span className="proposal-status">{proposal.status}</span>
                    </div>
                    <div className="proposal-content">
                      <div className="proposal-field">
                        <strong>Key:</strong> {proposal.payload.key}
                      </div>
                      <div className="proposal-field">
                        <strong>Value:</strong>{" "}
                        {typeof proposal.payload.value === "string" ? (
                          proposal.payload.value
                        ) : (
                          <pre className="object-pre">{renderObjectValue(proposal.payload.value)}</pre>
                        )}
                      </div>
                      <div className="proposal-field">
                        <strong>Confidence:</strong> {proposal.confidence?.toFixed(2) ?? "—"}
                      </div>
                      <div className="proposal-field">
                        <strong>Source:</strong> {proposal.source_ref.kind}: {proposal.source_ref.ref_id}
                      </div>
                      <div className="proposal-field">
                        <strong>Created:</strong>{" "}
                        {new Date(proposal.created_at).toLocaleString()}
                      </div>
                    </div>
                    <div className="proposal-actions">
                      <input
                        type="text"
                        className="reason-input"
                        placeholder="拒绝原因（可选）"
                        value={rejectReasons[proposal.id] ?? ""}
                        onChange={(event) =>
                          setRejectReasons((current) => ({
                            ...current,
                            [proposal.id]: event.target.value,
                          }))
                        }
                      />
                      <div className="action-buttons">
                        <button
                          type="button"
                          className="accept-btn"
                          onClick={() => void handleAcceptProposal(proposal.id)}
                        >
                          接受
                        </button>
                        <button
                          type="button"
                          className="reject-btn"
                          onClick={() => void handleRejectProposal(proposal.id)}
                        >
                          拒绝
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Facts Section */}
          <section className="settings-section">
            <div className="section-header">
              <h3>事实记录</h3>
              <div className="filters">
                <select
                  className="filter-select"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as StatusFilter)}
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  className="filter-input"
                  value={predicateContains}
                  onChange={(event) => setPredicateContains(event.target.value)}
                  placeholder="搜索 predicate"
                />
                <button
                  type="button"
                  className="refresh-btn"
                  onClick={() => void loadFacts()}
                  disabled={loading}
                >
                  刷新
                </button>
              </div>
            </div>

            {/* Add Fact Form */}
            <form className="add-fact-form" onSubmit={handleAddFact}>
              <h4>添加事实</h4>
              <div className="form-row">
                <label>
                  Subject
                  <input
                    type="text"
                    value={candidate.subject}
                    onChange={(event) =>
                      setCandidate({ ...candidate, subject: event.target.value })
                    }
                  />
                </label>
                <label>
                  Predicate
                  <input
                    type="text"
                    value={candidate.predicate}
                    onChange={(event) =>
                      setCandidate({ ...candidate, predicate: event.target.value })
                    }
                  />
                </label>
              </div>
              <div className="form-row">
                <label>
                  Object
                  <input
                    type="text"
                    value={String(candidate.object)}
                    onChange={(event) =>
                      setCandidate({ ...candidate, object: event.target.value })
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
                    value={candidate.confidence}
                    onChange={(event) =>
                      setCandidate({
                        ...candidate,
                        confidence: Number.parseFloat(event.target.value || "0"),
                      })
                    }
                  />
                </label>
              </div>
              <button type="submit" className="submit-btn" disabled={loading}>
                添加事实
              </button>
            </form>

            {/* Facts List */}
            {sortedFacts.length === 0 ? (
              <div className="empty-message">暂无事实记录</div>
            ) : (
              <div className="facts-list">
                {sortedFacts.map((fact) => (
                  <div
                    key={fact.id}
                    className="fact-card"
                    onClick={() => setSelectedFactId(fact.id)}
                  >
                    <div className="fact-header">
                      <span className="fact-predicate">{fact.key}</span>
                      <span className={`fact-status ${fact.status.toLowerCase()}`}>
                        {fact.status}
                      </span>
                    </div>
                    <div className="fact-content">
                      {typeof fact.value === "string" ? (
                        fact.value
                      ) : (
                        <pre className="object-pre">{renderObjectValue(fact.value)}</pre>
                      )}
                    </div>
                    <div className="fact-meta">
                      <span>Version: {fact.version}</span>
                      <span>{new Date(fact.created_at).toLocaleString()}</span>
                    </div>
                    <div
                      className="fact-retract"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="text"
                        className="reason-input"
                        placeholder="撤回原因"
                        value={retractReasons[fact.id] ?? ""}
                        onChange={(event) => {
                          setRetractReasons((current) => ({
                            ...current,
                            [fact.id]: event.target.value,
                          }));
                        }}
                        disabled={fact.status === "revoked"}
                      />
                      <button
                        type="button"
                        className="retract-btn"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleRetract(fact.id);
                        }}
                        disabled={
                          fact.status === "revoked" ||
                          loading ||
                          !(retractReasons[fact.id] ?? "").trim()
                        }
                      >
                        撤回
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
      <FactDetailsDrawer
        factId={selectedFactId}
        onClose={() => setSelectedFactId(null)}
      />
    </>
  );
};
