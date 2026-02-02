export type FactStatus = "active" | "revoked" | "archived";
export type ProposalStatus = "pending" | "accepted" | "rejected" | "expired";
export type Scope = "global" | "project" | "session";
export type SourceKind = "chat" | "run" | "connector" | "manual";
export type ConflictStrategy = "overwrite_latest" | "keep_both";

export type SourceRef = {
  kind: SourceKind;
  ref_id: string;
  excerpt: string | null;
};

export type ProposalPayload = {
  key: string;
  value: unknown;
  tags: string[];
  ttl_seconds: number | null;
};

export type Proposal = {
  id: string;
  payload: ProposalPayload;
  status: ProposalStatus;
  reason: string | null;
  confidence: number | null;
  scope_hint: Scope | null;
  source_ref: SourceRef;
  created_at: string;
  updated_at: string;
};

export type Fact = {
  id: string;
  key: string;
  value: unknown;
  status: FactStatus;
  scope: Scope;
  project_id: string | null;
  session_id: string | null;
  source_ref: SourceRef;
  confidence: number | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: string;
  type: string;
  actor: {
    kind: string;
    id: string;
  };
  target: {
    type: string;
    id: string;
  };
  request_id: string | null;
  diff: {
    before: unknown;
    after: unknown;
  } | null;
  created_at: string;
};

export type ProposalCreateRequest = {
  payload: ProposalPayload;
  source_ref: SourceRef;
  reason?: string | null;
  confidence?: number | null;
  scope_hint?: Scope | null;
};

export type ProposalAcceptRequest = {
  strategy?: ConflictStrategy | null;
  scope?: Scope | null;
  project_id?: string | null;
  session_id?: string | null;
};

export type FetchFactsParams = {
  scope?: Scope;
  project_id?: string;
  session_id?: string;
  status?: FactStatus | "all";
};

export type FetchProposalsParams = {
  status?: ProposalStatus | "all";
  scope_hint?: Scope;
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
  items: Fact[];
};

type FetchProposalsResponse = {
  items: Proposal[];
};

type FetchAuditEventsResponse = {
  items: AuditEvent[];
};

export type ProposeFactResponse = {
  status: ProposalStatus;
  proposal: Proposal;
  fact: Fact | null;
};

export type AcceptProposalResponse = {
  proposal: Proposal;
  fact: Fact;
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
    scope: params.scope,
    project_id: params.project_id,
    session_id: params.session_id,
    status: params.status,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch facts", response));
  }
  return await parseJson<FetchFactsResponse>(response);
};

export const getFact = async (factId: string): Promise<Fact> => {
  const url = buildUrl(`/memory/facts/${factId}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch fact", response));
  }
  return await parseJson<Fact>(response);
};

export const getFactByKey = async (
  key: string,
  scope: Scope,
  projectId?: string,
  sessionId?: string
): Promise<Fact> => {
  const url = buildUrl(`/memory/facts/key/${encodeURIComponent(key)}`, {
    scope,
    project_id: projectId,
    session_id: sessionId,
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch fact by key", response));
  }
  return await parseJson<Fact>(response);
};

export const proposeFact = async (request: ProposalCreateRequest): Promise<ProposeFactResponse> => {
  const url = buildUrl("/memory/proposals");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to propose fact", response));
  }
  return await parseJson<ProposeFactResponse>(response);
};

export const fetchProposals = async (params: FetchProposalsParams = {}): Promise<FetchProposalsResponse> => {
  const url = buildUrl("/memory/proposals", {
    status: params.status,
    scope_hint: params.scope_hint,
  });
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

export const getProposal = async (proposalId: string): Promise<Proposal> => {
  const url = buildUrl(`/memory/proposals/${proposalId}`);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch proposal", response));
  }
  return await parseJson<Proposal>(response);
};

export const acceptProposal = async (
  id: string,
  request?: ProposalAcceptRequest
): Promise<AcceptProposalResponse> => {
  const url = buildUrl(`/memory/proposals/${id}/accept`);
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request || {}),
  });
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

export const expireProposal = async (id: string): Promise<Proposal> => {
  const url = buildUrl(`/memory/proposals/${id}/expire`);
  const response = await fetch(url, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to expire proposal", response));
  }
  return await parseJson<Proposal>(response);
};

export const revokeFact = async (id: string): Promise<Fact> => {
  const url = buildUrl(`/memory/facts/${id}/revoke`);
  const response = await fetch(url, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to revoke fact", response));
  }
  return await parseJson<Fact>(response);
};

export const archiveFact = async (id: string): Promise<Fact> => {
  const url = buildUrl(`/memory/facts/${id}/archive`);
  const response = await fetch(url, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to archive fact", response));
  }
  return await parseJson<Fact>(response);
};

export const reactivateFact = async (id: string): Promise<Fact> => {
  const url = buildUrl(`/memory/facts/${id}/reactivate`);
  const response = await fetch(url, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to reactivate fact", response));
  }
  return await parseJson<Fact>(response);
};

export const fetchAuditEvents = async (params: {
  target_type?: string;
  target_id?: string;
  event_type?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<FetchAuditEventsResponse> => {
  const url = buildUrl("/memory/audit", {
    target_type: params.target_type,
    target_id: params.target_id,
    event_type: params.event_type,
    limit: params.limit?.toString(),
    offset: params.offset?.toString(),
  });
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to fetch audit events", response));
  }
  return await parseJson<FetchAuditEventsResponse>(response);
};

export const checkExpiredProposals = async (): Promise<{ expired_ids: string[] }> => {
  const url = buildUrl("/memory/maintenance/check-expired");
  const response = await fetch(url, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await buildErrorMessage("Failed to check expired proposals", response));
  }
  return await parseJson<{ expired_ids: string[] }>(response);
};
