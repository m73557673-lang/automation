import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, BookOpen, Check, CheckCircle2, ChevronRight,
  CircleHelp, Command, FileText, Filter, GitBranch, ListChecks, LoaderCircle,
  Plus, RefreshCw, Search, Server, Settings2, ShieldCheck, ShoppingCart, Sparkles, X,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api, type CheckoutSimulationEvents, type CheckoutSimulationHealth, type CheckoutSimulationMetrics, type Dashboard, type Incident, type Investigation, type Postmortem, type Remediation, type Runbook, type Service } from "./api";

type Section = "Overview" | "Incidents" | "Investigation" | "Evidence Chain" | "Services & Metrics" | "Checkout Simulation" | "Knowledge Base" | "Remediation" | "Postmortems" | "Settings";
const sections: { label: Section; icon: typeof Activity }[] = [
  { label: "Overview", icon: Activity },
  { label: "Incidents", icon: AlertTriangle },
  { label: "Investigation", icon: Search },
  { label: "Evidence Chain", icon: GitBranch },
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
  "Services & Metrics": ["Services & metrics", "Scenario metric histories. These charts are simulated, not production telemetry."],
  "Checkout Simulation": ["Checkout simulation", "Practice checkout incident response against deterministic, synthetic service signals."],
  "Knowledge Base": ["Knowledge base", "Search operational guidance for the selected service and scenario."],
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
  const [runbooks, setRunbooks] = useState<Runbook[]>([]);
  const [postmortems, setPostmortems] = useState<Postmortem[]>([]);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [health, setHealth] = useState<"checking" | "ready" | "error">("checking");
  const [loading, setLoading] = useState(true);
  const [investigationLoading, setInvestigationLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [checkoutMetrics, setCheckoutMetrics] = useState<CheckoutSimulationMetrics | null>(null);
  const [checkoutHealth, setCheckoutHealth] = useState<CheckoutSimulationHealth | null>(null);
  const [checkoutEvents, setCheckoutEvents] = useState<CheckoutSimulationEvents | null>(null);
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [checkoutActionLoading, setCheckoutActionLoading] = useState(false);
  const checkoutRequested = useRef(false);
  const selectedIdRef = useRef<number | null>(selectedId);
  selectedIdRef.current = selectedId;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const results = await Promise.allSettled([
      api.dashboard(), api.incidents(), api.services(), api.knowledge(""), api.postmortems(), api.health(),
    ]);
    const labels = ["dashboard", "incidents", "services", "knowledge base", "postmortems", "workspace health"];
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
      if (index === 3) setRunbooks(value as Runbook[]);
      if (index === 4) setPostmortems(value as Postmortem[]);
      if (index === 5) setHealth("ready");
    });
    if (results[5].status === "rejected") setHealth("error");
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
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  const loadCheckout = useCallback(async () => {
    setCheckoutLoading(true);
    setError("");
    const results = await Promise.allSettled([
      api.checkoutSimulation(), api.checkoutSimulationHealth(), api.checkoutSimulationEvents(),
    ]);
    let failed = "";
    if (results[0].status === "fulfilled") setCheckoutMetrics(results[0].value);
    else failed ||= `Could not load checkout metrics: ${results[0].reason instanceof Error ? results[0].reason.message : "Request failed"}`;
    if (results[1].status === "fulfilled") setCheckoutHealth(results[1].value);
    else failed ||= `Could not load checkout health: ${results[1].reason instanceof Error ? results[1].reason.message : "Request failed"}`;
    if (results[2].status === "fulfilled") setCheckoutEvents(results[2].value);
    else failed ||= `Could not load checkout events: ${results[2].reason instanceof Error ? results[2].reason.message : "Request failed"}`;
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
    setInvestigationLoading(true);
    setError("");
    try { setInvestigation(await api.investigation(id)); }
    catch (reason) { setInvestigation(null); setError(reason instanceof Error ? reason.message : "Could not load this investigation."); }
    finally { setInvestigationLoading(false); }
  }, []);

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

  async function searchKnowledge(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setKnowledgeLoading(true);
    setError("");
    try { setRunbooks(await api.knowledge(knowledgeQuery)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not search the knowledge base."); }
    finally { setKnowledgeLoading(false); }
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

  function renderEvidence() {
    if (investigationLoading) return <LoadingState />;
    if (!selected) return <EmptyState title="Select an incident" detail="Choose a scenario from the incident queue to inspect its evidence chain." icon={GitBranch} />;
    if (!investigation) return <EmptyState title="Investigation unavailable" detail="Retry the selected scenario to load its synthetic evidence." icon={AlertTriangle} />;
    return <>
      <div className="chain surface" style={{ padding: 16, marginBottom: 14 }}>
        {[
          ["01", "Scenario", "Seeded incident context"],
          ["02", "Signals", `${investigation.evidence.length} correlated evidence items`],
          ["03", "Guidance", `${investigation.runbooks.length} related runbooks`],
          ["04", "Decision", investigation.remediation ? `Remediation ${investigation.remediation.state}` : "Awaiting operator review"],
        ].map(([number, label, sub]) => <div className="chain-step" key={number}><div className="chain-top"><div className="chain-num">{number}</div><span className="chain-label">{label}</span></div><div className="chain-sub">{sub}</div></div>)}
      </div>
      <Surface title={`${investigation.evidence.length} evidence records`} kicker={`${selected.title} · simulated`} action={<SyntheticTag />}>
        <div className="surface-body">{investigation.evidence.length ? investigation.evidence.map((item) => <div className="evidence-row" key={item.id}>
          <div className="evidence-kind">{item.kind}</div>
          <div><div className="evidence-msg">{item.message}</div><div className="evidence-source">{item.source} · {new Date(item.observed_at).toLocaleString()}</div></div>
          <div className="confidence">{item.confidence === null ? "—" : `${Math.round(item.confidence * 100)}% conf.`}</div>
        </div>) : <EmptyState title="No evidence recorded" detail="This synthetic scenario has no evidence records yet." />}</div>
      </Surface>
      <Surface title="Metric snapshots" kicker={`${investigation.metrics.length} records · local database`}>
        <div className="surface-body">{investigation.metrics.length ? investigation.metrics.map((metric) => <div className="activity-item" key={metric.id}>
          <div className="activity-mark" /><div><div className="activity-title">{metric.metric_name.replace(/_/g, " ")}</div>
            <div className="activity-detail">{metric.value} · {new Date(metric.timestamp).toLocaleString()}</div></div>
        </div>) : <EmptyState title="No metric snapshots" detail="No metric records are linked to this incident's service and time window." />}</div>
      </Surface>
    </>;
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
        <Surface title="Next operator step" kicker="Explicit human control">
          <div className="surface-body"><p className="detail-summary" style={{ marginBottom: 14 }}>Review the supporting evidence and reference material, then explicitly approve or reject the simulated proposal.</p><button className="button primary" onClick={() => setSection("Remediation")}>Review remediation <ArrowRight size={13} /></button></div>
        </Surface>
      </div>;
    }
    if (section === "Evidence Chain") return renderEvidence();
    if (section === "Services & Metrics") return renderServices();
    if (section === "Checkout Simulation") return renderCheckoutSimulation();
    if (section === "Knowledge Base") return <>
      <Surface title="Runbook search" kicker="Synthetic operational reference">
        <form className="surface-body" onSubmit={(event) => void searchKnowledge(event)} style={{ display: "flex", gap: 9 }}>
          <div className="search-box" style={{ flex: 1 }}><Search size={14} /><input aria-label="Search runbooks" placeholder="Search by service, tag, or topic…" value={knowledgeQuery} onChange={(event) => setKnowledgeQuery(event.target.value)} /></div>
          <button className="button primary" type="submit" disabled={knowledgeLoading}>{knowledgeLoading ? <LoaderCircle size={14} /> : <Search size={14} />}Search</button>
        </form>
      </Surface>
      <div style={{ marginTop: 14 }}>{knowledgeLoading ? <LoadingState /> : runbooks.length ? <div className="section-grid">{runbooks.map((book) => <article className="runbook-card" key={book.id}><div className="runbook-meta">{book.service} · Runbook {String(book.id).padStart(3, "0")}</div><h3 className="runbook-title" style={{ marginTop: 8 }}>{book.title}</h3><p className="runbook-content">{book.content}</p><div className="tag-row">{book.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div></article>)}</div> : <EmptyState title="No matching guidance" detail="Try a broader service name or operational keyword." icon={BookOpen} />}</div>
    </>;
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
        <div className="page-head"><div><div className="eyebrow">Autonomous AI-powered incident commander</div><h1>{heading}</h1><p className="page-desc">{description}</p></div><div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}><SyntheticTag />{section === "Incidents" && <button className="button primary" onClick={() => setCreateOpen(true)}><Plus size={14} />Create scenario</button>}</div></div>
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