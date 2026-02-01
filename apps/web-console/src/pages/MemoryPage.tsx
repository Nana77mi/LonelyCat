import { useCallback, useEffect, useMemo, useState } from "react";

import {
  FactRecord,
  fetchFacts,
  proposeFact,
  retractFact,
} from "../api/memory";
import { FactDetailsDrawer } from "../components/FactDetailsDrawer";

const STATUS_OPTIONS = ["ALL", "ACTIVE", "RETRACTED"] as const;

type StatusFilter = (typeof STATUS_OPTIONS)[number];

type RetractReasonMap = Record<string, string>;

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

export const MemoryPage = () => {
  const [facts, setFacts] = useState<FactRecord[]>([]);
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [predicateContains, setPredicateContains] = useState("");
  const [candidate, setCandidate] = useState(defaultCandidate);
  const [retractReasons, setRetractReasons] = useState<RetractReasonMap>({});
  const [selectedFactId, setSelectedFactId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchParams = useMemo(
    () => ({
      subject: candidate.subject || "user",
      status,
      predicate_contains: predicateContains || undefined,
    }),
    [candidate.subject, status, predicateContains]
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

  const sortedFacts = useMemo(() => {
    return [...facts].sort((a, b) => {
      const subjectCompare = a.subject.localeCompare(b.subject);
      if (subjectCompare !== 0) {
        return subjectCompare;
      }
      return a.seq - b.seq;
    });
  }, [facts]);

  useEffect(() => {
    void loadFacts();
  }, [loadFacts]);

  const handleAddFact = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!candidate.predicate.trim() || !String(candidate.object).trim()) {
      setError("Predicate and object are required.");
      return;
    }
    setError(null);
    try {
      await proposeFact({
        subject: candidate.subject || "user",
        predicate: candidate.predicate.trim(),
        object: candidate.object,
        confidence: candidate.confidence,
        source: { type: "web-console" },
      });
      setCandidate(defaultCandidate);
      await loadFacts();
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
      await retractFact(id, reason.trim());
      setRetractReasons((current) => ({ ...current, [id]: "" }));
      await loadFacts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retract fact");
    }
  };

  return (
    <section>
      <h2>Memory: Facts</h2>
      <p>View and manage long-term facts stored for the assistant.</p>

      <div>
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

        <label>
          Predicate contains
          <input
            type="text"
            value={predicateContains}
            onChange={(event) => setPredicateContains(event.target.value)}
            placeholder="search predicate"
          />
        </label>

        <button type="button" onClick={() => void loadFacts()} disabled={loading}>
          Refresh
        </button>
      </div>

      <form onSubmit={handleAddFact}>
        <h3>Add Fact</h3>
        <label>
          Subject
          <input
            type="text"
            value={candidate.subject}
            onChange={(event) => setCandidate({ ...candidate, subject: event.target.value })}
          />
        </label>
        <label>
          Predicate
          <input
            type="text"
            value={candidate.predicate}
            onChange={(event) => setCandidate({ ...candidate, predicate: event.target.value })}
          />
        </label>
        <label>
          Object
          <input
            type="text"
            value={String(candidate.object)}
            onChange={(event) => setCandidate({ ...candidate, object: event.target.value })}
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
        <button type="submit" disabled={loading}>
          Add Fact
        </button>
      </form>

      {error ? <p role="alert">{error}</p> : null}
      {loading ? <p>Loading…</p> : null}

      <table>
        <thead>
          <tr>
            <th>Predicate</th>
            <th>Object</th>
            <th>Status</th>
            <th>Seq</th>
            <th>Created</th>
            <th>Retract</th>
          </tr>
        </thead>
        <tbody>
          {sortedFacts.length === 0 ? (
            <tr>
              <td colSpan={6}>No facts yet.</td>
            </tr>
          ) : (
            sortedFacts.map((fact) => (
              <tr key={fact.id} onClick={() => setSelectedFactId(fact.id)}>
                <td>{fact.predicate}</td>
                <td>
                  {typeof fact.object === "string" ? (
                    renderObjectValue(fact.object)
                  ) : (
                    <pre>{renderObjectValue(fact.object)}</pre>
                  )}
                </td>
                <td>{fact.status}</td>
                <td>{fact.seq}</td>
                <td>{new Date(fact.created_at * 1000).toLocaleString()}</td>
                <td>
                  <input
                    type="text"
                    placeholder="Reason"
                    value={retractReasons[fact.id] ?? ""}
                    onChange={(event) => {
                      event.stopPropagation();
                      setRetractReasons((current) => ({
                        ...current,
                        [fact.id]: event.target.value,
                      }));
                    }}
                    onClick={(event) => event.stopPropagation()}
                    disabled={fact.status === "RETRACTED"}
                  />
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleRetract(fact.id);
                    }}
                    disabled={
                      fact.status === "RETRACTED" ||
                      loading ||
                      !(retractReasons[fact.id] ?? "").trim()
                    }
                  >
                    Retract
                  </button>
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
