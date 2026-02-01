export type FactStatus = "ACTIVE" | "OVERRIDDEN" | "RETRACTED";

export type FactRecord = {
  id: string;
  subject: string;
  predicate: string;
  object: unknown;
  confidence: number;
  source: Record<string, unknown>;
  status: FactStatus;
  created_at: number;
  seq: number;
  overrides?: string | null;
  retracted_reason?: string | null;
};

export type FactCandidate = {
  subject: string;
  predicate: string;
  object: unknown;
  confidence: number;
  source: Record<string, unknown>;
};

export type FetchFactsParams = {
  subject?: string;
  status?: "ALL" | "ACTIVE" | "OVERRIDDEN" | "RETRACTED";
  predicate_contains?: string;
};

const baseUrl = import.meta.env.VITE_CORE_API_URL ?? "";

const joinBaseUrl = (base: string, path: string) => {
  if (!base) {
    return path.startsWith("/") ? path : `/${path}`;
  }
  const trimmedBase = base.replace(/\/+$/, "");
  const trimmedPath = path.startsWith("/") ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
};

const buildUrl = (path: string, params?: Record<string, string | undefined>) => {
  const joined = joinBaseUrl(baseUrl, path);
  const url = new URL(joined, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value) {
        url.searchParams.set(key, value);
      }
    });
  }
  return url.toString();
};

export const fetchFacts = async (params: FetchFactsParams = {}) => {
  const url = buildUrl("/memory/facts", {
    subject: params.subject,
    status: params.status,
    predicate_contains: params.predicate_contains,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch facts (${response.status})`);
  }
  return (await response.json()) as { items: FactRecord[] };
};

export const proposeFact = async (candidate: FactCandidate) => {
  const url = buildUrl("/memory/facts/propose");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(candidate),
  });
  if (!response.ok) {
    throw new Error(`Failed to propose fact (${response.status})`);
  }
  return (await response.json()) as FactRecord;
};

export const retractFact = async (id: string, reason: string) => {
  const url = buildUrl(`/memory/facts/${id}/retract`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`Failed to retract fact (${response.status})`);
  }
  return (await response.json()) as FactRecord;
};

export const fetchFactChain = async (id: string, maxDepth = 20) => {
  const url = buildUrl(`/memory/facts/${id}/chain`, {
    max_depth: String(maxDepth),
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch fact chain (${response.status})`);
  }
  return (await response.json()) as {
    root_id: string;
    items: FactRecord[];
    truncated: boolean;
  };
};
