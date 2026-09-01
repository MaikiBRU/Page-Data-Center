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
import { entryPath } from "@/lib/demo";
import { Topbar } from "@/components/Topbar";
import { OnboardingModal } from "@/components/OnboardingModal";
import { FlowSteps } from "@/components/FlowSteps";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { emitToast } from "@/lib/toast";
import { can } from "@/lib/permissions";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { useEscapeKey } from "@/lib/useEscapeKey";

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
  dataset_health: {
    id: number;
    name: string;
    /** Quality score. null when nothing was measured for this dataset. */
    score: number | null;
    total_rows: number;
    rows_affected: number | null;
    critical_rows: number | null;
    /** "compatible" | "warning" | "incompatible", null if never analysed. */
    schema_status?: string | null;
    last_run_at?: string | null;
  }[];
}

interface QualityTrend {
  current: number;
  previous: number;
  /** Difference in percentage points, not a percent change. */
  delta_points: number;
  datasets_compared: number;
}

interface DashboardKpis {
  datasets: number;
  datasets_analyzed: number;
  datasets_measured: number;
  total_rows: number;
  rows_affected: number;
  rows_affected_pct: number;
  critical_rows: number;
  critical_rows_pct: number;
  quality_score: number;
  /** Distinct (rule, field) findings. Not a row count. */
  findings: number;
  /** Total rule firings. A row breaking three rules adds three. */
  rule_violations: number;
  anomalies: number;
  open_cases: number;
  /** null when no dataset has two runs to compare. */
  quality_trend: QualityTrend | null;
}

const COLORS = ["#ff7a1a", "#ffb36a", "#d8843a", "#b55a28", "#6f7785", "#9aa0aa"];

export default function DashboardPage() {
  const router = useRouter();
  const [kpis, setKpis] = useState<DashboardKpis>({
    datasets: 0,
    datasets_analyzed: 0,
    datasets_measured: 0,
    total_rows: 0,
    rows_affected: 0,
    rows_affected_pct: 0,
    critical_rows: 0,
    critical_rows_pct: 0,
    quality_score: 0,
    findings: 0,
    rule_violations: 0,
    anomalies: 0,
    open_cases: 0,
    quality_trend: null,
  });
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [insights, setInsights] = useState<InsightsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoResetting, setDemoResetting] = useState(false);
  const [demoRegenerating, setDemoRegenerating] = useState(false);
  const [me, setMe] = useState<{
    is_admin: boolean;
    role?: string;
    is_demo?: boolean;
  } | null>(null);
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
  const [kpisError, setKpisError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"json" | "csv" | "html" | null>(null);
  const flow = useFlowData();

  // The KPI state is seeded with zeros so the first paint has a shape. When
  // the request fails those zeros used to stay on screen and read as measured
  // facts -- an unreachable API produced a confident "0 filas afectadas sobre
  // 0 analizadas". The failure is now tracked and shown instead.
  const loadDashboard = async () => {
    setLoading(true);
    const [kpisResult] = await Promise.allSettled([
      apiFetch<DashboardKpis>("/dashboard/kpis").then(setKpis),
      apiFetch<Dataset[]>("/datasets").then(setDatasets),
      apiFetch<InsightsResponse>("/dashboard/insights").then(setInsights),
      apiFetch<{ is_admin: boolean; role?: string; is_demo?: boolean }>("/auth/me").then(setMe),
    ]);
    setKpisError(
      kpisResult.status === "rejected"
        ? (kpisResult.reason as Error)?.message ?? "No se pudieron cargar las métricas."
        : null,
    );
    setLoading(false);
  };

  useEffect(() => {
    if (!getToken()) {
      router.push(entryPath());
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
  const hasMeasuredData =
    !kpisError && kpis.datasets_measured > 0 && kpis.total_rows > 0;
  /** "-" rather than 0 whenever the figure was never actually received. */
  const kpi = (value: number) => (kpisError ? "—" : formatNumber(value));
  const kpiPct = (value: number) => (kpisError ? "—" : `${value}%`);
  const isDemo = me?.is_demo ?? false;
  const canDemo = can(me, "dashboard:demo");
  const demoCount = useMemo(
    () => datasets.filter((dataset) => dataset.name.toLowerCase().includes("demo")).length,
    [datasets]
  );
  const formatNumber = (value: number) =>
    new Intl.NumberFormat("es-AR").format(value || 0);
  // Quality is already a percentage, so its movement is expressed in points.
  const formatPoints = (value: number) =>
    `${value > 0 ? "+" : ""}${value.toFixed(1)} pts`;
  const trendClass = (value: number) => {
    if (value > 0) return "text-[var(--success)]";
    if (value < 0) return "text-[var(--danger)]";
    return "text-white/75";
  };
  const qualityTone = (score: number) => {
    if (score >= 90) return "text-[var(--success)]";
    if (score >= 60) return "text-[var(--warning)]";
    return "text-[var(--danger)]";
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

  // min-h, not h: these divs also carry flex-1, and in a column flex
  // container flex-basis:0% overrides height. The four dashboard charts
  // were collapsing to 0px because their panels are sized by their own
  // content, leaving no free space for the chart to claim.
  const chartHeight = "min-h-[22.5rem]";
  const modalChartHeight = "h-[28rem]";

  const createDemo = async () => {
    if (!canDemo) {
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
      description: "Corré reglas y anomalías para producir hallazgos y casos.",
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

  // Every overlay in the app was mouse-only; Escape now closes them.
  useEscapeKey(Boolean(activeModal), () => setActiveModal(null));
  useEscapeKey(Boolean(showExport), () => setShowExport(false));

  return (
    <div className="flex flex-col gap-8">
      <Topbar
        title="Salud general"
        onGuide={() => setShowOnboarding(true)}
        onExport={() => setShowExport(true)}
      />

      {kpisError && !loading && (
        <ErrorState
          title="No se pudieron cargar las métricas"
          message={kpisError}
          onRetry={loadDashboard}
          compact
        />
      )}

      <OnboardingCoach
        flow={flow}
        stepKey="datasets"
        title="Creá tu primer dataset"
        description="Definí el origen y el dominio para empezar el monitoreo."
        actionLabel="Crear dataset"
        href="/datasets#dataset-create"
      />

      {/* The headline metric gets its own row and a much larger number: the
          five supporting counts below explain it, they do not compete with it.
          Every figure is a count of rows or of findings; nothing is estimated. */}
      <section className="panel kpi-card">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">
              Calidad de datos
            </p>
            {loading ? (
              <div className="skeleton mt-4 h-16 w-48" />
            ) : !hasMeasuredData ? (
              <p className="mt-3 text-3xl font-semibold text-white/60">Sin datos</p>
            ) : (
              <p
                className={`mt-3 text-6xl font-semibold tracking-tight sm:text-7xl ${qualityTone(
                  kpis.quality_score,
                )}`}
              >
                {kpis.quality_score}
                <span className="align-top text-3xl">%</span>
              </p>
            )}
            <p className="mt-3 max-w-md text-sm text-white/75">
              {loading
                ? "Calculando..."
                : hasMeasuredData
                ? `${formatNumber(
                    kpis.total_rows - kpis.rows_affected,
                  )} de ${formatNumber(
                    kpis.total_rows,
                  )} filas pasaron todas las reglas activas del dominio.`
                : kpisError
                ? "El score no se pudo calcular: las métricas no llegaron."
                : "Todavia no hay corridas de calidad medidas."}
            </p>
          </div>

          <div className="grid shrink-0 gap-3 text-sm sm:grid-cols-2 lg:w-[26rem]">
            <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-white/55">Tendencia</p>
              {loading ? (
                <div className="skeleton mt-2 h-5 w-24" />
              ) : kpis.quality_trend ? (
                <>
                  <p
                    className={`mt-1 text-lg font-semibold ${trendClass(
                      kpis.quality_trend.delta_points,
                    )}`}
                  >
                    {formatPoints(kpis.quality_trend.delta_points)}
                  </p>
                  <p className="mt-1 text-xs text-white/60">
                    {kpis.quality_trend.previous}% &rarr; {kpis.quality_trend.current}% en{" "}
                    {kpis.quality_trend.datasets_compared} dataset
                    {kpis.quality_trend.datasets_compared === 1 ? "" : "s"}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-xs text-white/60">
                  Sin corrida previa para comparar
                </p>
              )}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.2em] text-white/55">
                Como se calcula
              </p>
              <p className="mt-1 text-xs leading-snug text-white/70">
                Filas que no violan ninguna regla, sobre el total analizado. Una fila
                con tres problemas sigue contando como una.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Five supporting counts. Each one is a number plus a single line
          saying what it counts: at this width anything longer wraps into
          soup. */}
      <section className="grid grid-cols-2 items-stretch gap-3 sm:gap-4 xl:grid-cols-5">
        <div className="panel h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Filas afectadas</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-24" />
          ) : (
            <div className="mt-3 flex items-baseline gap-2">
              <p className="text-3xl font-semibold">{kpi(kpis.rows_affected)}</p>
              <span className="text-sm font-medium text-[var(--accent-2)]">
                {kpiPct(kpis.rows_affected_pct)}
              </span>
            </div>
          )}
          <p className="mt-2 text-xs leading-snug text-white/70">
            Fallan al menos una regla, sobre {kpi(kpis.total_rows)} analizadas
          </p>
        </div>

        <div className="panel h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Filas criticas</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-24" />
          ) : (
            <div className="mt-3 flex items-baseline gap-2">
              <p className="text-3xl font-semibold">{kpi(kpis.critical_rows)}</p>
              <span className="text-sm font-medium text-[var(--danger)]">
                {kpiPct(kpis.critical_rows_pct)}
              </span>
            </div>
          )}
          <p className="mt-2 text-xs leading-snug text-white/70">
            Severidad alta: direccion, codigo postal, ID de orden, precio o entrega
          </p>
        </div>

        <div className="panel h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Hallazgos</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-3 text-3xl font-semibold">{kpi(kpis.findings)}</p>
          )}
          <p className="mt-2 text-xs leading-snug text-white/70">
            Combinaciones regla + campo, en {kpi(kpis.rule_violations)} violaciones
          </p>
        </div>

        <div className="panel h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Anomalias</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-3 text-3xl font-semibold">{kpi(kpis.anomalies)}</p>
          )}
          <p className="mt-2 text-xs leading-snug text-white/70">
            Valores validos pero fuera de rango (|z| &ge; 3.5 sobre la mediana)
          </p>
        </div>

        <div className="panel h-full">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Casos abiertos</p>
          {loading ? (
            <div className="skeleton mt-4 h-9 w-20" />
          ) : (
            <p className="mt-3 text-3xl font-semibold">{kpi(kpis.open_cases)}</p>
          )}
          <p className="mt-2 text-xs leading-snug text-white/70">
            Incidencias sin resolver, sobre {kpi(kpis.datasets_analyzed)} de {kpi(kpis.datasets)}{" "}
            datasets analizados
          </p>
        </div>
      </section>

      {!loading && !isDemo && (
        <section className="panel flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Demo</p>
            <h3 className="mt-2 text-xl font-semibold">Control de demo</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              {demoCount > 0
                ? `${demoCount} datasets demo activos.`
                : "Todavía no hay datasets demo cargados."}
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            {!isDemo && (
              <button
                className="btn-secondary"
                onClick={createDemo}
                disabled={demoLoading || !canDemo}
              >
                {demoLoading ? "Generando demo..." : "Cargar demo"}
              </button>
            )}
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

      <FlowSteps flow={flow} onGuide={() => setShowOnboarding(true)} />

      <section className="grid gap-6 lg:grid-cols-2 items-stretch">
        <div className="panel h-full flex flex-col">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/55">Actividad</p>
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
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Calidad</p>
            <h3 className="mt-2 text-xl font-semibold">Violaciones por severidad</h3>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.issues_by_severity ?? []).length === 0 ? (
              <div className="chart-empty h-full">
                <EmptyState
                  title="Sin violaciones calculadas."
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
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Primeros pasos</p>
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
            {!isDemo && (
              <button
                className="btn-secondary"
                onClick={createDemo}
                disabled={demoLoading || !canDemo}
              >
                {demoLoading ? "Generando demo..." : "Cargar demo"}
              </button>
            )}
          </div>
          {me && !canDemo && !isDemo && (
            <p className="text-xs text-[var(--muted)] md:col-span-2">
              Solo administradores o analistas pueden cargar demos.
            </p>
          )}
        </section>
      )}

      <section className="grid gap-6 lg:grid-cols-2 items-stretch">
        <div className="panel h-full flex flex-col">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Reglas</p>
            <h3 className="mt-2 text-xl font-semibold">Violaciones por regla</h3>
          </div>
          <div className={`mt-6 ${chartHeight} flex-1`}>
            {loading ? (
              <div className="skeleton h-full" />
            ) : (insights?.issues_by_code ?? []).length === 0 ? (
              <div className="chart-empty h-full">
                <EmptyState
                  title="Sin violaciones por regla."
                  description="Generá hallazgos con una corrida."
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
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Anomalías</p>
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
              <p className="text-xs uppercase tracking-[0.3em] text-white/55">Datasets</p>
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
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Calidad por dataset</p>
            <h3 className="mt-2 text-xl font-semibold">Filas sin problemas</h3>
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
                    <p className="text-xs text-white/50">
                      {dataset.score === null
                        ? dataset.schema_status === "incompatible"
                          ? "Esquema incompatible"
                          : "Sin medir"
                        : `${dataset.score}%`}
                    </p>
                  </div>
                  <div className="mt-2 h-2 w-full rounded-full bg-white/10">
                    <div
                      className="h-2 rounded-full bg-[var(--accent)]"
                      style={{ width: `${dataset.score ?? 0}%` }}
                    />
                  </div>
                  {dataset.score !== null && dataset.rows_affected !== null && (
                    <p className="mt-2 text-xs text-white/50">
                      {formatNumber(dataset.rows_affected)} de{" "}
                      {formatNumber(dataset.total_rows)} filas afectadas
                      {dataset.critical_rows ? ` · ${formatNumber(dataset.critical_rows)} criticas` : ""}
                    </p>
                  )}
                  {dataset.score === null && (
                    <p
                      className={`mt-2 text-xs ${
                        dataset.schema_status === "incompatible"
                          ? "text-[var(--danger)]"
                          : "text-white/50"
                      }`}
                    >
                      {dataset.schema_status === "incompatible"
                        ? "El archivo no corresponde al dominio: no se ejecutaron las reglas."
                        : "Todavia no se corrio calidad sobre este dataset."}
                    </p>
                  )}
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
          <div role="dialog" aria-modal="true" className="modal-panel relative max-h-[85vh] w-[92vw] max-w-5xl overflow-hidden ring-1 ring-white/10">
            <button
              className="absolute right-6 top-6 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
              onClick={() => setActiveModal(null)}
            >
              Cerrar
            </button>
            <div className="scroll-soft flex flex-col gap-6 overflow-auto pr-2 max-h-[75vh]">
              {activeModal === "runs" && (
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Actividad</p>
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
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Calidad</p>
                  <h3 className="mt-2 text-xl font-semibold">Violaciones por severidad</h3>
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
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Reglas</p>
                  <h3 className="mt-2 text-xl font-semibold">Todos los hallazgos</h3>
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
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Anomalías</p>
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
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Datasets</p>
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
                  <p className="text-xs uppercase tracking-[0.3em] text-white/55">Salud</p>
                  <h3 className="mt-2 text-xl font-semibold">Filas sin problemas</h3>
                  <div className="mt-4 grid gap-3">
                    {healthList.map((dataset) => (
                      <div key={dataset.id} className="card-box">
                        <div className="flex items-center justify-between">
                          <p className="font-medium">{dataset.name}</p>
                          <p className="text-xs text-white/50">
                            {dataset.score === null
                              ? dataset.schema_status === "incompatible"
                                ? "Esquema incompatible"
                                : "Sin medir"
                              : `${dataset.score}%`}
                          </p>
                        </div>
                        <div className="mt-2 h-2 w-full rounded-full bg-white/10">
                          <div
                            className="h-2 rounded-full bg-[var(--accent)]"
                            style={{ width: `${dataset.score ?? 0}%` }}
                          />
                        </div>
                        {dataset.score !== null && dataset.rows_affected !== null && (
                          <p className="mt-2 text-xs text-white/50">
                            {formatNumber(dataset.rows_affected)} de{" "}
                            {formatNumber(dataset.total_rows)} filas afectadas
                          </p>
                        )}
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
          <div role="dialog" aria-modal="true" className="modal-panel max-w-md space-y-4">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/55">Reporte</p>
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
