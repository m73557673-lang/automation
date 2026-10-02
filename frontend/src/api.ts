export type Incident = {
  id: number;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  status: "open" | "investigating" | "mitigated" | "resolved";
  service: string;
  summary: string;
  source: string;
  is_synthetic: boolean;
  created_at: string;
};

export type Evidence = {
  id: number;
  incident_id: number;
  kind: string;
  source: string;
  message: string;
  observed_at: string;
  confidence: number | null;
};

export type Runbook = {
  id: number;
  title: string;
  service: string;
  content: string;
  tags: string[];
};

export type Service = {
  id: number;
  name: string;
  owner: string;
  tier: string;
  status: string;
  latency_ms: number;
  error_rate: number;
  request_rate: number;
  latency_history: number[];
  error_history: number[];
  is_synthetic: boolean;
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
  synthetic: true;
};

export type Investigation = {
  incident: Incident;
  evidence: Evidence[];
  runbooks: Runbook[];
  remediation: Remediation | null;
  postmortem: Postmortem | null;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; database: string }>("/health"),
  dashboard: () => request<Dashboard>("/dashboard"),
  incidents: () => request<Incident[]>("/incidents"),
  createIncident: (data: { title: string; severity: Incident["severity"]; service: string; summary: string }) =>
    request<Incident>("/incidents", { method: "POST", body: JSON.stringify(data) }),
  investigation: (id: number) => request<Investigation>(`/incidents/${id}/investigation`),
  services: () => request<Service[]>("/services"),
  knowledge: (query: string) => request<Runbook[]>(`/knowledge?q=${encodeURIComponent(query)}`),
  approveRemediation: (incidentId: number) =>
    request<Remediation>(`/incidents/${incidentId}/remediation/approve`, { method: "POST" }),
  rejectRemediation: (incidentId: number) =>
    request<Remediation>(`/incidents/${incidentId}/remediation/reject`, { method: "POST" }),
  validateRecovery: (remediationId: number) =>
    request<Remediation>(`/remediations/${remediationId}/validate`, { method: "POST" }),
  postmortems: () => request<Postmortem[]>("/postmortems"),
  generatePostmortem: (incidentId: number) =>
    request<Postmortem>(`/incidents/${incidentId}/postmortem/generate`, { method: "POST" }),
};