export type FactStatus = "ACTIVE" | "RETRACTED";
export type ProposalStatus = "PENDING" | "ACCEPTED" | "REJECTED";

export type FactRecord = {
  id: string;
  subject: string;
  predicate: string;
  object: unknown;
  confidence: number;
  source: Record<string, unknown> | null;
  status: FactStatus;
  created_at: number;
  seq: number;
  overrides: string | null;
  retracted_reason: string | null;
};

export type FactCandidate = {
  subject: string;
  predicate: string;
  object: unknown;
  confidence: number;
  source: Record<string, unknown>;
};

export type Proposal = {
  id: string;
  candidate: FactCandidate;
  source_note: string;
  reason: string | null;
  status: ProposalStatus;
  created_at: number;
  resolved_at: number | null;
  resolved_reason: string | null;
};

export type FetchFactsParams = {
  subject?: string;
  status?: "ALL" | "ACTIVE" | "RETRACTED";
  predicate_contains?: string;
};

const baseUrl = import.meta.env.VITE_CORE_API_URL ?? "http://localhost:8000";

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

type FetchFactsResponse = {
  items: FactRecord[];
};

type FetchProposalsResponse = {
  items: Proposal[];
};

type FactChainResponse = {
  root_id: string;
  items: FactRecord[];
  truncated: boolean;
};

export type ProposeFactResponse = {
  status: ProposalStatus;
  proposal: Proposal;
  record: FactRecord | null;
};

const parseJson = async <T>(response: Response): Promise<T> => {
  try {
    return (await response.json()) as T;
  } catch (error) {
    throw new Error(
      error instanceof Error ? `Failed to parse response: ${error.message}` : "Failed to parse response"
    );
  }
};

export const fetchFacts = async (params: FetchFactsParams = {}): Promise<FetchFactsResponse> => {
  const url = buildUrl("/memory/facts", {
    subject: params.subject,
    status: params.status,
    predicate_contains: params.predicate_contains,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch facts (${response.status})`);
  }
  return await parseJson<FetchFactsResponse>(response);
};

export const proposeFact = async (candidate: FactCandidate): Promise<ProposeFactResponse> => {
  const url = buildUrl("/memory/facts/propose");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(candidate),
  });
  if (!response.ok) {
    throw new Error(`Failed to propose fact (${response.status})`);
  }
  return await parseJson<ProposeFactResponse>(response);
};

export const fetchProposals = async (status?: ProposalStatus | "ALL"): Promise<FetchProposalsResponse> => {
  const url = buildUrl("/memory/proposals", { status });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch proposals (${response.status})`);
  }
  return await parseJson<FetchProposalsResponse>(response);
};

export const acceptProposal = async (id: string): Promise<FactRecord> => {
  const url = buildUrl(`/memory/proposals/${id}/accept`);
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to accept proposal (${response.status})`);
  }
  return await parseJson<FactRecord>(response);
};

export const rejectProposal = async (id: string, reason?: string): Promise<Proposal> => {
  const url = buildUrl(`/memory/proposals/${id}/reject`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`Failed to reject proposal (${response.status})`);
  }
  return await parseJson<Proposal>(response);
};

export const retractFact = async (id: string, reason: string): Promise<FactRecord> => {
  const url = buildUrl(`/memory/facts/${id}/retract`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`Failed to retract fact (${response.status})`);
  }
  return await parseJson<FactRecord>(response);
};

export const fetchFactChain = async (
  id: string,
  maxDepth = 20,
  signal?: AbortSignal
): Promise<FactChainResponse> => {
  const url = buildUrl(`/memory/facts/${id}/chain`, {
    max_depth: String(maxDepth),
  });
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Failed to fetch fact chain (${response.status})`);
  }
  return await parseJson<FactChainResponse>(response);
};
