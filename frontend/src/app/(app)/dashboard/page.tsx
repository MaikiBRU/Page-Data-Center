"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch, API_URL } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { Topbar } from "@/components/Topbar";
import { OnboardingModal } from "@/components/OnboardingModal";
import { FlowSteps } from "@/components/FlowSteps";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { emitToast } from "@/lib/toast";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";

interface Dataset {
  id: number;
  name: string;
  domain: string;
  source_type: string;
  created_at: string;
  last_run_at?: string | null;
}

interface InsightSeries {
  label: string;
  value: number;
}

interface InsightsResponse {
  issues_by_code: InsightSeries[];
  issues_by_code_all: InsightSeries[];
  issues_by_severity: InsightSeries[];
  anomalies_by_field: InsightSeries[];
  anomalies_by_field_all: InsightSeries[];
  runs_last_7_days: { date: string; runs: number }[];
  dataset_health: { id: number; name: string; score: number; last_run_at?: string | null }[];
}

interface DashboardKpis {
  datasets: number;
  open_cases: number;
  issues: number;
  impact_estimated: number;
  risk_score: number;
  risk_level: string;
  week: {
    runs: { current: number; previous: number; delta_pct: number };
    issues: { current: number; previous: number; delta_pct: number };
    anomalies: { current: number; previous: number; delta_pct: number };
    impact: { current: number; previous: number; delta_pct: number };
    risk_score: { current: number; previous: number; delta_pct: number };
    cases: { current: number; previous: number; delta_pct: number };
  };
}

const COLORS = ["#ff7a1a", "#ffb36a", "#d8843a", "#b55a28", "#6f7785", "#9aa0aa"];

export default function DashboardPage() {
  const router = useRouter();
  const [kpis, setKpis] = useState<DashboardKpis>({
    datasets: 0,
    open_cases: 0,
    issues: 0,
    impact_estimated: 0,
    risk_score: 0,
    risk_level: "bajo",
    week: {
      runs: { current: 0, previous: 0, delta_pct: 0 },
      issues: { current: 0, previous: 0, delta_pct: 0 },
      anomalies: { current: 0, previous: 0, delta_pct: 0 },
      impact: { current: 0, previous: 0, delta_pct: 0 },
      risk_score: { current: 0, previous: 0, delta_pct: 0 },
      cases: { current: 0, previous: 0, delta_pct: 0 },
    },
  });
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoResetting, setDemoResetting] = useState(false);
  const [demoRegenerating, setDemoRegenerating] = useState(false);
  const [me, setMe] = useState<{ is_admin: boolean; role?: string } | null>(null);
  const [activeModal, setActiveModal] = useState<
    | "runs"
    | "severity"
    | "issues"
    | "anomalies"
    | "datasets"
    | "health"
    | null
  >(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [exporting, setExporting] = useState<"json" | "csv" | "html" | null>(null);
  const flow = useFlowData();

  const loadDashboard = async () => {
    setLoading(true);
    await Promise.allSettled([
      apiFetch<DashboardKpis>("/dashboard/kpis").then(setKpis),
      apiFetch<Dataset[]>("/datasets").then(setDatasets),
      apiFetch<InsightsResponse>("/dashboard/insights").then(setInsights),
      apiFetch<{ is_admin: boolean; role?: string }>("/auth/me").then(setMe),
    ]);
    setLoading(false);
  };

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    loadDashboard();
  }, [router]);

  useEffect(() => {
    if (loading) return;
    if (typeof window === "undefined") return;
    const key = "dq_onboarding_done";
    const done = window.localStorage.getItem(key);
    if (!done && datasets.length === 0) {
      setShowOnboarding(true);
    }
  }, [loading, datasets.length]);

  const healthList = useMemo(() => insights?.dataset_health ?? [], [insights]);
  const totalRuns = useMemo(
    () => (insights?.runs_last_7_days ?? []).reduce((acc, item) => acc + item.runs, 0),
    [insights]
  );
  const canDemo = me?.is_admin || me?.role === "analyst";
  const demoCount = useMemo(
    () => datasets.filter((dataset) => dataset.name.toLowerCase().includes("demo")).length,
    [datasets]
  );
  const formatCurrency = (value: number) =>
    new Intl.NumberFormat("es-AR", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(value || 0);
  const formatDelta = (value: number) => `${value >= 0 ? "+" : ""}${value}%`;
  const deltaClass = (value: number) =>
    value >= 0 ? "text-[var(--success)]" : "text-[var(--danger)]";
  const riskBadge = (level: string) => {
    if (level === "alto") {
      return "border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]";
    }
    if (level === "medio") {
      return "border-[var(--warning)]/50 bg-[var(--warning)]/10 text-[var(--warning)]";
    }
    return "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]";
  };
  const formatDate = (value?: string | null) => {
    if (!value) return "Pendiente";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    }).format(date);
  };

  const chartHeight = "h-[22.5rem]";
  const modalChartHeight = "h-[28rem]";

  const createDemo = async () => {
    if (!(me?.is_admin || me?.role === "analyst")) {
      emitToast({ message: "No tenés permisos para crear demo.", kind: "error" });
      return;
    }
    if (demoCount > 0) {
      emitToast({ message: "Ya existe una demo. Usá regenerar o reset.", kind: "info" });
      return;
    }
    setDemoLoading(true);
    try {
      const demoSets = [
        { name: "Pedidos ecommerce demo", domain: "ecommerce" },
        { name: "Logística última milla demo", domain: "logistica" },
        { name: "Operación integrada demo", domain: "ecommerce-logistica" },
      ];
      for (const item of demoSets) {
        const created = await apiFetch<Dataset>("/datasets", {
          method: "POST",
          body: JSON.stringify(item),
        });
        await apiFetch(`/datasets/${created.id}/generate`, {
          method: "POST",
          body: JSON.stringify({ rows: 400, anomaly_rate: 0.12 }),
        });
        await apiFetch(`/datasets/${created.id}/run-quality`, { method: "POST" });
      }
      emitToast({ message: "Demo generada con éxito.", kind: "success" });
      await loadDashboard();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setDemoLoading(false);
    }
  };

  const resetDemo = async () => {
    if (!canDemo) {
      emitToast({ message: "No tenés permisos para resetear demo.", kind: "error" });
      return;
    }
    if (!window.confirm("¿Querés eliminar todos los datasets demo?")) return;
    setDemoResetting(true);
    try {
      await apiFetch("/dashboard/demo/reset", { method: "POST" });
      emitToast({ message: "Demo eliminada.", kind: "success" });
      await loadDashboard();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setDemoResetting(false);
    }
  };

  const regenerateDemo = async () => {
    if (!canDemo) {
      emitToast({ message: "No tenés permisos para regenerar demo.", kind: "error" });
      return;
    }
    setDemoRegenerating(true);
    try {
      await apiFetch("/dashboard/demo/regenerate", { method: "POST" });
      emitToast({ message: "Demo regenerada.", kind: "success" });
      await loadDashboard();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setDemoRegenerating(false);
    }
  };

  const downloadReport = async (format: "json" | "csv" | "html") => {
    const token = getToken();
    if (!token) return;
    setExporting(format);
    try {
      const response = await fetch(`${API_URL}/dashboard/report?format=${format}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("No se pudo exportar el reporte");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `dashboard_report_${stamp}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
      emitToast({ message: "Reporte descargado.", kind: "success" });
      setShowExport(false);
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setExporting(null);
    }
  };

  const openHtmlReport = async () => {
    const token = getToken();
    if (!token) return;
    setExporting("html");
    try {
      const response = await fetch(`${API_URL}/dashboard/report?format=html`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("No se pudo abrir el reporte");
      }
      const html = await response.text();
      const blob = new Blob([html], { type: "text/html" });
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank");
      emitToast({ message: "Reporte abierto.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setExporting(null);
    }
  };

  const onboardingSteps = [
    {
      title: "Crear dataset",
      description: "Definí el origen y el dominio para empezar a monitorear.",
      ctaLabel: "Ir a Datasets",
      href: "/datasets",
    },
    {
      title: "Subir o generar datos",
      description: "Cargá un CSV real o generá datos simulados con anomalías.",
      ctaLabel: "Ver detalle",
      href: "/datasets",
    },
    {
      title: "Ejecutar calidad",
      description: "Corré reglas y anomalías para producir issues y casos.",
      ctaLabel: "Correr calidad",
      href: "/datasets",
    },
    {
      title: "Gestionar casos",
      description: "Asigná responsables, SLA y estados para resolver incidencias.",
      ctaLabel: "Ver Casos",
      href: "/cases",
    },
    {
      title: "Aplicar recomendaciones",
      description: "Convertí recomendaciones en casos y medí impacto.",
      ctaLabel: "Ver Recomendaciones",
      href: "/recommendations",
    },
  ];

  return (
    <div className="flex flex-col gap-8">
      <Topbar
        title="Salud general"
        onGuide={() => setShowOnboarding(true)}
        onExport={() => setShowExport(true)}
      />

      <FlowSteps flow={flow} onGuide={() => setShowOnboarding(true)} />

      <OnboardingCoach
        flow={flow}
        stepKey="datasets"
        title="Creá tu primer dataset"
        description="Definí el origen y el dominio para empezar el monitoreo."
        actionLabel="Crear dataset"
        href="/datasets#dataset-create"
      />

      <section className="grid gap-6 md:grid-cols-3 xl:grid-cols-5 items-stretch">
        <div className="panel kpi-card h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Datasets</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-4 text-3xl font-semibold">{kpis.datasets}</p>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm text-[var(--muted)]">
            <span className="badge">Activos</span>
            <span>Orígenes monitoreados</span>
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-white/60">
              Corridas semana: {kpis.week.runs.current}{" "}
              <span className={deltaClass(kpis.week.runs.delta_pct)}>
                {formatDelta(kpis.week.runs.delta_pct)}
              </span>
            </p>
          )}
        </div>
        <div className="panel kpi-card h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Alertas abiertas</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-4 text-3xl font-semibold">{kpis.open_cases}</p>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm text-[var(--muted)]">
            <span className="badge">Prioridad</span>
            <span>Casos pendientes</span>
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-white/60">
              Nuevos casos: {kpis.week.cases.current}{" "}
              <span className={deltaClass(kpis.week.cases.delta_pct)}>
                {formatDelta(kpis.week.cases.delta_pct)}
              </span>
            </p>
          )}
        </div>
        <div className="panel kpi-card h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Issues detectados</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-4 text-3xl font-semibold">{kpis.issues}</p>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm text-[var(--muted)]">
            <span className="badge">7 días</span>
            <span>{totalRuns} corridas</span>
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-white/60">
              Issues semana: {kpis.week.issues.current}{" "}
              <span className={deltaClass(kpis.week.issues.delta_pct)}>
                {formatDelta(kpis.week.issues.delta_pct)}
              </span>
            </p>
          )}
        </div>
        <div className="panel kpi-card h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Impacto estimado</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-32" />
          ) : (
            <p className="mt-4 text-2xl font-semibold">{formatCurrency(kpis.impact_estimated)}</p>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm text-[var(--muted)]">
            <span className="badge">Riesgo $</span>
            <span>Exposición estimada</span>
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-white/60">
              Semana: {formatCurrency(kpis.week.impact.current)}{" "}
              <span className={deltaClass(kpis.week.impact.delta_pct)}>
                {formatDelta(kpis.week.impact.delta_pct)}
              </span>
            </p>
          )}
        </div>
        <div className="panel kpi-card h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Riesgo operativo</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <div className="mt-4 flex items-center gap-3">
              <p className="text-3xl font-semibold">{Math.round(kpis.risk_score)}</p>
              <span className={`badge ${riskBadge(kpis.risk_level)}`}>
                {kpis.risk_level.toUpperCase()}
              </span>
            </div>
          )}
          <div className="mt-4 flex items-center gap-3 text-sm text-[var(--muted)]">
            <span className="badge">Score</span>
            <span>0 a 100</span>
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-white/60">
              Semana: {Math.round(kpis.week.risk_score.current)}{" "}
              <span className={deltaClass(kpis.week.risk_score.delta_pct)}>
                {formatDelta(kpis.week.risk_score.delta_pct)}
              </span>
            </p>
          )}
        </div>
      </section>

      {!loading && (
        <section className="panel flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Demo</p>
            <h3 className="mt-2 text-lg font-semibold">Control de demo</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              {demoCount > 0
                ? `${demoCount} datasets demo activos.`
                : "Todavía no hay datasets demo cargados."}
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              className="btn-secondary"
              onClick={createDemo}
              disabled={demoLoading || !canDemo}
            >
              {demoLoading ? "Generando demo..." : "Cargar demo"}
            </button>
            <button
              className="btn-secondary"
              onClick={regenerateDemo}
              disabled={demoRegenerating || demoCount === 0 || !canDemo}
            >
              {demoRegenerating ? "Regenerando..." : "Regenerar demo"}
            </button>
            <button
              className="btn-primary"
              onClick={resetDemo}
              disabled={demoResetting || demoCount === 0 || !canDemo}
            >
              {demoResetting ? "Reseteando..." : "Reset demo"}
            </button>
          </div>
          {me && !canDemo && (
            <p className="text-xs text-[var(--muted)]">
              Solo administradores o analistas pueden gestionar la demo.
            </p>
          )}
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-2 items-stretch">
        <div className="panel h-full flex flex-col">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Actividad</p>
              <h3 className="mt-2 text-xl font-semibold">Corridas últimos 7 días</h3>
            </div>
            <span className="badge">{totalRuns} runs</span>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.runs_last_7_days ?? []).length === 0 ? (
              <div className="chart-empty h-full flex-col gap-3">
                <EmptyState
                  title="Sin datos de corridas aún."
                  description="Ejecutá calidad para generar historial."
                  actions={[{ label: "Ejecutar calidad", href: "/datasets", variant: "secondary" }]}
                  compact
                />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={insights?.runs_last_7_days ?? []}>
                  <defs>
                  <linearGradient id="runs" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff7a1a" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#ff7a1a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "#9fb0c9", fontSize: 11 }}
                    tickFormatter={(value) => value.slice(5)}
                  />
                  <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                  />
                  <Area
                    type="monotone"
                    dataKey="runs"
                    stroke="#ff7a1a"
                    fill="url(#runs)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-6 flex justify-end">
            <button className="btn-mini" onClick={() => setActiveModal("runs")}>
              Ver todo
            </button>
          </div>
        </div>

        <div className="panel h-full flex flex-col">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Calidad</p>
            <h3 className="mt-2 text-xl font-semibold">Issues por severidad</h3>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.issues_by_severity ?? []).length === 0 ? (
              <div className="chart-empty h-full">
                <EmptyState
                  title="Sin issues calculados."
                  description="Corré calidad para ver severidades."
                  actions={[{ label: "Ir a Datasets", href: "/datasets", variant: "secondary" }]}
                  compact
                />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={insights?.issues_by_severity ?? []}
                    dataKey="value"
                    nameKey="label"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={4}
                  >
                    {(insights?.issues_by_severity ?? []).map((entry, index) => (
                      <Cell key={`cell-${entry.label}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          {!loading && (
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-white/70">
              {(insights?.issues_by_severity ?? []).map((item, index) => (
                <div key={item.label} className="flex items-center gap-2">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: COLORS[index % COLORS.length] }}
                  />
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-6 flex justify-end">
            <button className="btn-mini" onClick={() => setActiveModal("severity")}>
              Ver todo
            </button>
          </div>
        </div>
      </section>

      {!loading && datasets.length === 0 && (
        <section className="panel grid gap-4 md:grid-cols-[1.2fr_0.8fr] items-center">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Primeros pasos</p>
            <h3 className="mt-2 text-xl font-semibold">Configurá tu primer dataset</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Creá una fuente para empezar a correr calidad y generar casos.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 justify-end">
            <Link className="btn-secondary" href="/datasets">
              Crear dataset
            </Link>
            <Link className="btn-primary" href="/datasets">
              Subir datos
            </Link>
            <button
              className="btn-secondary"
              onClick={createDemo}
              disabled={demoLoading || !canDemo}
            >
              {demoLoading ? "Generando demo..." : "Cargar demo"}
            </button>
          </div>
          {me && !canDemo && (
            <p className="text-xs text-[var(--muted)] md:col-span-2">
              Solo administradores o analistas pueden cargar demos.
            </p>
          )}
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-2 items-stretch">
        <div className="panel h-full flex flex-col">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Issues</p>
            <h3 className="mt-2 text-xl font-semibold">Top issues por tipo</h3>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.issues_by_code ?? []).length === 0 ? (
              <div className="chart-empty h-full">
                <EmptyState
                  title="Sin issues por tipo."
                  description="Generá issues con una corrida."
                  actions={[{ label: "Ejecutar calidad", href: "/datasets", variant: "secondary" }]}
                  compact
                />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={insights?.issues_by_code ?? []}>
                  <XAxis dataKey="label" tick={{ fill: "#9fb0c9", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                  />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {(insights?.issues_by_code ?? []).map((entry, index) => (
                      <Cell key={`cell-${entry.label}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-6 flex justify-end">
            <button className="btn-mini" onClick={() => setActiveModal("issues")}>
              Ver todo
            </button>
          </div>
        </div>

        <div className="panel h-full flex flex-col">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Anomalías</p>
            <h3 className="mt-2 text-xl font-semibold">Anomalías por campo</h3>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.anomalies_by_field ?? []).length === 0 ? (
              <div className="chart-empty h-full">
                <EmptyState
                  title="Sin anomalías destacadas."
                  description="Corré calidad para detectar outliers."
                  actions={[{ label: "Ir a Datasets", href: "/datasets", variant: "secondary" }]}
                  compact
                />
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={insights?.anomalies_by_field ?? []}>
                  <XAxis dataKey="label" tick={{ fill: "#9fb0c9", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                  />
                  <Bar dataKey="value" fill="#ff7a1a" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-6 flex justify-end">
            <button className="btn-mini" onClick={() => setActiveModal("anomalies")}>
              Ver todo
            </button>
          </div>
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2 items-stretch">
        <div className="panel h-full flex flex-col">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Datasets</p>
              <h3 className="mt-2 text-xl font-semibold">Monitoreo reciente</h3>
            </div>
            <Link className="btn-secondary" href="/datasets">
              Ver todos
            </Link>
          </div>
          <div className="mt-6 grid gap-3 flex-1">
            {loading ? (
              Array.from({ length: 3 }).map((_, index) => (
                <div key={`ds-skel-${index}`} className="skeleton h-16" />
              ))
            ) : datasets.length === 0 ? (
              <EmptyState
                title="No hay datasets aún."
                description="Creá uno para ver monitoreo reciente."
                actions={[{ label: "Crear dataset", href: "/datasets", variant: "secondary" }]}
                compact
              />
            ) : (
              datasets.slice(0, 4).map((dataset) => (
                <div key={dataset.id} className="card-row">
                  <div>
                    <p className="text-white">{dataset.name}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {dataset.domain} · {dataset.source_type}
                    </p>
                  </div>
                  <div className="text-xs text-white/50">
                    Última corrida: {formatDate(dataset.last_run_at)}
                  </div>
                  <Link className="btn-secondary" href={`/datasets/${dataset.id}`}>
                    Ver detalle
                  </Link>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="panel h-full flex flex-col">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Salud por dataset</p>
            <h3 className="mt-2 text-xl font-semibold">Score de calidad</h3>
          </div>
          <div className="mt-6 grid gap-3 flex-1">
            {loading ? (
              Array.from({ length: 3 }).map((_, index) => (
                <div key={`health-skel-${index}`} className="skeleton h-16" />
              ))
            ) : healthList.length === 0 ? (
              <EmptyState
                title="Sin corridas aún."
                description="Ejecutá calidad para ver score."
                actions={[{ label: "Ejecutar calidad", href: "/datasets", variant: "secondary" }]}
                compact
              />
            ) : (
              healthList.map((dataset) => (
                <div key={dataset.id} className="card-box">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{dataset.name}</p>
                    <p className="text-xs text-white/50">{Math.round(dataset.score)}%</p>
                  </div>
                  <div className="mt-2 h-2 w-full rounded-full bg-white/10">
                    <div
                      className="h-2 rounded-full bg-[var(--accent)]"
                      style={{ width: `${Math.round(dataset.score)}%` }}
                    />
                  </div>
                  {dataset.last_run_at && (
                    <p className="mt-2 text-xs text-[var(--muted)]">
                      Última corrida: {formatDate(dataset.last_run_at)}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
          <div className="mt-6 flex justify-end">
            <button className="btn-mini" onClick={() => setActiveModal("health")}>
              Ver todo
            </button>
          </div>
        </div>
      </section>
      {activeModal && (
        <div className="modal-backdrop">
          <div className="modal-panel relative max-h-[85vh] w-[92vw] max-w-5xl overflow-hidden ring-1 ring-white/10">
            <button
              className="absolute right-6 top-6 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
              onClick={() => setActiveModal(null)}
            >
              Cerrar
            </button>
            <div className="scroll-soft flex flex-col gap-6 overflow-auto pr-2 max-h-[75vh]">
              {activeModal === "runs" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Actividad</p>
                  <h3 className="mt-2 text-xl font-semibold">Corridas últimos 7 días</h3>
                  <div className={`mt-6 ${modalChartHeight}`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={insights?.runs_last_7_days ?? []}>
                        <defs>
                          <linearGradient id="runs-modal" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#ff7a1a" stopOpacity={0.7} />
                            <stop offset="95%" stopColor="#ff7a1a" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <XAxis
                          dataKey="date"
                          tick={{ fill: "#9fb0c9", fontSize: 11 }}
                          tickFormatter={(value) => value.slice(5)}
                        />
                        <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                        />
                        <Area
                          type="monotone"
                          dataKey="runs"
                          stroke="#ff7a1a"
                          fill="url(#runs-modal)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {activeModal === "severity" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Calidad</p>
                  <h3 className="mt-2 text-xl font-semibold">Issues por severidad</h3>
                  <div className={`mt-6 ${modalChartHeight}`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={insights?.issues_by_severity ?? []}
                          dataKey="value"
                          nameKey="label"
                          innerRadius={80}
                          outerRadius={120}
                          paddingAngle={4}
                        >
                          {(insights?.issues_by_severity ?? []).map((entry, index) => (
                            <Cell key={`modal-${entry.label}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {activeModal === "issues" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Issues</p>
                  <h3 className="mt-2 text-xl font-semibold">Todos los issues</h3>
                  <div className={`mt-6 ${modalChartHeight}`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={insights?.issues_by_code_all ?? []}>
                        <XAxis dataKey="label" tick={{ fill: "#9fb0c9", fontSize: 10 }} />
                        <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                        />
                        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                          {(insights?.issues_by_code_all ?? []).map((entry, index) => (
                            <Cell key={`modal-${entry.label}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {activeModal === "anomalies" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Anomalías</p>
                  <h3 className="mt-2 text-xl font-semibold">Todas las anomalías</h3>
                  <div className={`mt-6 ${modalChartHeight}`}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={insights?.anomalies_by_field_all ?? []}>
                        <XAxis dataKey="label" tick={{ fill: "#9fb0c9", fontSize: 10 }} />
                        <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} />
                        <Tooltip
                          contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }}
                        />
                        <Bar dataKey="value" fill="#ff7a1a" radius={[6, 6, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {activeModal === "datasets" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Datasets</p>
                  <h3 className="mt-2 text-xl font-semibold">Todos los datasets</h3>
                  <div className="mt-4 grid gap-3">
                    {datasets.map((dataset) => (
                      <div key={dataset.id} className="card-row">
                        <div>
                          <p className="text-white">{dataset.name}</p>
                          <p className="text-xs text-[var(--muted)]">
                            {dataset.domain} · {dataset.source_type}
                          </p>
                        </div>
                        <p className="text-xs text-white/50">
                          Última corrida: {formatDate(dataset.last_run_at)}
                        </p>
                        <Link className="btn-secondary" href={`/datasets/${dataset.id}`}>
                          Abrir
                        </Link>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {activeModal === "health" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Salud</p>
                  <h3 className="mt-2 text-xl font-semibold">Score de calidad</h3>
                  <div className="mt-4 grid gap-3">
                    {healthList.map((dataset) => (
                      <div key={dataset.id} className="card-box">
                        <div className="flex items-center justify-between">
                          <p className="font-medium">{dataset.name}</p>
                          <p className="text-xs text-white/50">{Math.round(dataset.score)}%</p>
                        </div>
                        <div className="mt-2 h-2 w-full rounded-full bg-white/10">
                          <div
                            className="h-2 rounded-full bg-[var(--accent)]"
                            style={{ width: `${Math.round(dataset.score)}%` }}
                          />
                        </div>
                        {dataset.last_run_at && (
                          <p className="mt-2 text-xs text-[var(--muted)]">
                            Última corrida: {formatDate(dataset.last_run_at)}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <OnboardingModal
        open={showOnboarding}
        steps={onboardingSteps}
        onClose={() => setShowOnboarding(false)}
        onDone={() => {
          if (typeof window !== "undefined") {
            window.localStorage.setItem("dq_onboarding_done", "1");
          }
          setShowOnboarding(false);
        }}
      />

      {showExport && (
        <div className="modal-backdrop">
          <div className="modal-panel max-w-md space-y-4">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Reporte</p>
              <h3 className="mt-2 text-xl font-semibold">Exportar reporte general</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Incluye KPIs, comparativas y salud por dataset.
              </p>
            </div>
            <div className="grid gap-3">
              <button
                className="btn-primary"
                onClick={() => downloadReport("json")}
                disabled={exporting !== null}
              >
                {exporting === "json" ? "Descargando..." : "Descargar JSON"}
              </button>
              <button
                className="btn-secondary"
                onClick={() => downloadReport("csv")}
                disabled={exporting !== null}
              >
                {exporting === "csv" ? "Descargando..." : "Descargar CSV"}
              </button>
              <button
                className="btn-secondary"
                onClick={() => downloadReport("html")}
                disabled={exporting !== null}
              >
                {exporting === "html" ? "Descargando..." : "Descargar HTML"}
              </button>
              <button
                className="btn-secondary"
                onClick={openHtmlReport}
                disabled={exporting !== null}
              >
                Abrir reporte en navegador
              </button>
            </div>
            <div className="flex justify-end">
              <button className="btn-secondary" onClick={() => setShowExport(false)}>
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
