import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight,
  CircleHelp, Command, FileText, Filter, GitBranch, ListChecks, LoaderCircle,
  Plus, RefreshCw, Search, Server, Settings2, ShieldCheck, ShoppingCart, Sparkles, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type AIInvestigation, type CheckoutSimulationEvents, type CheckoutSimulationHealth, type CheckoutSimulationMetrics, type Dashboard, type Incident, type Investigation, type Postmortem, type Remediation, type Service, type StoredEvidenceDetail } from "./api";
import KnowledgeBasePage from "./KnowledgeBasePage";

type Section = "Overview" | "Incidents" | "Investigation" | "Evidence Chain" | "Root Cause" | "Services & Metrics" | "Checkout Simulation" | "Knowledge Base" | "Remediation" | "Postmortems" | "Settings";
const sections: { label: Section; icon: typeof Activity }[] = [
  { label: "Overview", icon: Activity },
  { label: "Incidents", icon: AlertTriangle },
  { label: "Investigation", icon: Search },
  { label: "Evidence Chain", icon: GitBranch },
  { label: "Root Cause", icon: AlertTriangle },
  { label: "Services & Metrics", icon: Server },
  { label: "Checkout Simulation", icon: ShoppingCart },
  { label: "Knowledge Base", icon: BookOpen },
  { label: "Remediation", icon: ListChecks },
  { label: "Postmortems", icon: FileText },
  { label: "Settings", icon: Settings2 },
];
const sectionCopy: Record<Section, [string, string]> = {
  Overview: ["Command overview", "A compact view of simulated incident activity and recovery progress."],
  Incidents: ["Incident queue", "Review and select a scenario to inspect its evidence and recommended response."],
  Investigation: ["Investigation", "Correlate the evidence trail and consult relevant runbooks."],
  "Evidence Chain": ["Evidence chain", "A traceable sequence of synthetic signals supporting the investigation."],
  "Root Cause": ["Root cause analysis", "Review persisted hypotheses, evidence support, contradictions, and missing data."],
  "Services & Metrics": ["Services & metrics", "Scenario metric histories. These charts are simulated, not production telemetry."],
  "Checkout Simulation": ["Checkout simulation", "Practice checkout incident response against deterministic, synthetic service signals."],
  "Knowledge Base": ["Knowledge base", "Search approved operational references without treating retrieved text as authorization."],
  Remediation: ["Remediation review", "Explicit operator approval is required before any simulated action is recorded."],
  Postmortems: ["Postmortems", "Generate and review clearly labeled synthetic incident narratives."],
  Settings: ["Workspace settings", "Controls for this isolated simulation workspace."],
};

function SyntheticTag() {
  return <span className="simulation-tag"><ShieldCheck aria-hidden="true" /> Synthetic simulation</span>;
}
function Status({ value }: { value: string }) {
  return <span className={`status-pill ${value.toLowerCase().replace(/\s/g, "-")}`}>{value}</span>;
}
function Severity({ value }: { value: string }) {
  return <span className={`severity ${value}`}>{value}</span>;
}
function EmptyState({ title, detail, icon: Icon = CircleHelp }: { title: string; detail: string; icon?: typeof CircleHelp }) {
  return <div className="empty"><div className="empty-mark"><Icon size={16} /></div><strong>{title}</strong><div style={{ marginTop: 6 }}>{detail}</div></div>;
}
function LoadingState() {
  return <div className="section-grid">{[0, 1, 2, 3].map((n) => <div className="surface" key={n} style={{ padding: 16 }}><div className="skeleton" style={{ height: 12, width: "42%", marginBottom: 14 }} /><div className="skeleton" style={{ height: 8, width: "78%", marginBottom: 9 }} /><div className="skeleton" style={{ height: 8, width: "60%" }} /></div>)}</div>;
}
function IncidentRow({ incident, selected, onClick }: { incident: Incident; selected?: boolean; onClick: () => void }) {
  return <div className={`incident-row ${selected ? "selected" : ""}`} role="button" tabIndex={0} onClick={onClick} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onClick(); } }}>
    <Severity value={incident.severity} />
    <div>
      <div className="incident-name">{incident.title}</div>
      <div className="incident-meta"><span className="incident-id">INC-{String(incident.id).padStart(4, "0")}</span><span>{incident.service}</span><span>{incident.source}</span></div>
    </div>
    <Status value={incident.status} />
  </div>;
}
function Surface({ title, kicker, action, children, className = "" }: { title: string; kicker?: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return <section className={`surface ${className}`}><div className="surface-head"><div><div className="surface-title">{title}</div>{kicker && <div className="surface-kicker">{kicker}</div>}</div>{action}</div>{children}</section>;
}

export default function App() {
  const [section, setSection] = useState<Section>("Overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [services, setServices] = useState<Service[]>([]);
  const [postmortems, setPostmortems] = useState<Postmortem[]>([]);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [aiInvestigation, setAiInvestigation] = useState<AIInvestigation | null>(null);
  const [health, setHealth] = useState<"checking" | "ready" | "error">("checking");
  const [loading, setLoading] = useState(true);
  const [investigationLoading, setInvestigationLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [evidenceScope, setEvidenceScope] = useState<"incident" | "checkout">("incident");
  const [evidenceTypeFilter, setEvidenceTypeFilter] = useState("all");
  const [evidenceDetail, setEvidenceDetail] = useState<StoredEvidenceDetail | null>(null);
  const [evidenceDetailLoading, setEvidenceDetailLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [aiActionLoading, setAiActionLoading] = useState(false);
  const [checkoutMetrics, setCheckoutMetrics] = useState<CheckoutSimulationMetrics | null>(null);
  const [checkoutHealth, setCheckoutHealth] = useState<CheckoutSimulationHealth | null>(null);
  const [checkoutEvents, setCheckoutEvents] = useState<CheckoutSimulationEvents | null>(null);
  const [checkoutAIInvestigation, setCheckoutAIInvestigation] = useState<AIInvestigation | null>(null);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutActionLoading, setCheckoutActionLoading] = useState(false);
  const checkoutRequested = useRef(false);
  const selectedIdRef = useRef<number | null>(selectedId);
  selectedIdRef.current = selectedId;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const results = await Promise.allSettled([
      api.dashboard(), api.incidents(), api.services(), api.postmortems(), api.health(),
    ]);
    const labels = ["dashboard", "incidents", "services", "postmortems", "workspace health"];
    let failed = "";
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        failed ||= `Could not load ${labels[index]}: ${result.reason instanceof Error ? result.reason.message : "Request failed"}`;
        return;
      }
      const value = result.value;
      if (index === 0) setDashboard(value as Dashboard);
      if (index === 1) setIncidents(value as Incident[]);
      if (index === 2) setServices(value as Service[]);
      if (index === 3) setPostmortems(value as Postmortem[]);
      if (index === 4) setHealth("ready");
    });
    if (results[4].status === "rejected") setHealth("error");
    setError(failed);
    const firstIncident = results[1].status === "fulfilled" ? (results[1].value as Incident[])[0] : null;
    const current = selectedIdRef.current ?? firstIncident?.id ?? null;
    if (current !== null && !selectedIdRef.current) {
      selectedIdRef.current = current;
      setSelectedId(current);
    }
    if (current !== null) {
      try { setInvestigation(await api.investigation(current)); }
      catch (reason) { setInvestigation(null); setError((reason instanceof Error ? reason.message : "Could not load investigation")); }
      try { setAiInvestigation(await api.aiInvestigation(current)); }
      catch { setAiInvestigation(null); }
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const loadCheckout = useCallback(async () => {
    setCheckoutLoading(true);
    setError("");
    const results = await Promise.allSettled([
      api.checkoutSimulation(), api.checkoutSimulationHealth(), api.checkoutSimulationEvents(),
      api.checkoutAIInvestigation(),
    ]);
    let failed = "";
    if (results[0].status === "fulfilled") setCheckoutMetrics(results[0].value);
    else failed ||= `Could not load checkout metrics: ${results[0].reason instanceof Error ? results[0].reason.message : "Request failed"}`;
    if (results[1].status === "fulfilled") setCheckoutHealth(results[1].value);
    else failed ||= `Could not load checkout health: ${results[1].reason instanceof Error ? results[1].reason.message : "Request failed"}`;
    if (results[2].status === "fulfilled") setCheckoutEvents(results[2].value);
    else failed ||= `Could not load checkout events: ${results[2].reason instanceof Error ? results[2].reason.message : "Request failed"}`;
    if (results[3].status === "fulfilled") setCheckoutAIInvestigation(results[3].value);
    else failed ||= `Could not load saved AI investigation: ${results[3].reason instanceof Error ? results[3].reason.message : "Request failed"}`;
    setError(failed);
    setCheckoutLoading(false);
  }, []);

  useEffect(() => {
    if (section === "Checkout Simulation" && !checkoutRequested.current) {
      checkoutRequested.current = true;
      void loadCheckout();
    }
  }, [section, loadCheckout]);

  const selectIncident = useCallback(async (id: number) => {
    setSelectedId(id);
    setEvidenceScope("incident");
    setEvidenceTypeFilter("all");
    setInvestigationLoading(true);
    setError("");
    try {
      setInvestigation(await api.investigation(id));
      try { setAiInvestigation(await api.aiInvestigation(id)); }
      catch { setAiInvestigation(null); }
    }
    catch (reason) { setInvestigation(null); setError(reason instanceof Error ? reason.message : "Could not load this investigation."); }
    finally { setInvestigationLoading(false); }
  }, []);

  async function runAIInvestigation(incidentId: number) {
    setAiActionLoading(true);
    setError("");
    try { setAiInvestigation(await api.runAIInvestigation(incidentId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not run the AI investigation."); }
    finally { setAiActionLoading(false); }
  }

  async function runCheckoutAIInvestigation() {
    setAiActionLoading(true);
    setError("");
    try {
      setCheckoutAIInvestigation(await api.runCheckoutAIInvestigation());
      await loadCheckout();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not run the checkout AI investigation.");
    } finally { setAiActionLoading(false); }
  }

  async function changeEvidenceScope(scope: "incident" | "checkout") {
    setEvidenceScope(scope);
    setEvidenceTypeFilter("all");
    if (scope !== "checkout") return;
    setCheckoutLoading(true);
    setError("");
    try {
      const [metrics, report] = await Promise.all([
        api.checkoutSimulation(),
        api.checkoutAIInvestigation(),
      ]);
      setCheckoutMetrics(metrics);
      setCheckoutAIInvestigation(report);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load the saved checkout investigation.");
    } finally {
      setCheckoutLoading(false);
    }
  }

  async function openStoredEvidence(ref: string, scope: "incident" | "checkout" = evidenceScope) {
    setEvidenceDetail(null);
    setEvidenceDetailLoading(true);
    setError("");
    try {
      const detail = scope === "checkout"
        ? await api.checkoutAIEvidence(ref)
        : selected ? await api.incidentAIEvidence(selected.id, ref) : null;
      if (!detail) throw new Error("Select an incident before opening its evidence.");
      setEvidenceDetail(detail);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open the stored evidence record.");
    } finally {
      setEvidenceDetailLoading(false);
    }
  }

  const filteredIncidents = useMemo(() => incidents.filter((incident) =>
    `${incident.title} ${incident.service} ${incident.summary} ${incident.id}`.toLowerCase().includes(query.toLowerCase()) &&
    (severityFilter === "all" || incident.severity === severityFilter)), [incidents, query, severityFilter]);
  const selected = incidents.find((item) => item.id === selectedId) ?? investigation?.incident ?? null;
  const [heading, description] = sectionCopy[section];

  async function createIncident(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const created = await api.createIncident({
        title: String(form.get("title") || ""),
        severity: String(form.get("severity") || "medium") as Incident["severity"],
        service_id: Number(form.get("service_id")),
        summary: String(form.get("summary") || ""),
      });
      setIncidents((old) => [created, ...old]);
      setCreateOpen(false);
      setSection("Incidents");
      await selectIncident(created.id);
      const [nextDashboard] = await Promise.all([api.dashboard()]);
      setDashboard(nextDashboard);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create the scenario."); }
    finally { setSubmitting(false); }
  }

  async function remediationAction(action: "approve" | "reject" | "validate") {
    if (!investigation || !selected) return;
    if (action !== "validate" && !window.confirm(`${action === "approve" ? "Approve" : "Reject"} this simulated remediation for ${selected.title}? No infrastructure will be changed.`)) return;
    setActionLoading(true);
    setError("");
    try {
      let remediation: Remediation;
      if (action === "approve") remediation = await api.approveRemediation(selected.id);
      else if (action === "reject") remediation = await api.rejectRemediation(selected.id);
      else if (investigation.remediation) remediation = await api.validateRecovery(investigation.remediation.id);
      else return;
      setInvestigation((current) => current ? { ...current, remediation } : current);
      const fresh = await api.incidents();
      setIncidents(fresh);
      if (dashboard) setDashboard(await api.dashboard());
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The simulated action could not be completed."); }
    finally { setActionLoading(false); }
  }

  async function startCheckoutIncident() {
    setCheckoutActionLoading(true);
    setError("");
    try {
      setCheckoutMetrics(await api.startCheckoutSimulation());
      await loadCheckout();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the checkout incident simulation.");
    } finally {
      setCheckoutActionLoading(false);
    }
  }

  async function resetCheckoutSimulation() {
    if (!window.confirm("Reset the checkout simulation to its healthy state? This affects the simulation only; no live infrastructure is connected.")) return;
    setCheckoutActionLoading(true);
    setError("");
    try {
      setCheckoutMetrics(await api.resetCheckoutSimulation());
      await loadCheckout();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reset the checkout simulation.");
    } finally {
      setCheckoutActionLoading(false);
    }
  }

  async function generatePostmortem() {
    if (!selected) return;
    setActionLoading(true);
    setError("");
    try {
      const created = await api.generatePostmortem(selected.id);
      setPostmortems((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setInvestigation((current) => current ? { ...current, postmortem: created } : current);
      setSection("Postmortems");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not generate a postmortem."); }
    finally { setActionLoading(false); }
  }

  function evidenceScopePicker() {
    return <label className="evidence-scope-picker">
      <span>Investigation source</span>
      <select
        className="select"
        value={evidenceScope}
        onChange={(event) => void changeEvidenceScope(event.target.value as "incident" | "checkout")}
      >
        <option value="incident">{selected ? `Incident · ${selected.title}` : "Selected incident"}</option>
        <option value="checkout">Checkout DB_POOL_SIZE demo</option>
      </select>
    </label>;
  }

  function renderEvidenceDetail() {
    if (!evidenceDetail && !evidenceDetailLoading) return null;
    return <div className="evidence-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setEvidenceDetail(null);
    }}>
      <section className="evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-modal-title">
        <div className="surface-head">
          <div><div id="evidence-modal-title" className="surface-title">Original stored evidence</div><div className="surface-kicker">Read-only database record</div></div>
          <button className="button small" aria-label="Close evidence detail" onClick={() => setEvidenceDetail(null)}><X size={13} /></button>
        </div>
        {evidenceDetailLoading ? <div className="surface-body"><LoadingState /></div> : evidenceDetail && <div className="surface-body evidence-modal-content">
          <div><span>Identifier</span><code>{evidenceDetail.id}</code></div>
          <div><span>Source type</span><strong>{evidenceDetail.source_type.replace(/_/g, " ")}</strong></div>
          <div><span>Source reference</span><code>{evidenceDetail.source_reference}</code></div>
          <div><span>Timestamp</span><strong>{evidenceDetail.timestamp ? new Date(evidenceDetail.timestamp).toLocaleString() : "No event timestamp stored"}</strong></div>
          <div><span>Source</span><strong>{evidenceDetail.source}</strong></div>
          {evidenceDetail.value !== null && <div><span>Value</span><strong>{evidenceDetail.value}</strong></div>}
          <div className="evidence-modal-excerpt"><span>Original excerpt</span><p>{evidenceDetail.excerpt}</p></div>
        </div>}
      </section>
    </div>;
  }

  function renderEvidence() {
    const report = evidenceScope === "checkout" ? checkoutAIInvestigation : aiInvestigation;
    const incidentBusy = evidenceScope === "incident" && investigationLoading;
    if (incidentBusy || (evidenceScope === "checkout" && checkoutLoading)) return <LoadingState />;
    if (evidenceScope === "incident" && !selected) return <EmptyState title="Select an incident" detail="Choose a scenario from the incident queue to inspect its saved evidence chain." icon={GitBranch} />;
    if (!report) return <div className="evidence-page">
      {evidenceScopePicker()}
      <Surface title="No persisted investigation" kicker="Evidence is not generated or inferred on this page">
        <div className="surface-body">
          <EmptyState
            title="No saved evidence chain yet"
            detail={evidenceScope === "incident"
              ? "Run an investigation to save the source records, timestamps, and cited hypotheses for this incident."
              : "Start the synthetic pool-reduction scenario in Checkout Simulation, then save its investigation."}
            icon={GitBranch}
          />
          {evidenceScope === "incident" && selected
            ? <button className="button primary" onClick={() => void runAIInvestigation(selected.id)} disabled={aiActionLoading}><Sparkles size={13} />{aiActionLoading ? "Investigating…" : "Run and save investigation"}</button>
            : <button className="button primary" onClick={() => setSection("Checkout Simulation")}><ShoppingCart size={13} />Open Checkout Simulation</button>}
        </div>
      </Surface>
    </div>;

    const rootHypotheses = report.agents.root_cause.hypotheses;
    const entries = [
      ...report.evidence.map((item) => ({
        id: item.id,
        sourceReference: item.source_ref ?? item.id,
        sourceType: item.kind === "knowledge"
          ? item.record_class === "historical" ? "historical_incident" : "runbook_excerpt"
          : item.kind === "log" ? "application_log"
            : item.kind === "deployment" ? "deployment_or_configuration" : item.kind,
        timestamp: item.observed_at,
        source: item.source,
        excerpt: item.excerpt ?? item.text,
        value: item.value ?? null,
        evidenceRef: item.id,
        hypothesis: false,
      })),
      ...rootHypotheses.map((hypothesis) => ({
        id: `hypothesis:${hypothesis.key}`,
        sourceReference: `ai_investigation:${report.id}#${hypothesis.key}`,
        sourceType: "root_cause_hypothesis",
        timestamp: report.created_at,
        source: hypothesis.origin,
        excerpt: hypothesis.explanation,
        value: hypothesis.confidence_score,
        evidenceRef: null,
        hypothesis: true,
      })),
    ].sort((a, b) => {
      if (!a.timestamp) return b.timestamp ? 1 : a.id.localeCompare(b.id);
      if (!b.timestamp) return -1;
      return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
    });
    const filteredEntries = evidenceTypeFilter === "all"
      ? entries
      : entries.filter((item) => item.sourceType === evidenceTypeFilter);
    const typeOptions = [...new Set(entries.map((item) => item.sourceType))].sort();
    const staleCheckoutReport = evidenceScope === "checkout"
      && checkoutMetrics !== null
      && report.run_number !== checkoutMetrics.run_number;

    return <div className="evidence-page">
      <div className="evidence-page-toolbar">
        {evidenceScopePicker()}
        <label className="evidence-scope-picker">
          <span>Filter by evidence type</span>
          <select className="select" value={evidenceTypeFilter} onChange={(event) => setEvidenceTypeFilter(event.target.value)}>
            <option value="all">All types · {entries.length}</option>
            {typeOptions.map((type) => <option key={type} value={type}>{type.replace(/_/g, " ")} · {entries.filter((item) => item.sourceType === type).length}</option>)}
          </select>
        </label>
        <div className="evidence-report-meta">Saved investigation #{report.id} · {new Date(report.created_at).toLocaleString()}</div>
      </div>
      {staleCheckoutReport && <div className="notice evidence-stale-notice">The checkout simulation has changed since this report was saved. Re-run the investigation to refresh this timeline.</div>}
      <Surface title={`${filteredEntries.length} timeline entries`} kicker={`${report.title} · chronological · stored evidence`} action={<SyntheticTag />}>
        <div className="evidence-timeline">
          {filteredEntries.length ? filteredEntries.map((item) => <article className="evidence-timeline-item" key={item.id}>
            <div className={`evidence-timeline-mark ${item.sourceType}`} />
            <div className="evidence-timeline-card">
              <div className="evidence-timeline-heading">
                <span className="evidence-kind">{item.sourceType.replace(/_/g, " ")}</span>
                <time>{item.timestamp ? new Date(item.timestamp).toLocaleString() : "No event timestamp stored"}</time>
              </div>
              <div className="evidence-timeline-source">{item.source}</div>
              <p>{item.excerpt}</p>
              {item.value !== null && <div className="evidence-timeline-value">{item.hypothesis ? `${Math.round(Number(item.value) * 100)}% heuristic support` : `Recorded value: ${item.value}`}</div>}
              <div className="evidence-timeline-ref"><span>Stable ID</span><code>{item.id}</code><span>Source reference</span><code>{item.sourceReference}</code></div>
              {item.evidenceRef
                ? <button className="button small" onClick={() => void openStoredEvidence(item.evidenceRef!, evidenceScope)}>Open original record <ArrowRight size={12} /></button>
                : <button className="button small" onClick={() => setSection("Root Cause")}>Open saved hypothesis <ArrowRight size={12} /></button>}
            </div>
          </article>) : <EmptyState title="No items match this filter" detail="Choose another evidence type or return to all timeline entries." icon={Filter} />}
        </div>
      </Surface>
      <Surface title="Evidence interpretation" kicker="Observed records are separate from model-selected hypotheses">
        <div className="surface-body"><p className="detail-summary">The timeline contains only records attached to the saved investigation. Hypothesis entries are clearly labeled and point back to the persisted report; they are not original telemetry.</p><button className="button small" onClick={() => setSection("Root Cause")}>Review hypothesis support <ArrowRight size={12} /></button></div>
      </Surface>
      {renderEvidenceDetail()}
    </div>;
  }

  function renderRootCause() {
    const report = evidenceScope === "checkout" ? checkoutAIInvestigation : aiInvestigation;
    const busy = evidenceScope === "incident" ? investigationLoading : checkoutLoading;
    if (busy) return <LoadingState />;
    if (evidenceScope === "incident" && !selected) return <EmptyState title="Select an incident" detail="Choose an incident to review its saved root-cause hypotheses." icon={AlertTriangle} />;
    if (!report) return <div className="evidence-page">
      {evidenceScopePicker()}
      <Surface title="No persisted root-cause report" kicker="This page reads saved investigation output">
        <div className="surface-body">
          <EmptyState
            title="No hypotheses saved"
            detail={evidenceScope === "incident"
              ? "Run an investigation to create evidence-linked hypotheses for this incident."
              : "Run the Checkout Simulation and save its AI investigation to review the DB_POOL_SIZE scenario."}
            icon={AlertTriangle}
          />
          {evidenceScope === "incident" && selected
            ? <button className="button primary" onClick={() => void runAIInvestigation(selected.id)} disabled={aiActionLoading}><Sparkles size={13} />{aiActionLoading ? "Investigating…" : "Run and save investigation"}</button>
            : <button className="button primary" onClick={() => setSection("Checkout Simulation")}><ShoppingCart size={13} />Open Checkout Simulation</button>}
        </div>
      </Surface>
    </div>;

    const hypotheses = report.agents.root_cause.hypotheses;
    const poolFact = report.observed_facts.find((fact) => fact.id === "pool_size_change");
    const staleCheckoutReport = evidenceScope === "checkout"
      && checkoutMetrics !== null
      && report.run_number !== checkoutMetrics.run_number;
    const citations = (refs: string[]) => refs.length
      ? <div className="root-cause-citations">{refs.map((ref) => {
        const item = report.evidence.find((evidence) => evidence.id === ref);
        return <button key={ref} className="root-cause-citation" onClick={() => void openStoredEvidence(ref, evidenceScope)}>
          <strong>{item?.source ?? ref}</strong><span>{item?.excerpt ?? item?.text ?? "Stored source record"}</span><code>{ref}</code>
        </button>;
      })}</div>
      : <p className="ai-muted">No direct records of this type were cited.</p>;

    return <div className="evidence-page">
      <div className="evidence-page-toolbar">
        {evidenceScopePicker()}
        <div className="evidence-report-meta">Saved investigation #{report.id} · {new Date(report.created_at).toLocaleString()}</div>
        <button className="button small" onClick={() => evidenceScope === "checkout"
          ? void runCheckoutAIInvestigation()
          : selected && void runAIInvestigation(selected.id)} disabled={aiActionLoading}>
          {aiActionLoading ? <LoaderCircle size={13} /> : <RefreshCw size={13} />} Re-run from stored evidence
        </button>
      </div>
      {staleCheckoutReport && <div className="notice evidence-stale-notice">This saved report predates the current checkout simulation run. Re-run it before interpreting the latest signals.</div>}
      {poolFact && <Surface title="DB_POOL_SIZE scenario evidence" kicker="Derived from persisted metric and configuration records">
        <div className="surface-body">
          <p className="root-cause-pool-fact">{poolFact.statement}</p>
          {citations(poolFact.evidence_ids)}
          <p className="ai-muted">This summary is calculated from the cited stored samples. No fixed confidence value is applied.</p>
        </div>
      </Surface>}
      <Surface title="Investigation summary" kicker={`${report.service} · ${report.provider_message}`}>
        <div className="surface-body">
          <p className="detail-summary">{hypotheses.length
            ? `${hypotheses.length} testable explanations are retained. The highest evidence-support score is a heuristic ranking, not proof of cause.`
            : "The saved investigation contains no root-cause hypotheses."}</p>
          <div className="notice">Several causes can remain plausible at once. Correlation and heuristic scores do not establish causation.</div>
          {report.retrieval_warning && <div className="notice">{report.retrieval_warning}</div>}
        </div>
      </Surface>
      <div className="root-cause-list">
        {hypotheses.map((hypothesis) => <Surface key={hypothesis.key} title={hypothesis.title} kicker={`${hypothesis.confidence_label} · hypothesis, not a confirmed cause`}>
          <div className="surface-body root-cause-body">
            <div className="root-cause-score">
              <strong>{Math.round(hypothesis.confidence_score * 100)}% heuristic evidence support</strong>
              <div className="ai-score-track"><div style={{ width: `${Math.round(hypothesis.confidence_score * 100)}%` }} /></div>
              <span>Not a statistically calibrated probability</span>
            </div>
            <p className="detail-summary">{hypothesis.explanation}</p>
            <div className="root-cause-subsection"><h3>Supporting evidence</h3>{citations(hypothesis.supporting_evidence_ids ?? hypothesis.evidence_ids)}</div>
            <div className="root-cause-subsection"><h3>Contradicting evidence</h3>{hypothesis.contradicting_evidence_ids?.length
              ? citations(hypothesis.contradicting_evidence_ids)
              : <p className="ai-muted">No direct contradicting record was identified in the retrieved evidence; absence of contradiction is not confirmation.</p>}</div>
            <div className="root-cause-subsection"><h3>Evidence still missing</h3>
              {hypothesis.missing_evidence?.length
                ? <ul>{hypothesis.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
                : <p className="ai-muted">{hypothesis.uncertainty}</p>}
            </div>
            <div className="root-cause-subsection"><h3>Next validation test</h3><p>{hypothesis.test}</p></div>
          </div>
        </Surface>)}
      </div>
      <Surface title="Scoring method and alternatives" kicker="Transparent heuristic">
        <div className="surface-body">
          <p className="detail-summary">{report.support_score_method}</p>
          <p className="ai-muted">{report.support_score_note}</p>
          <p className="ai-muted">Alternatives remain visible above rather than being discarded. Gather the missing time-aligned records before choosing one cause.</p>
        </div>
      </Surface>
      {renderEvidenceDetail()}
    </div>;
  }

  function renderRemediation() {
    if (investigationLoading) return <LoadingState />;
    if (!selected) return <EmptyState title="No scenario selected" detail="Select an incident before reviewing simulated remediation." icon={ListChecks} />;
    const remediation = investigation?.remediation;
    return <div className="section-grid">
      <Surface title="Operator decision" kicker={`INC-${String(selected.id).padStart(4, "0")} · simulated`}>
        <div className="surface-body">
          {investigation?.recommendation && <div className="notice" style={{ marginTop: 0 }}>
            Recorded guidance · {investigation.recommendation.risk} risk · {Math.round(investigation.recommendation.confidence * 100)}% confidence.
            {" "}{investigation.recommendation.action} This deterministic guidance is not AI output and does not execute an action.
          </div>}
          {remediation ? <div className="remediation-box">
            <div className="detail-heading"><div className="remediation-action">{remediation.action}</div><Status value={remediation.state} /></div>
            <p className="remediation-copy">{remediation.result || "Proposed response for this simulated scenario. Review carefully before recording a decision."}</p>
            <div className="action-row">
              {remediation.state === "approved" && <button className="button success" onClick={() => void remediationAction("validate")} disabled={actionLoading}><CheckCircle2 size={14} />{actionLoading ? "Checking…" : "Run simulated recovery check"}</button>}
              {remediation.state === "rejected" && <span className="activity-detail">This proposal was rejected. No action was performed.</span>}
              {remediation.state === "validated" && <span className="activity-detail"><CheckCircle2 size={14} style={{ verticalAlign: "middle", marginRight: 5, color: "var(--green)" }} />Recovery check {remediation.validation_passed ? "passed" : "did not pass"} · simulated</span>}
            </div>
          </div> : <div className="remediation-box">
            <div className="remediation-action">No remediation decision recorded</div>
            <p className="remediation-copy">An available response may be reviewed and explicitly approved or rejected. This workspace only records a simulated decision.</p>
            <div className="action-row">
              <button className="button success" onClick={() => void remediationAction("approve")} disabled={actionLoading || !investigation}><Check size={14} />Approve simulated action</button>
              <button className="button danger" onClick={() => void remediationAction("reject")} disabled={actionLoading || !investigation}><X size={14} />Reject proposal</button>
            </div>
          </div>}
          <div className="notice">Approval records a simulated choice only. No production systems, credentials, or infrastructure are connected to this workspace.</div>
        </div>
      </Surface>
      <Surface title="Guardrails" kicker="Always in effect">
        <div className="surface-body">
          {[["Human approval", "A human operator must explicitly record a decision."], ["Simulation only", "No production telemetry or infrastructure changes."], ["Recovery validation", "Checks are simulated and do not probe live systems."]].map(([title, body]) => <div className="activity-item" key={title}><div className="activity-mark" /><div><div className="activity-title">{title}</div><div className="activity-detail">{body}</div></div></div>)}
        </div>
      </Surface>
    </div>;
  }

  function renderServices() {
    if (loading && !services.length) return <LoadingState />;
    if (!services.length) return <EmptyState title="No service scenarios available" detail="Service metric histories will appear here when synthetic data is available." icon={Server} />;
    return <div className="service-grid">{services.map((service) => {
      const latencyData = service.latency_history.map((value, index) => ({ point: index + 1, value }));
      const errorData = service.error_history.map((value, index) => ({ point: index + 1, value }));
      return <article className="service-card" key={service.id}>
        <div className="service-top"><div><div className="service-name">{service.name}</div><div className="service-owner">Owner: {service.owner} · {service.environment}</div></div><span className="simulation-tag">Synthetic</span></div>
        <div className="service-metrics">
          <div><div className="metric-label">Latency</div><div className="metric-value">{service.latency_ms ?? "—"} ms</div></div>
          <div><div className="metric-label">Error rate</div><div className="metric-value">{service.error_rate ?? "—"}%</div></div>
          <div><div className="metric-label">Request rate</div><div className="metric-value">{service.request_rate ?? "—"}/s</div></div>
        </div>
        <div className="section-grid" style={{ gap: 10, marginTop: 13 }}>
          <div><div className="chart-caption">Latency history · simulated</div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={latencyData}><defs><linearGradient id={`lat-${service.id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#64d7e7" stopOpacity={.23} /><stop offset="100%" stopColor="#64d7e7" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#203247" vertical={false} /><XAxis dataKey="point" hide /><YAxis hide /><Tooltip contentStyle={{ background: "#101e2e", border: "1px solid #30475c", borderRadius: 5, color: "#dce7f2", fontSize: 10 }} /><Area type="monotone" dataKey="value" stroke="#64d7e7" fill={`url(#lat-${service.id})`} strokeWidth={1.5} /></AreaChart></ResponsiveContainer></div></div>
          <div><div className="chart-caption">Error history · simulated</div><div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={errorData}><defs><linearGradient id={`err-${service.id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#75a9f7" stopOpacity={.2} /><stop offset="100%" stopColor="#75a9f7" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#203247" vertical={false} /><XAxis dataKey="point" hide /><YAxis hide /><Tooltip contentStyle={{ background: "#101e2e", border: "1px solid #30475c", borderRadius: 5, color: "#dce7f2", fontSize: 10 }} /><Area type="monotone" dataKey="value" stroke="#75a9f7" fill={`url(#err-${service.id})`} strokeWidth={1.5} /></AreaChart></ResponsiveContainer></div></div>
        </div>
      </article>;
    })}</div>;
  }

  function renderCheckoutSimulation() {
    if (checkoutLoading && !checkoutMetrics) return <LoadingState />;
    if (!checkoutMetrics) return <EmptyState title="Checkout simulation unavailable" detail="Retry to load the deterministic checkout scenario from the simulation API." icon={AlertTriangle} />;
    const events = [...(checkoutEvents?.items ?? [])].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
    const metricsToChart = [
      { key: "latency_ms", label: "Latency", unit: "ms", color: "#64d7e7" },
      { key: "error_rate_percent", label: "Error rate", unit: "%", color: "#f18d91" },
      { key: "request_volume_rps", label: "Request volume", unit: "rps", color: "#75a9f7" },
      { key: "db_pool_utilization_percent", label: "DB pool utilization", unit: "%", color: "#e9bd72" },
      { key: "db_pool_size", label: "DB pool size", unit: " connections", color: "#a9a0dc" },
    ] as const;
    const formatValue = (value: number | null, unit: string) => value === null
      ? "—"
      : `${Number.isInteger(value) ? value : value.toFixed(1)}${unit}`;
    return <>
      <section className="checkout-command surface" aria-label="Checkout simulation controls">
        <div className="checkout-command-top">
          <div>
            <div className="checkout-state-row">
              <span className={`checkout-state ${checkoutMetrics.state}`}>{checkoutMetrics.state === "incident" ? "Incident active" : "Healthy"}</span>
              <span className="checkout-health-copy">Overall health <Status value={checkoutHealth?.overall_status ?? "unavailable"} /></span>
            </div>
            <div className="checkout-run-meta">RUN {String(checkoutMetrics.run_number).padStart(2, "0")} <span>·</span> UPDATED {new Date(checkoutMetrics.updated_at).toLocaleString()}</div>
          </div>
          <div className="action-row checkout-actions">
            <button className="button primary" onClick={() => void startCheckoutIncident()} disabled={checkoutActionLoading || checkoutMetrics.state === "incident"}>
              {checkoutActionLoading ? <LoaderCircle size={14} /> : <AlertTriangle size={14} />}
              {checkoutActionLoading ? "Applying…" : checkoutMetrics.state === "incident" ? "Incident already active" : "Start incident"}
            </button>
            <button className="button" onClick={() => void resetCheckoutSimulation()} disabled={checkoutActionLoading}>
              {checkoutActionLoading ? <LoaderCircle size={14} /> : <RefreshCw size={14} />}
              Reset to healthy
            </button>
            <button className="button" onClick={() => void runCheckoutAIInvestigation()} disabled={aiActionLoading}>
              {aiActionLoading ? <LoaderCircle size={14} /> : <Sparkles size={14} />}
              {aiActionLoading ? "Investigating…" : "Run AI investigation"}
            </button>
            <button className="button small" onClick={() => void loadCheckout()} disabled={checkoutLoading || checkoutActionLoading} aria-label="Refresh checkout simulation data">
              <RefreshCw size={13} />{checkoutLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
        <div className="checkout-boundary">
          <ShieldCheck size={14} aria-hidden="true" />
          <span>Deterministic training scenario. Every signal below is synthetic and isolated from live infrastructure.</span>
        </div>
      </section>

      <div className="checkout-service-grid">
        {checkoutMetrics.services.map((service) => {
          const serviceHealth = checkoutHealth?.services.find((item) => item.name === service.name);
          const values = [
            ["Latency", formatValue(service.latency_ms, " ms")],
            ["Error rate", formatValue(service.error_rate_percent, "%")],
            ["Requests", formatValue(service.request_volume_rps, " rps")],
            ["DB pool", formatValue(service.db_pool_utilization_percent, "%")],
          ];
          return <article className="checkout-service surface" key={service.service_id}>
            <div className="checkout-service-head">
              <div>
                <div className="checkout-service-name">{service.name}</div>
                <div className="checkout-service-summary">{serviceHealth?.summary ?? "Service health summary unavailable."}</div>
              </div>
              <Status value={serviceHealth?.status ?? service.status} />
            </div>
            <div className="checkout-current-grid">
              {values.map(([label, value]) => <div className="checkout-current" key={label}>
                <div className="metric-label">{label}</div><div className="metric-value">{value}</div>
              </div>)}
              <div className="checkout-current">
                <div className="metric-label">DB pool size</div><div className="metric-value">{service.db_pool_size ?? "—"}</div>
              </div>
            </div>
            <div className="checkout-chart-grid">
              {metricsToChart.map((metric) => <div className="checkout-chart-panel" key={metric.key}>
                <div className="chart-caption">{metric.label} history <span>· synthetic</span></div>
                {service.history.length ? <div className="checkout-chart-wrap">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={service.history} margin={{ top: 8, right: 7, bottom: 0, left: 0 }}>
                      <CartesianGrid stroke="#203247" vertical={false} />
                      <XAxis dataKey="timestamp" tickFormatter={(value: string) => new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} tick={{ fill: "#71869b", fontSize: 8 }} tickLine={false} axisLine={false} minTickGap={22} />
                      <YAxis hide domain={["auto", "auto"]} />
                      <Tooltip labelFormatter={(value) => new Date(String(value)).toLocaleString()} formatter={(value) => [value == null ? "—" : `${value} ${metric.unit}`, metric.label]} contentStyle={{ background: "#101e2e", border: "1px solid #30475c", borderRadius: 5, color: "#dce7f2", fontSize: 10 }} />
                      <Line type="monotone" dataKey={metric.key} stroke={metric.color} strokeWidth={1.6} dot={false} activeDot={{ r: 3 }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div> : <div className="checkout-chart-empty">No history points returned.</div>}
              </div>)}
            </div>
            <div className="checkout-service-foot">
              <span>{service.history.length} timestamped samples</span>
              <span>{service.is_synthetic ? "Synthetic" : "Not marked synthetic"}</span>
            </div>
          </article>;
        })}
      </div>

      <Surface title="Deployment & log timeline" kicker="Persistent backend events · chronological" action={<span className="simulation-tag">Synthetic event stream</span>}>
        <div className="checkout-timeline">
          {checkoutEvents === null ? <EmptyState title="Event timeline unavailable" detail="Retry the checkout simulation request to load backend event records." icon={Activity} />
            : events.length ? events.map((event) => <article className="checkout-event" key={event.id}>
              <div className={`checkout-event-mark ${event.kind}`} />
              <div className="checkout-event-main">
                <div className="checkout-event-heading">
                  <div className="checkout-event-title">{event.title}</div>
                  <div className="checkout-event-tags"><span className={`checkout-event-kind ${event.kind}`}>{event.kind}</span><span className="checkout-event-level">{event.level}</span></div>
                </div>
                <div className="checkout-event-detail">{event.detail}</div>
                <div className="checkout-event-meta"><span>{event.service}</span><span>{new Date(event.timestamp).toLocaleString()}</span><span>{event.is_synthetic ? "Synthetic" : "Not marked synthetic"}</span></div>
              </div>
            </article>) : <EmptyState title="No checkout events yet" detail="Deployment and log records will appear here as the simulation runs." icon={Activity} />}
        </div>
      </Surface>
      {checkoutAIInvestigation
        ? renderAIInvestigation(
          checkoutAIInvestigation,
          () => void runCheckoutAIInvestigation(),
          aiActionLoading,
          checkoutAIInvestigation.run_number !== checkoutMetrics.run_number,
          "checkout",
        )
        : <Surface title="Agent investigation" kicker="Evidence-first · saved to SQLite">
          <div className="surface-body">
            <p className="detail-summary">The agents correlate database timeout frequency, DB_POOL_SIZE, checkout traffic, historical incidents, and approved troubleshooting documents.</p>
            <p className="ai-muted">Run an analysis to save the observed facts, alternative testable hypotheses, advisory recovery plan, validation status, and draft report.</p>
          </div>
        </Surface>}
    </>;
  }

  function renderPostmortem(pm: Postmortem) {
    return <article className="postmortem" key={pm.id}>
      <div className="detail-heading"><div><h3>{pm.title}</h3><div className="runbook-meta">INC-{String(pm.incident_id).padStart(4, "0")} · {new Date(pm.created_at).toLocaleString()}</div></div><SyntheticTag /></div>
      <div className="pm-section"><strong>Summary</strong><p>{pm.summary}</p></div>
      <div className="pm-section"><strong>Root cause</strong><p>{pm.root_cause}</p></div>
      <div className="pm-section"><strong>Impact</strong><p>{pm.impact}</p></div>
      <div className="pm-section"><strong>Prevention</strong><p>{pm.prevention}</p></div>
    </article>;
  }

  function renderAIInvestigation(
    report: AIInvestigation,
    onRun: () => void,
    busy: boolean,
    staleRun = false,
    evidenceScopeForReport: "incident" | "checkout" = report.scope === "checkout_simulation" ? "checkout" : "incident",
  ) {
    const evidenceById = new Map(report.evidence.map((item) => [item.id, item]));
    const citations = (ids: string[]) => ids.length ? <div className="ai-citations">
      {ids.map((id) => {
        const item = evidenceById.get(id);
        return <button className="ai-citation" key={id} disabled={!item} onClick={() => void openStoredEvidence(id, evidenceScopeForReport)}>
          <strong>{item?.source ?? id}</strong>
          <span>{item?.text ?? "Source record unavailable."}</span>
          {item?.observed_at && <small>{new Date(item.observed_at).toLocaleString()}</small>}
        </button>;
      })}
    </div> : <div className="ai-muted">No supporting records were available.</div>;

    return <Surface
      title="Agent investigation"
      kicker={`Saved ${new Date(report.created_at).toLocaleString()} · ${report.provider_status.replace(/_/g, " ")}`}
      action={<button className="button small" onClick={onRun} disabled={busy}>
        {busy ? <LoaderCircle size={13} /> : <RefreshCw size={13} />}
        {busy ? "Investigating…" : "Run again"}
      </button>}
    >
      <div className="surface-body ai-investigation-body">
        <div className="ai-status-notice">
          <strong>{report.provider_status === "available" ? "AI-assisted" : "Deterministic fallback"}</strong>
          <span>{report.provider_message}</span>
          <small>{report.safety}</small>
          {staleRun && <strong>This report is from an earlier simulation run. Run the investigation again.</strong>}
        </div>
        <div className="ai-section">
          <h3>Recorded facts</h3>
          <p className="ai-muted">Observed metrics and logs are kept separate from generated hypotheses.</p>
          {report.observed_facts.length ? report.observed_facts.map((fact) => <article className="ai-fact" key={fact.id}>
            <div><strong>{fact.statement}</strong><span>{fact.source} · {fact.kind}</span></div>
            {citations(fact.evidence_ids)}
          </article>) : <div className="ai-muted">No matching observations were collected.</div>}
        </div>
        <div className="ai-section">
          <h3>Root-cause hypotheses</h3>
          <p className="ai-muted">Testable explanations only. Scores are evidence-support scores, not probabilities.</p>
          {report.agents.root_cause.hypotheses.map((item) => <article className="ai-hypothesis" key={item.key}>
            <div className="ai-hypothesis-heading">
              <strong>{item.title}</strong>
              <span>{Math.round(item.confidence_score * 100)}% evidence support</span>
            </div>
            <div className="ai-score-track"><div style={{ width: `${Math.round(item.confidence_score * 100)}%` }} /></div>
            <span className="ai-hypothesis-label">{item.confidence_label}{item.ai_selected ? " · selected by AI" : " · retained alternative"}</span>
            <p>{item.explanation}</p>
            <p><strong>Test:</strong> {item.test}</p>
            <p className="ai-uncertainty"><strong>Uncertainty:</strong> {item.uncertainty}</p>
            {citations(item.ai_evidence_ids?.length ? item.ai_evidence_ids : item.evidence_ids)}
          </article>)}
          <details className="ai-method">
            <summary>How the evidence score is calculated</summary>
            <p>{report.support_score_method}</p><p>{report.support_score_note}</p>
          </details>
        </div>
        <div className="ai-agent-grid">
          <section className="ai-agent-card">
            <h3>Triage</h3><p>{report.agents.triage.severity} · {report.agents.triage.scope.replace(/_/g, " ")}</p>
            <span>{report.agents.triage.note}</span>{citations(report.agents.triage.evidence_ids)}
          </section>
          <section className="ai-agent-card">
            <h3>Log patterns</h3>
            <p>{report.agents.log_analysis.patterns.map((item) => item.code.replace(/_/g, " ")).join(", ") || "No recognized pattern"}</p>
            {report.agents.log_analysis.patterns.map((item) => <div key={item.code}>{citations(item.evidence_ids)}</div>)}
          </section>
          <section className="ai-agent-card">
            <h3>Change analysis</h3><p>{report.agents.change_analysis.relationship.replace(/_/g, " ")}</p>
            <span>{report.agents.change_analysis.note}</span>{citations(report.agents.change_analysis.evidence_ids)}
          </section>
          <section className="ai-agent-card">
            <h3>Knowledge agent · {report.retrieval_mode.replace(/_/g, " ")}</h3>
            {report.retrieval_warning && <p>{report.retrieval_warning}</p>}
            {report.agents.knowledge.items.map((item) => <div className="ai-knowledge" key={`${item.document_id}-${item.chunk_index}`}>
              <strong>{item.title} · {item.source}</strong><p>{item.excerpt}</p>
            </div>)}
          </section>
        </div>
        <div className="ai-section">
          <h3>Advisory recovery plan · {report.agents.remediation.risk} risk</h3>
          <p>{report.agents.remediation.plan}</p>
          <span>{report.agents.remediation.source}. Human review remains required; this does not approve or execute an action.</span>
          {citations(report.agents.remediation.evidence_ids)}
        </div>
        <div className="ai-agent-grid">
          <section className="ai-agent-card">
            <h3>Validation agent</h3><p>{report.agents.validation.assessment.replace(/_/g, " ")}</p>
            <span>{report.agents.validation.detail}</span>
            {report.agents.validation.observations?.map((item) => <div className="ai-validation-metric" key={item.metric}>
              <strong>{item.metric.replace(/_/g, " ")}</strong>
              <span>{item.before} → {item.after} · {item.change}</span>
              {citations(item.evidence_ids)}
            </div>)}
          </section>
          <section className="ai-agent-card">
            <h3>Postmortem draft · review required</h3>
            <p>{report.agents.postmortem.summary}</p>
            <span>Impact: {report.agents.postmortem.impact}</span>
            <span>Timeline: {report.agents.postmortem.timeline}</span>
            <span>Prevention: {report.agents.postmortem.prevention}</span>
            {citations(report.agents.postmortem.evidence_ids)}
          </section>
        </div>
      </div>
      {renderEvidenceDetail()}
    </Surface>;
  }

  function renderMain() {
    if (section === "Overview") {
      if (loading && !dashboard) return <LoadingState />;
      if (!dashboard) return <EmptyState title="Workspace data unavailable" detail="Retry to reconnect to the synthetic incident workspace." icon={AlertTriangle} />;
      return <>
        <div className="stat-grid">
          {[
            ["Active incidents", dashboard.active_incidents, "Across seeded scenarios"],
            ["Critical", dashboard.critical_incidents, "Require focused review"],
            ["Affected services", dashboard.affected_services, "Synthetic service set"],
            ["Recovery checks", dashboard.recovery_checks_passed, "Simulated checks passed"],
          ].map(([label, value, foot]) => <div className="stat-card" key={String(label)}><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-foot">{foot} · synthetic</div></div>)}
        </div>
        <div className="overview-grid">
          <Surface title="Incident queue" kicker="Select a scenario to investigate" action={<button className="button small" onClick={() => setSection("Incidents")}>All incidents <ArrowRight size={12} /></button>}>
            {dashboard.incidents.length ? <div className="incident-list">{dashboard.incidents.slice(0, 5).map((incident) => <IncidentRow key={incident.id} incident={incident} selected={incident.id === selectedId} onClick={() => { void selectIncident(incident.id); setSection("Investigation"); }} />)}</div> : <EmptyState title="No active scenarios" detail="Create a simulated incident to begin an investigation." icon={CheckCircle2} />}
          </Surface>
          <Surface title="Activity stream" kicker="Synthetic workspace events">
            <div className="surface-body activity-list">{dashboard.activity.length ? dashboard.activity.slice(0, 6).map((activity) => <div className="activity-item" key={activity.id}><div className="activity-mark" /><div><div className="activity-title">{activity.title}</div><div className="activity-detail">{activity.detail}</div><div className="activity-time">{new Date(activity.occurred_at).toLocaleString()}</div></div></div>) : <EmptyState title="No recent activity" detail="Events will appear as scenarios are reviewed." />}</div>
          </Surface>
        </div>
        <div style={{ marginTop: 15 }}><Surface title="Service signal summary" kicker="Synthetic histories · never production telemetry" action={<button className="button small" onClick={() => setSection("Services & Metrics")}>View metrics <ArrowRight size={12} /></button>}>
          <div className="surface-body" style={{ padding: 0 }}>{dashboard.services.slice(0, 4).map((service) => <div className="incident-row" key={service.id} onClick={() => setSection("Services & Metrics")} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSection("Services & Metrics"); }} role="button" tabIndex={0}><span className="incident-id">SVC-{String(service.id).padStart(3, "0")}</span><div><div className="incident-name">{service.name}</div><div className="incident-meta">{service.owner} · synthetic service</div></div><span className="status-pill">{service.status}</span></div>)}</div>
        </Surface></div>
      </>;
    }
    if (section === "Incidents") return <div className="split-layout">
      <Surface title="Scenario queue" kicker={`${filteredIncidents.length} synthetic incidents`} className="incident-index" action={<span className="simulation-tag">Synthetic</span>}>
        <div className="surface-body" style={{ padding: 12 }}>
          <div className="search-box" style={{ marginBottom: 9 }}><Search size={14} /><input aria-label="Search incidents" placeholder="Search scenarios…" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <label className="sr-only" htmlFor="severity-filter">Filter by severity</label>
          <select id="severity-filter" className="select" value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)} style={{ width: "100%" }}><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
        </div>
        {loading && !incidents.length ? <LoadingState /> : filteredIncidents.length ? <div className="incident-list">{filteredIncidents.map((incident) => <IncidentRow key={incident.id} incident={incident} selected={incident.id === selectedId} onClick={() => void selectIncident(incident.id)} />)}</div> : <EmptyState title="No matching scenarios" detail="Try another search or severity filter." icon={Filter} />}
      </Surface>
      <Surface title="Scenario details" kicker="All data in this workspace is simulated" className="incident-detail">
        {selected ? <><div className="detail-top"><div className="detail-heading"><div><span className="incident-id">INC-{String(selected.id).padStart(4, "0")} · {selected.service}</span><h2 className="detail-title">{selected.title}</h2></div><Status value={selected.status} /></div><p className="detail-summary">{selected.summary}</p><div style={{ marginTop: 13, display: "flex", gap: 8, flexWrap: "wrap" }}><button className="button small primary" onClick={() => setSection("Investigation")}>Open investigation <ArrowRight size={12} /></button><span className="simulation-tag">Synthetic scenario</span></div></div>
          <div className="detail-content"><h3>Evidence preview</h3>{investigationLoading ? <LoadingState /> : investigation?.evidence.slice(0, 3).map((item) => <div className="evidence-row" key={item.id}><div className="evidence-kind">{item.kind}</div><div><div className="evidence-msg">{item.message}</div><div className="evidence-source">{item.source}</div></div><div className="confidence">{item.confidence === null ? "—" : `${Math.round(item.confidence * 100)}%`}</div></div>) ?? <EmptyState title="Evidence unavailable" detail="Retry the investigation to load scenario evidence." />}</div></> : <EmptyState title="Select a scenario" detail="Incident details and evidence previews will appear here." />}
      </Surface>
    </div>;
    if (section === "Investigation") {
      if (investigationLoading) return <LoadingState />;
      if (!selected || !investigation) return <EmptyState title="Select an incident" detail="Choose a synthetic scenario from Incidents to open its investigation." icon={Search} />;
      return <div className="section-grid">
        <Surface title={selected.title} kicker={`INC-${String(selected.id).padStart(4, "0")} · ${selected.service}`} action={<SyntheticTag />}>
          <div className="surface-body"><div className="detail-heading"><Severity value={selected.severity} /><Status value={selected.status} /></div><p className="detail-summary" style={{ marginTop: 12 }}>{selected.summary}</p><div className="action-row" style={{ marginTop: 14 }}><button className="button small" onClick={() => setSection("Evidence Chain")}><GitBranch size={13} />Evidence chain</button><button className="button small" onClick={() => setSection("Knowledge Base")}><BookOpen size={13} />Runbooks</button><button className="button small" onClick={() => setSection("Remediation")}><ListChecks size={13} />Remediation</button></div></div>
        </Surface>
        <Surface title="Correlated evidence" kicker={`${investigation.evidence.length} synthetic records`} action={<button className="button small" onClick={() => setSection("Evidence Chain")}>View full chain <ArrowRight size={12} /></button>}>
          <div className="surface-body">{investigation.evidence.slice(0, 4).map((item) => <div className="evidence-row" key={item.id}><div className="evidence-kind">{item.kind}</div><div><div className="evidence-msg">{item.message}</div><div className="evidence-source">{item.source} · {new Date(item.observed_at).toLocaleTimeString()}</div></div><div className="confidence">{item.confidence === null ? "—" : `${Math.round(item.confidence * 100)}%`}</div></div>)}{!investigation.evidence.length && <EmptyState title="No correlated signals" detail="No evidence has been attached to this scenario." />}</div>
        </Surface>
        <Surface title="Related runbooks" kicker="Reference material · synthetic workspace" action={<button className="button small" onClick={() => setSection("Knowledge Base")}>Browse knowledge <ArrowRight size={12} /></button>}>
          <div className="surface-body">{investigation.runbooks.length ? investigation.runbooks.slice(0, 2).map((book) => <div className="runbook-card" key={book.id} style={{ marginBottom: 9 }}><h3 className="runbook-title">{book.title}</h3><div className="runbook-meta">{book.service}</div><p className="runbook-content">{book.content.slice(0, 240)}{book.content.length > 240 ? "…" : ""}</p></div>) : <EmptyState title="No related runbooks" detail="Search the knowledge base for applicable guidance." />}</div>
        </Surface>
        {aiInvestigation
          ? renderAIInvestigation(aiInvestigation, () => void runAIInvestigation(selected.id), aiActionLoading)
          : <Surface title="AI investigation" kicker="Evidence-first · advisory only" action={<button className="button small primary" onClick={() => void runAIInvestigation(selected.id)} disabled={aiActionLoading}>
            {aiActionLoading ? <LoaderCircle size={13} /> : <Sparkles size={13} />}{aiActionLoading ? "Investigating…" : "Run AI investigation"}
          </button>}>
            <div className="surface-body"><p className="detail-summary">Classifies the incident, retrieves approved references, proposes evidence-linked hypotheses, and saves a review-only report. Without AI credentials, deterministic agents still run.</p><div className="notice">Generated analysis cannot approve or execute a remediation.</div></div>
          </Surface>}
        <Surface title="Next operator step" kicker="Explicit human control">
          <div className="surface-body"><p className="detail-summary" style={{ marginBottom: 14 }}>Review the supporting evidence and reference material, then explicitly approve or reject the simulated proposal.</p><button className="button primary" onClick={() => setSection("Remediation")}>Review remediation <ArrowRight size={13} /></button></div>
        </Surface>
      </div>;
    }
    if (section === "Evidence Chain") return renderEvidence();
    if (section === "Root Cause") return renderRootCause();
    if (section === "Services & Metrics") return renderServices();
    if (section === "Checkout Simulation") return renderCheckoutSimulation();
    if (section === "Knowledge Base") return <KnowledgeBasePage />;
    if (section === "Remediation") return renderRemediation();
    if (section === "Postmortems") return <>
      <Surface title="Generate synthetic postmortem" kicker="Built from selected scenario context" action={<span className="simulation-tag">Synthetic only</span>}>
        <div className="surface-body"><div className="detail-heading"><div><div className="incident-name">{selected?.title ?? "No scenario selected"}</div><div className="incident-meta">{selected ? `INC-${String(selected.id).padStart(4, "0")} · ${selected.service}` : "Choose an incident before generation"}</div></div><button className="button primary" onClick={() => void generatePostmortem()} disabled={!selected || actionLoading}><Sparkles size={13} />{actionLoading ? "Generating…" : "Generate postmortem"}</button></div><div className="notice">Generated content is synthetic and intended for review. It is not an official incident record.</div></div>
      </Surface>
      <div style={{ marginTop: 14 }}><div className="surface-head" style={{ paddingLeft: 2, border: 0 }}><div><div className="surface-title">Generated reports</div><div className="surface-kicker">Every report is labeled synthetic</div></div></div>
        {loading && !postmortems.length ? <LoadingState /> : postmortems.length ? <div className="section-grid">{postmortems.map(renderPostmortem)}</div> : <Surface title="No reports yet"><EmptyState title="Nothing generated" detail="Choose a scenario above to create its synthetic postmortem." icon={FileText} /></Surface>}
      </div>
    </>;
    return <div className="settings-grid">
      <Surface title="Safety controls" kicker="Simulation workspace guardrails">
        <div className="surface-body">{[
          ["Operator approval", "Remediation decisions always require a human action."],
          ["Recovery check gate", "Recovery checks are available only after simulated approval."],
          ["Synthetic data labeling", "Simulation labels remain visible across the workspace."],
        ].map(([title, desc]) => <div className="setting-row" key={title}><div><div className="setting-name">{title}</div><div className="setting-desc">{desc}</div></div><span className="status-pill validated">Enforced</span></div>)}</div>
      </Surface>
      <Surface title="Workspace status" kicker="Connection and data posture">
        <div className="surface-body">
          <div className="setting-row"><div><div className="setting-name">API connection</div><div className="setting-desc">Workspace service health check</div></div><Status value={health === "ready" ? "ready" : health === "checking" ? "checking" : "unavailable"} /></div>
          <div className="setting-row"><div><div className="setting-name">Data source</div><div className="setting-desc">Seeded simulation data only</div></div><span className="simulation-tag">Synthetic</span></div>
          <div className="setting-row"><div><div className="setting-name">Infrastructure access</div><div className="setting-desc">No production control path</div></div><span className="status-pill">Not connected</span></div>
          <button className="button small" style={{ marginTop: 14 }} onClick={() => void load()}><RefreshCw size={13} />Refresh workspace status</button>
        </div>
      </Surface>
      <Surface title="About this workspace" kicker="Incident Commander">
        <div className="surface-body"><p className="detail-summary">A controlled environment for on-call SREs to practice incident review, evidence correlation, runbook consultation, simulated remediation decisions, recovery checks, and synthetic postmortem generation.</p><div className="notice">No live telemetry is displayed. No infrastructure changes can be made from this application.</div></div>
      </Surface>
    </div>;
  }

  return <div className="app-shell">
    <aside className="sidebar" aria-label="Primary navigation">
      <div className="brand"><div className="brand-mark"><Command size={18} /></div><div className="brand-copy"><div className="brand-title">INCIDENT<br />COMMANDER</div><div className="brand-sub">SRE workspace</div></div></div>
      <div className="workspace-label">Workspace</div>
      <nav className="nav-list">{sections.map(({ label, icon: Icon }) => <button key={label} className={`nav-item ${section === label ? "active" : ""}`} aria-current={section === label ? "page" : undefined} onClick={() => setSection(label)} title={label}><Icon size={15} /><span className="nav-label">{label}</span></button>)}</nav>
      <div className="side-bottom"><div className="sim-card"><div className="sim-title"><span className="sim-dot" />SIMULATION MODE</div><p>Seeded scenarios only. No production telemetry or infrastructure access.</p></div><div className="operator"><div className="operator-avatar">OC</div><div><div className="operator-name">On-call operator</div><div className="operator-role">SRE · Workspace</div></div></div></div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><ChevronRight size={12} /><strong>{section}</strong></div>
        <div className="top-meta"><SyntheticTag /><div className="health"><span className="health-light" style={{ background: health === "error" ? "var(--red)" : health === "checking" ? "var(--amber)" : "var(--green)" }} />{health === "ready" ? "API connected" : health === "checking" ? "Checking API" : "API unavailable"}</div><span className="top-time">SIM / {new Date().toLocaleDateString()}</span></div>
      </header>
      <div className="content">
        {error && <div className="error-banner" role="alert"><span><AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: 7 }} />{error}</span><button className="button small" onClick={() => section === "Checkout Simulation" ? void loadCheckout() : void load()}><RefreshCw size={12} />Retry</button></div>}
        {section !== "Knowledge Base" && <div className="page-head"><div><div className="eyebrow">Autonomous AI-powered incident commander</div><h1>{heading}</h1><p className="page-desc">{description}</p></div><div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}><SyntheticTag />{section === "Incidents" && <button className="button primary" onClick={() => setCreateOpen(true)}><Plus size={14} />Create scenario</button>}</div></div>}
        {renderMain()}
      </div>
    </main>
    {createOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCreateOpen(false); }}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
        <div className="modal-head"><div><h2 id="create-title">Create simulated incident</h2><div className="surface-kicker">This creates a synthetic scenario only</div></div><button className="button ghost small" aria-label="Close dialog" onClick={() => setCreateOpen(false)}><X size={15} /></button></div>
        <form className="modal-form" onSubmit={(event) => void createIncident(event)}>
          <div className="field"><label htmlFor="incident-title">Scenario title</label><input id="incident-title" name="title" required maxLength={120} placeholder="e.g. Elevated checkout latency" /></div>
          <div className="section-grid" style={{ gap: 10 }}><div className="field"><label htmlFor="incident-severity">Severity</label><select id="incident-severity" name="severity" defaultValue="medium"><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></div><div className="field"><label htmlFor="incident-service">Service</label><select id="incident-service" name="service_id" required defaultValue=""><option value="" disabled>Select a service</option>{services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></div></div>
          <div className="field"><label htmlFor="incident-summary">Scenario summary</label><textarea id="incident-summary" name="summary" required minLength={8} maxLength={1000} placeholder="Describe the simulated symptoms and context…" /></div>
          <div className="notice" style={{ marginTop: 0 }}>No production telemetry is used and no infrastructure can be modified.</div>
          <div className="modal-actions"><button type="button" className="button" onClick={() => setCreateOpen(false)}>Cancel</button><button className="button primary" type="submit" disabled={submitting || services.length === 0}>{submitting ? "Creating…" : services.length ? "Create scenario" : "No services available"}</button></div>
        </form>
      </section>
    </div>}
  </div>;
}