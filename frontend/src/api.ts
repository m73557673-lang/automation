export type Incident = {
  id: number;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  status: "open" | "investigating" | "mitigated" | "resolved";
  service_id: number;
  service: string;
  summary: string;
  source: string;
  is_synthetic: boolean;
  created_at: string;
  resolved_at: string | null;
};

export type Evidence = {
  id: number;
  incident_id: number;
  source_type: string;
  source_id: number;
  relevance: number;
  kind: string;
  source: string;
  message: string;
  observed_at: string;
  confidence: number | null;
  created_at: string;
};

export type Metric = {
  id: number;
  service_id: number;
  timestamp: string;
  metric_name: string;
  value: number;
};

export type Runbook = {
  id: number;
  title: string;
  service: string;
  content: string;
  tags: string[];
};

export type KnowledgeBaseStatus = {
  document_count: number;
  indexed_document_count: number;
  chunk_count: number;
  synthetic_document_count: number;
  retrieval_mode: "keyword_bm25" | "semantic";
  supported_extensions: string[];
};

export type KnowledgeBaseDocument = {
  id: number;
  title: string;
  source: string;
  original_filename: string;
  approval_status: string;
  approved_by: string;
  is_synthetic: boolean;
  indexing_status: string;
  indexed_chunk_count: number;
  indexed_at: string | null;
  created_at: string;
  excerpt: string;
  source_metadata: Record<string, unknown>;
};

export type KnowledgePassage = {
  document_id: number;
  title: string;
  source: string;
  excerpt: string;
  chunk_index: number;
  score?: number;
  is_synthetic: boolean;
  approval_status: string;
};

export type KnowledgeSearchResponse = {
  query: string;
  retrieval_mode: "keyword_bm25" | "semantic";
  items: KnowledgePassage[];
};

export type KnowledgeDocumentPage = {
  items: KnowledgeBaseDocument[];
  total: number;
  skip: number;
  limit: number;
};

export type Service = {
  id: number;
  name: string;
  environment: string;
  owner: string;
  status: string;
  latency_ms: number | null;
  error_rate: number | null;
  request_rate: number | null;
  latency_history: number[];
  error_history: number[];
  is_synthetic: boolean;
};

export type Recommendation = {
  id: number;
  incident_id: number;
  action: string;
  risk: "low" | "medium" | "high";
  confidence: number;
  created_at: string;
};

export type Remediation = {
  id: number;
  incident_id: number;
  action: string;
  state: "approved" | "validated" | "rejected";
  created_at: string;
  approved_at: string | null;
  validation_passed: boolean | null;
  result: string | null;
};

export type Postmortem = {
  id: number;
  incident_id: number;
  title: string;
  summary: string;
  root_cause: string;
  impact: string;
  prevention: string;
  created_at: string;
  is_synthetic: boolean;
};

export type Dashboard = {
  active_incidents: number;
  critical_incidents: number;
  affected_services: number;
  recovery_checks_passed: number;
  incidents: Incident[];
  activity: { id: number; incident_id: number; title: string; detail: string; occurred_at: string }[];
  services: Service[];
  synthetic: boolean;
};

export type CheckoutMetricPoint = {
  timestamp: string;
  latency_ms: number | null;
  error_rate_percent: number | null;
  request_volume_rps: number | null;
  db_pool_utilization_percent: number | null;
  db_pool_size: number | null;
};

export type CheckoutServiceMetrics = {
  service_id: number;
  name: string;
  status: string;
  latency_ms: number | null;
  error_rate_percent: number | null;
  request_volume_rps: number | null;
  db_pool_utilization_percent: number | null;
  db_pool_size: number | null;
  history: CheckoutMetricPoint[];
  is_synthetic: boolean;
};

export type CheckoutSimulationMetrics = {
  state: "healthy" | "incident";
  run_number: number;
  updated_at: string;
  services: CheckoutServiceMetrics[];
  is_synthetic: boolean;
};

export type CheckoutServiceHealth = {
  name: string;
  status: string;
  summary: string;
  latency_ms: number | null;
  error_rate_percent: number | null;
  db_pool_utilization_percent: number | null;
  is_synthetic: boolean;
};

export type CheckoutSimulationHealth = {
  state: "healthy" | "incident";
  overall_status: "healthy" | "degraded";
  services: CheckoutServiceHealth[];
  is_synthetic: boolean;
};

export type CheckoutSimulationEvent = {
  id: string;
  timestamp: string;
  kind: "log" | "deployment";
  level: string;
  service: string;
  title: string;
  detail: string;
  is_synthetic: boolean;
};

export type CheckoutSimulationEvents = {
  items: CheckoutSimulationEvent[];
  is_synthetic: boolean;
};

export type Investigation = {
  incident: Incident;
  evidence: Evidence[];
  metrics: Metric[];
  runbooks: Runbook[];
  recommendation: Recommendation | null;
  remediation: Remediation | null;
  postmortem: Postmortem | null;
};

export type AIInvestigationHypothesis = {
  key: string;
  title: string;
  explanation: string;
  test: string;
  evidence_ids: string[];
  supporting_evidence_ids?: string[];
  contradicting_evidence_ids?: string[];
  missing_evidence?: string[];
  confidence_score: number;
  confidence_label: string;
  uncertainty: string;
  origin: string;
  ai_selected?: boolean;
  ai_evidence_ids?: string[];
};

export type AIInvestigationEvidence = {
  id: string;
  source_ref?: string;
  source_type?: string;
  source: string;
  kind: string;
  text: string;
  excerpt?: string;
  value?: number | string | null;
  observed_at: string | null;
  record_class?: string;
};

export type StoredEvidenceDetail = {
  id: string;
  source_type: string;
  source_reference: string;
  timestamp: string | null;
  source: string;
  excerpt: string;
  value: number | string | null;
};

export type AIInvestigation = {
  id: number;
  created_at: string;
  scope: string;
  title: string;
  service: string;
  scenario_status: string;
  run_number?: number;
  is_synthetic: boolean;
  provider_status: "not_configured" | "missing_credentials" | "provider_error" | "invalid_response" | "available";
  provider_message: string;
  retrieval_mode: string;
  retrieval_warning: string | null;
  agents: {
    triage: { severity: string; scope: string; evidence_ids: string[]; note: string; source: string };
    log_analysis: { patterns: { code: string; evidence_ids: string[] }[]; source: string };
    change_analysis: { relationship: string; evidence_ids: string[]; note: string; source: string };
    root_cause: { hypotheses: AIInvestigationHypothesis[]; source: string };
    knowledge: { retrieval_mode: string; warning: string | null; items: KnowledgePassage[]; source: string };
    remediation: { plan_code: string; plan: string; risk: string; evidence_ids: string[]; advisory_only: boolean; source: string };
    validation: {
      assessment: string;
      detail: string;
      evidence_ids: string[];
      observations?: { metric: string; before: number; after: number; change: string; evidence_ids: string[] }[];
      source: string;
    };
    postmortem: { summary: string; impact: string; timeline: string; prevention: string; evidence_ids: string[]; source: string; review_required?: boolean };
  };
  observed_facts: {
    id: string;
    statement: string;
    evidence_ids: string[];
    source: string;
    kind: string;
    value: unknown;
  }[];
  support_score_method: string;
  support_score_note: string;
  evidence: AIInvestigationEvidence[];
  safety: string;
};

type Page<T> = { items: T[]; total: number; skip: number; limit: number };

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.body instanceof FormData
    ? { ...init.headers }
    : { "Content-Type": "application/json", ...init?.headers };
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string"
      ? body.detail
      : Array.isArray(body?.errors)
        ? body.errors.map((item: { message?: string }) => item.message).filter(Boolean).join(" ")
        : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

async function pageItems<T>(path: string): Promise<T[]> {
  const page = await request<Page<T>>(path);
  return page.items;
}

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(path);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

function toRemediation(action: {
  id: number;
  incident_id: number;
  action: string;
  status: string;
  result: string | null;
  created_at: string;
  updated_at: string;
}): Remediation {
  return {
    id: action.id,
    incident_id: action.incident_id,
    action: action.action,
    state: action.status === "simulated_validated" ? "validated" : action.status as Remediation["state"],
    created_at: action.created_at,
    approved_at: action.status === "approved" || action.status === "simulated_validated" ? action.updated_at : null,
    validation_passed: action.status === "simulated_validated" ? true : null,
    result: action.result,
  };
}

export const api = {
  health: () => request<{ status: string; database: string }>("/health"),
  aiInvestigation: (id: number) => optional<AIInvestigation>(`/incidents/${id}/ai-investigation`),
  incidentAIEvidence: (id: number, ref: string) =>
    request<StoredEvidenceDetail>(`/incidents/${id}/ai-evidence?ref=${encodeURIComponent(ref)}`),
  runAIInvestigation: (id: number) =>
    request<AIInvestigation>(`/incidents/${id}/ai-investigation`, { method: "POST" }),
  checkoutAIInvestigation: () => optional<AIInvestigation>("/simulation/ai-investigation"),
  checkoutAIEvidence: (ref: string) =>
    request<StoredEvidenceDetail>(`/simulation/ai-evidence?ref=${encodeURIComponent(ref)}`),
  runCheckoutAIInvestigation: () =>
    request<AIInvestigation>("/simulation/ai-investigation", { method: "POST" }),
  checkoutSimulation: () => request<CheckoutSimulationMetrics>("/simulation/metrics"),
  checkoutSimulationHealth: () => request<CheckoutSimulationHealth>("/simulation/health"),
  checkoutSimulationEvents: () => request<CheckoutSimulationEvents>("/simulation/events"),
  startCheckoutSimulation: () =>
    request<CheckoutSimulationMetrics>("/simulation/start", { method: "POST" }),
  resetCheckoutSimulation: () =>
    request<CheckoutSimulationMetrics>("/simulation/reset", { method: "POST" }),
  dashboard: () => request<Dashboard>("/dashboard"),
  incidents: () => pageItems<Incident>("/incidents?skip=0&limit=100"),
  createIncident: (data: {
    title: string;
    severity: Incident["severity"];
    service_id: number;
    summary: string;
  }) => request<Incident>("/incidents", { method: "POST", body: JSON.stringify(data) }),
  investigation: async (id: number): Promise<Investigation> => {
    const incident = await request<Incident>(`/incidents/${id}`);
    const query = new URLSearchParams({ q: incident.service, skip: "0", limit: "100" });
    const [evidence, metrics, runbooks, recommendation, actions, postmortem] = await Promise.all([
      pageItems<Evidence>(`/incidents/${id}/evidence?skip=0&limit=100`),
      pageItems<Metric>(`/incidents/${id}/metrics?skip=0&limit=100`),
      pageItems<Runbook>(`/knowledge?${query.toString()}`),
      optional<Recommendation>(`/incidents/${id}/recommendation`),
      pageItems<{
        id: number;
        incident_id: number;
        action: string;
        status: string;
        result: string | null;
        created_at: string;
        updated_at: string;
      }>(`/incidents/${id}/actions?skip=0&limit=100`),
      optional<Postmortem>(`/incidents/${id}/postmortem`),
    ]);
    return {
      incident,
      evidence,
      metrics,
      runbooks,
      recommendation,
      remediation: actions[0] ? toRemediation(actions[0]) : null,
      postmortem,
    };
  },
  services: () => pageItems<Service>("/services?skip=0&limit=100"),
  knowledge: (query: string) => pageItems<Runbook>(`/knowledge?q=${encodeURIComponent(query)}&skip=0&limit=100`),
  knowledgeBaseStatus: () => request<KnowledgeBaseStatus>("/knowledge/status"),
  knowledgeDocuments: () => request<KnowledgeDocumentPage>("/knowledge/documents?skip=0&limit=100"),
  knowledgeDocument: (id: number) => request<KnowledgeBaseDocument>(`/knowledge/documents/${id}`),
  knowledgePassage: (documentId: number, chunkIndex: number) =>
    request<KnowledgePassage>(`/knowledge/documents/${documentId}/chunks/${chunkIndex}`),
  searchKnowledgePassages: (query: string, limit = 10) =>
    request<KnowledgeSearchResponse>(`/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  uploadKnowledgeDocument: (file: File, metadata: {
    title: string;
    source: string;
    approvedBy: string;
  }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", metadata.title);
    form.append("source", metadata.source);
    form.append("approved_by", metadata.approvedBy);
    form.append("approved", "true");
    return request<KnowledgeBaseDocument>("/knowledge/documents", {
      method: "POST",
      body: form,
    });
  },
  approveRemediation: (incidentId: number) =>
    request<Remediation>(`/incidents/${incidentId}/remediation/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: "On-call operator" }),
    }),
  rejectRemediation: (incidentId: number) =>
    request<Remediation>(`/incidents/${incidentId}/remediation/reject`, {
      method: "POST",
      body: JSON.stringify({ approved_by: "On-call operator" }),
    }),
  validateRecovery: (remediationId: number) =>
    request<Remediation>(`/remediations/${remediationId}/validate`, { method: "POST" }),
  postmortems: () => pageItems<Postmortem>("/postmortems?skip=0&limit=100"),
  generatePostmortem: (incidentId: number) =>
    request<Postmortem>(`/incidents/${incidentId}/postmortem/generate`, { method: "POST" }),
};