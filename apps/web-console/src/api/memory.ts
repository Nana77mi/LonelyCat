export type FactStatus = "ACTIVE" | "OVERRIDDEN" | "RETRACTED";
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
  status?: "ALL" | "ACTIVE" | "OVERRIDDEN" | "RETRACTED";
  predicate_contains?: string;
};

// Priority: VITE_CORE_API_URL > VITE_API_BASE_URL > default "/api"
const baseUrl =
  import.meta.env.VITE_CORE_API_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  "/api";

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
  // If baseUrl is absolute (http:// or https://), use it directly
  // Otherwise, treat as relative path (will use window.location.origin)
  const url = new URL(joined, baseUrl.startsWith("http") ? undefined : window.location.origin);
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

const readErrorBody = async (response: Response): Promise<string> => {
  const contentType = response.headers.get("content-type") ?? "";
  let body = "";
  try {
    if (contentType.includes("application/json")) {
      const data = await response.json();
      body = JSON.stringify(data);
    } else {
      body = await response.text();
    }
  } catch {
    body = "";
  }
  const trimmed = body.replace(/\s+/g, " ").trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.length > 200 ? `${trimmed.slice(0, 200)}…` : trimmed;
};

const buildErrorMessage = async (prefix: string, response: Response): Promise<string> => {
  const detail = await readErrorBody(response);
  if (!detail) {
    return `${prefix} (${response.status})`;
  }
  return `${prefix} (${response.status}): ${detail}`;
};

export const fetchFacts = async (params: FetchFactsParams = {}): Promise<FetchFactsResponse> => {
  const url = buildUrl("/memory/facts", {
    subject: params.subject,
    status: params.status,
    predicate_contains: params.predicate_contains,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch facts", response));
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
    throw new Error(await buildErrorMessage("Failed to propose fact", response));
  }
  return await parseJson<ProposeFactResponse>(response);
};

export const fetchProposals = async (status?: ProposalStatus | "ALL"): Promise<FetchProposalsResponse> => {
  const url = buildUrl("/memory/proposals", { status });
  const response = await fetch(url);
  if (!response.ok) {
    const detail = await readErrorBody(response);
    const message = `Failed to fetch proposals: ${response.status} ${url}${detail ? ` ${detail}` : ""}`;
    const error = new Error(message) as Error & { requestUrl?: string };
    error.requestUrl = url;
    throw error;
  }
  return await parseJson<FetchProposalsResponse>(response);
};

export type AcceptProposalResponse = {
  proposal: Proposal;
  record: FactRecord;
};

export const acceptProposal = async (id: string): Promise<AcceptProposalResponse> => {
  const url = buildUrl(`/memory/proposals/${id}/accept`);
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to accept proposal", response));
  }
  return await parseJson<AcceptProposalResponse>(response);
};

export const rejectProposal = async (id: string, reason?: string): Promise<Proposal> => {
  const url = buildUrl(`/memory/proposals/${id}/reject`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to reject proposal", response));
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
    throw new Error(await buildErrorMessage("Failed to retract fact", response));
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
    throw new Error(await buildErrorMessage("Failed to fetch fact chain", response));
  }
  return await parseJson<FactChainResponse>(response);
};
