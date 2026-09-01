"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiFetch, API_URL } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { entryPath } from "@/lib/demo";
import { emitToast } from "@/lib/toast";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { formatDateTime, formatNumber } from "@/lib/format";

type DatasetOption = {
  id: number;
  name: string;
};

type RunItem = {
  id: number;
  dataset_id: number;
  dataset_name: string;
  domain: string;
  run_at: string | null;
  duration_ms: number | null;
  total_rows: number | null;
  issue_rows: number | null;
  anomaly_count: number | null;
  risk_score: number | null;
  quality_score: number | null;
};

type Summary = {
  total_runs: number;
  total_rows: number;
  total_issues: number;
  total_anomalies: number;
  avg_duration_ms: number;
  avg_risk_score: number;
  avg_quality_score: number;
  runs_by_day: { date: string; runs: number }[];
};

export default function RunsPage() {
  const router = useRouter();
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    dataset_id: "",
    from_date: "",
    to_date: "",
    min_risk: "",
    min_rows: "",
  });
  const flow = useFlowData();

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (filters.dataset_id) params.set("dataset_id", filters.dataset_id);
    if (filters.from_date) params.set("from_date", filters.from_date);
    if (filters.to_date) params.set("to_date", filters.to_date);
    if (filters.min_risk) params.set("min_risk", filters.min_risk);
    if (filters.min_rows) params.set("min_rows", filters.min_rows);
    return params.toString();
  }, [filters]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ds, runList, sum] = await Promise.all([
        apiFetch<DatasetOption[]>("/datasets"),
        apiFetch<RunItem[]>(`/runs${queryString ? `?${queryString}` : ""}`),
        apiFetch<Summary>(`/runs/summary${queryString ? `?${queryString}` : ""}`),
      ]);
      setDatasets(ds);
      setRuns(runList);
      setSummary(sum);
      setLoadError(null);
    } catch (err) {
      setRuns([]);
      setSummary(null);
      // Without this the five summary cards fell back to zeros, presenting an
      // unreachable API as "0 corridas, 0 filas, calidad media 0%".
      setLoadError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [queryString]);

  useEffect(() => {
    if (!getToken()) {
      router.push(entryPath());
      return;
    }
    load();
  }, [router, load]);

  /** "-" rather than 0 whenever the figure was never actually received. */
  const kpi = (value?: number | null) => (loadError ? "—" : formatNumber(value ?? 0));

  const formatDuration = (value?: number | null) => {
    if (!value) return "-";
    if (value < 1000) return `${value} ms`;
    return `${(value / 1000).toFixed(1)} s`;
  };

  const exportCsv = async () => {
    try {
      const token = getToken();
      if (!token) return;
      const url = `${API_URL}/runs?format=csv${queryString ? `&${queryString}` : ""}`;
      const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) {
        throw new Error("No se pudo exportar CSV");
      }
      const blob = await response.blob();
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 10);
      link.href = window.URL.createObjectURL(blob);
      link.download = `runs_${stamp}.csv`;
      link.click();
      window.URL.revokeObjectURL(link.href);
      emitToast({ message: "CSV descargado.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/55">Corridas</p>
        <h2 className="mt-2 text-3xl font-semibold">Historial de calidad</h2>
      </div>

      <OnboardingCoach
        flow={flow}
        stepKey="runs"
        title="Ejecutá la primera corrida"
        description="Seleccioná un dataset y ejecutá calidad para generar hallazgos."
        actionLabel="Ir a Datasets"
        href="/datasets"
      />

      {loadError && !loading && (
        <ErrorState title="No se pudieron cargar las corridas" message={loadError} onRetry={load} compact />
      )}

      {/* The two date pickers used to be unlabelled and identical: there was
          no way to tell "desde" from "hasta" without clicking one. */}
      <section className="panel">
        <p className="text-xs uppercase tracking-[0.3em] text-white/55">Filtros</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <label className="grid gap-1.5 text-xs text-white/70">
            Dataset
            <select
              className="input-base"
              value={filters.dataset_id}
              onChange={(event) =>
                setFilters({ ...filters, dataset_id: event.target.value })
              }
            >
              <option value="">Todos los datasets</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={String(dataset.id)}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-xs text-white/70">
            Desde
            <input
              className="input-base"
              type="date"
              value={filters.from_date}
              onChange={(event) =>
                setFilters({ ...filters, from_date: event.target.value })
              }
            />
          </label>
          <label className="grid gap-1.5 text-xs text-white/70">
            Hasta
            <input
              className="input-base"
              type="date"
              value={filters.to_date}
              onChange={(event) =>
                setFilters({ ...filters, to_date: event.target.value })
              }
            />
          </label>
          <label className="grid gap-1.5 text-xs text-white/70">
            % filas criticas minimo
            <input
              className="input-base"
              type="number"
              min={0}
              max={100}
              placeholder="0"
              value={filters.min_risk}
              onChange={(event) =>
                setFilters({ ...filters, min_risk: event.target.value })
              }
            />
          </label>
          <label className="grid gap-1.5 text-xs text-white/70">
            Filas minimas
            <input
              className="input-base"
              type="number"
              min={0}
              placeholder="0"
              value={filters.min_rows}
              onChange={(event) =>
                setFilters({ ...filters, min_rows: event.target.value })
              }
            />
          </label>
        </div>
      </section>

      <section className="grid grid-cols-2 items-stretch gap-3 sm:gap-4 xl:grid-cols-5">
        {[
          {
            etiqueta: "Corridas",
            valor: kpi(summary?.total_runs),
            pie: "En el filtro actual",
          },
          {
            etiqueta: "Filas",
            valor: kpi(summary?.total_rows),
            pie: "Registros analizados",
          },
          {
            // total_issues sums run.issue_rows, which the backend fills with
            // rule_violations(): it counts rule firings, not distinct rows.
            etiqueta: "Violaciones",
            valor: kpi(summary?.total_issues),
            pie: "Reglas disparadas en total",
          },
          {
            etiqueta: "% criticas medio",
            valor: loadError ? "—" : `${summary?.avg_risk_score ?? 0}%`,
            pie: "Promedio de las corridas",
          },
          {
            etiqueta: "Calidad media",
            valor: loadError ? "—" : `${summary?.avg_quality_score ?? 0}%`,
            pie: "Promedio de las corridas",
          },
        ].map((item) => (
          <div key={item.etiqueta} className="panel h-full">
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">
              {item.etiqueta}
            </p>
            {loading ? (
              <div className="skeleton mt-4 h-9 w-20" />
            ) : (
              <p className="mt-3 text-3xl font-semibold">{item.valor}</p>
            )}
            <p className="mt-2 text-xs leading-snug text-white/70">{item.pie}</p>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Tendencia</p>
            <h3 className="mt-2 text-xl font-semibold">Corridas por día</h3>
          </div>
          <button className="btn-secondary" onClick={exportCsv}>
            Exportar CSV
          </button>
        </div>
        <div className="mt-6 h-64">
          {loading ? (
            <div className="skeleton h-full" />
          ) : summary?.runs_by_day?.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={summary.runs_by_day}
                margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="runsSeries" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff7a1a" stopOpacity={0.7} />
                    <stop offset="95%" stopColor="#ff7a1a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#9fb0c9", fontSize: 11 }}
                  tickFormatter={(value) => value.slice(5)}
                />
                <YAxis tick={{ fill: "#9fb0c9", fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#101827", border: "1px solid rgba(255,255,255,0.1)" }} />
                <Area
                  type="monotone"
                  dataKey="runs"
                  stroke="#ff7a1a"
                  fill="url(#runsSeries)"
                  strokeWidth={2}
                  dot={{ r: 2.5, fill: "#ff7a1a", stroke: "none" }}
                  activeDot={{ r: 4 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="chart-empty h-full">
              <EmptyState
                title="Sin datos de corridas."
                description="Ejecutá calidad para generar historial."
                actions={[{ label: "Ir a Datasets", href: "/datasets", variant: "secondary" }]}
                compact
              />
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Detalle</p>
            <h3 className="mt-2 text-xl font-semibold">Corridas registradas</h3>
          </div>
          <button
            className="btn-secondary"
            onClick={() =>
              setFilters({ dataset_id: "", from_date: "", to_date: "", min_risk: "", min_rows: "" })
            }
          >
            Limpiar filtros
          </button>
        </div>
        <div className="mt-6 grid gap-3">
          {loading ? (
            Array.from({ length: 3 }).map((_, idx) => (
              <div key={`run-skel-${idx}`} className="skeleton h-16" />
            ))
          ) : runs.length === 0 ? (
            <EmptyState
              title="No hay corridas para mostrar."
              description="Ejecutá calidad en un dataset para iniciar el historial."
              actions={[{ label: "Ejecutar calidad", href: "/datasets", variant: "primary" }]}
            />
          ) : (
            runs.map((run) => (
              <div key={run.id} className="card-row">
                <div>
                  <p className="text-white">{run.dataset_name}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {formatDateTime(run.run_at)} · {run.domain}
                  </p>
                </div>
                <div className="text-xs text-white/70">
                  {formatNumber(run.total_rows)} filas · {formatNumber(run.issue_rows)}{" "}
                  violaciones · {formatNumber(run.anomaly_count)} anomalias
                </div>
                <div className="text-xs text-white/70">
                  Calidad {run.quality_score ?? 0}% · Criticas {run.risk_score ?? 0}%
                </div>
                <div className="text-xs text-white/70">{formatDuration(run.duration_ms)}</div>
                <Link className="btn-secondary" href={`/datasets/${run.dataset_id}`}>
                  Ver dataset
                </Link>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
