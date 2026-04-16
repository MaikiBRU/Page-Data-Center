"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch, API_URL } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { emitToast } from "@/lib/toast";
import { EmptyState } from "@/components/EmptyState";

interface QualityIssue {
  code: string;
  field?: string;
  count?: number;
  severity?: string;
}

interface DatasetRecommendation {
  code: string;
  label?: string;
  action: string;
  severity?: string;
  count?: number;
  priority?: string;
}

interface DatasetAnomaly {
  field: string;
  value?: string | number;
  score?: number;
  order_id?: string;
}

interface DatasetQualitySummary {
  summary?: {
    total_rows?: number;
    domain_profile?: string;
  };
  issues?: QualityIssue[];
  recommendations?: DatasetRecommendation[];
}

interface DatasetAnomalySummary {
  anomaly_count?: number;
  anomalies?: DatasetAnomaly[];
}

interface DatasetDetail {
  id: number;
  name: string;
  domain: string;
  source_type: string;
  file_path?: string | null;
  quality_summary?: DatasetQualitySummary | null;
  anomaly_summary?: DatasetAnomalySummary | null;
  rules_config?: { disabled_rules?: string[] } | null;
  assignment_mode?: string;
  assignment_owner?: string | null;
  assignment_cursor?: number | null;
}

interface PreviewData {
  columns: string[];
  rows: Record<string, string>[];
  stats: Record<
    string,
    {
      missing: number;
      unique: number;
      type: string;
      min?: number | null;
      max?: number | null;
      avg?: number | null;
      samples: string[];
    }
  >;
  sampled: boolean;
  sample_size: number;
}

interface DatasetRun {
  id: number;
  run_at: string | null;
  duration_ms: number | null;
  total_rows: number | null;
  issue_count: number | null;
  issue_rows: number | null;
  anomaly_count: number | null;
  risk_score: number | null;
  quality_score: number | null;
}

export default function DatasetDetailPage() {
  const params = useParams();
  const router = useRouter();
  const datasetId = Number(params.id);
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [me, setMe] = useState<{ is_admin: boolean; role?: string } | null>(null);
  const [assignableUsers, setAssignableUsers] = useState<
    { id: number; email: string; role: string; is_admin: boolean }[]
  >([]);
  const [assignmentMode, setAssignmentMode] = useState("manual");
  const [assignmentOwner, setAssignmentOwner] = useState("");
  const [savingAssignment, setSavingAssignment] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [savingDomain, setSavingDomain] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [rulesCatalog, setRulesCatalog] = useState<Record<string, string>>({});
  const [rulesProfiles, setRulesProfiles] = useState<Record<string, string[]>>({});
  const [disabledRules, setDisabledRules] = useState<string[]>([]);
  const [savingRules, setSavingRules] = useState(false);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [runs, setRuns] = useState<DatasetRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [showRuns, setShowRuns] = useState(false);

  const loadDataset = useCallback(() => {
    apiFetch<DatasetDetail>(`/datasets/${datasetId}`)
      .then(setDataset)
      .catch(() => null);
  }, [datasetId]);

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    loadDataset();
    apiFetch<{ is_admin: boolean; role?: string }>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, [datasetId, router, loadDataset]);

  useEffect(() => {
    apiFetch<{ id: number; email: string; role: string; is_admin: boolean }[]>(
      "/users/assignable"
    )
      .then(setAssignableUsers)
      .catch(() => setAssignableUsers([]));
  }, []);

  const datasetAssignmentMode = dataset?.assignment_mode ?? "manual";
  const datasetAssignmentOwner = dataset?.assignment_owner ?? "";

  useEffect(() => {
    setAssignmentMode(datasetAssignmentMode);
    setAssignmentOwner(datasetAssignmentOwner);
  }, [datasetAssignmentMode, datasetAssignmentOwner]);

  const loadPreview = useCallback(async () => {
    if (!dataset?.file_path) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await apiFetch<PreviewData>(`/datasets/${datasetId}/preview`);
      setPreview(data);
    } catch (err) {
      const message = (err as Error).message || "Error al cargar vista previa";
      if (message.toLowerCase().includes("failed to fetch")) {
        setPreviewError(
          `No se pudo conectar al backend (${API_URL}). Verificá que Uvicorn esté corriendo.`
        );
      } else {
        setPreviewError(message);
      }
    } finally {
      setPreviewLoading(false);
    }
  }, [dataset?.file_path, datasetId]);

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const data = await apiFetch<DatasetRun[]>(`/datasets/${datasetId}/runs?limit=20`);
      setRuns(data);
    } catch {
      setRuns([]);
    } finally {
      setRunsLoading(false);
    }
  }, [datasetId]);

  useEffect(() => {
    if (dataset?.file_path) {
      loadPreview();
    } else {
      setPreview(null);
    }
    loadRuns();
  }, [dataset?.file_path, loadPreview, loadRuns]);

  useEffect(() => {
    apiFetch<{ catalog: Record<string, string>; profiles: Record<string, string[]> }>(
      "/datasets/rules"
    )
      .then((data) => {
        setRulesCatalog(data.catalog ?? {});
        setRulesProfiles(data.profiles ?? {});
      })
      .catch(() => null);
  }, []);

  useEffect(() => {
    if (!dataset) return;
    const rules = dataset.rules_config?.disabled_rules ?? [];
    const allowed = rulesProfiles[dataset.domain];
    if (!allowed) {
      setDisabledRules(rules);
      return;
    }
    setDisabledRules(rules.filter((rule) => allowed.includes(rule)));
  }, [dataset, rulesProfiles]);

  const uploadFile = async (file: File) => {
    if (!(me?.is_admin || me?.role === "analyst")) {
      emitToast({ message: "No tenés permisos para subir archivos.", kind: "error" });
      return;
    }
    const token = getToken();
    if (!token) return;

    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_URL}/datasets/${datasetId}/upload`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      body: formData,
    });

    if (!response.ok) {
      const msg = "No se pudo subir el archivo";
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
      return;
    }
    setMessage("Archivo cargado correctamente");
    emitToast({ message: "Archivo cargado.", kind: "success" });
    loadDataset();
    loadPreview();
    loadRuns();
  };

  const generateData = async () => {
    if (!(me?.is_admin || me?.role === "analyst")) {
      emitToast({ message: "No tenés permisos para generar datos.", kind: "error" });
      return;
    }
    try {
      await apiFetch(`/datasets/${datasetId}/generate`, {
        method: "POST",
        body: JSON.stringify({ rows: 300, anomaly_rate: 0.1 }),
      });
      setMessage("Dataset generado");
      emitToast({ message: "Dataset generado.", kind: "success" });
      loadDataset();
      loadPreview();
      loadRuns();
    } catch (err) {
      const msg = (err as Error).message;
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
    }
  };

  const runQuality = async () => {
    if (!(me?.is_admin || me?.role === "analyst")) {
      emitToast({ message: "No tenés permisos para ejecutar calidad.", kind: "error" });
      return;
    }
    try {
      await apiFetch(`/datasets/${datasetId}/run-quality`, { method: "POST" });
      setMessage("Calidad ejecutada");
      emitToast({ message: "Calidad ejecutada.", kind: "success" });
      loadDataset();
      loadRuns();
    } catch (err) {
      const msg = (err as Error).message;
      setMessage(msg);
      emitToast({ message: msg, kind: "error" });
    }
  };

  if (!dataset) {
    return <p className="text-sm text-[var(--muted)]">Cargando...</p>;
  }

  const issues = dataset.quality_summary?.issues ?? [];
  const recommendations = dataset.quality_summary?.recommendations ?? [];
  const anomalies = dataset.anomaly_summary?.anomalies ?? [];
  const profile = dataset.quality_summary?.summary?.domain_profile ?? dataset.domain;
  const canEdit = me?.is_admin || me?.role === "analyst";
  const canAdmin = me?.is_admin;
  const formatDate = (value?: string | null) => {
    if (!value) return "Pendiente";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "short",
      year: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const formatDuration = (value?: number | null) => {
    if (!value) return "-";
    if (value < 1000) return `${value} ms`;
    return `${(value / 1000).toFixed(1)} s`;
  };

  const downloadReport = async (format: "json" | "csv" | "html") => {
    const token = getToken();
    if (!token) return;
    try {
      const response = await fetch(
        `${API_URL}/datasets/${datasetId}/report?format=${format}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) {
        throw new Error("No se pudo exportar el reporte");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `dataset_${datasetId}_report.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
      emitToast({ message: "Reporte descargado.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const openHtmlReport = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const response = await fetch(`${API_URL}/datasets/${datasetId}/report?format=html`, {
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
    }
  };

  const profileLabel = () => {
    switch (profile) {
      case "ecommerce":
        return "Ecommerce";
      case "logistica":
        return "Logística";
      case "ecommerce-logistica":
      default:
        return "Ecommerce + Logística";
    }
  };

  const profileRuleIds = () => {
    if (!dataset) return [];
    return rulesProfiles[dataset.domain] ?? [];
  };

  const activeRuleLabels = () => {
    const ids = profileRuleIds().filter((id) => !disabledRules.includes(id));
    if (ids.length === 0) return [];
    return ids.map((id) => rulesCatalog[id] ?? id);
  };

  const nextRoundRobin = () => {
    if (assignmentMode !== "round_robin") return null;
    if (!assignableUsers.length) return null;
    const cursor = dataset?.assignment_cursor ?? 0;
    const index = cursor % assignableUsers.length;
    return assignableUsers[index]?.email ?? null;
  };

  const impactPreview = (ruleId: string) => {
    const issues = dataset?.quality_summary?.issues ?? [];
    const anomalies = dataset?.anomaly_summary?.anomalies ?? [];
    if (ruleId.startsWith("anomaly_")) {
      const fieldMap: Record<string, string> = {
        anomaly_price: "price",
        anomaly_weight_kg: "weight_kg",
        anomaly_lead_time_days: "lead_time_days",
        anomaly_quantity: "quantity",
        anomaly_stock: "stock",
        anomaly_discount_pct: "discount_pct",
      };
      const field = fieldMap[ruleId];
      if (!field) return null;
      const count = anomalies.filter((item) => item.field === field).length;
      if (!count) return null;
      return { text: `Podrías ocultar ${count} anomalías`, risk: "medio" };
    }
    const matches = issues.filter((item) => item.code === ruleId);
    if (matches.length === 0) return null;
    const totalRows = matches.reduce(
      (acc: number, item) => acc + (Number(item.count) || 0),
      0
    );
    const severity = matches.some((item) => item.severity === "high")
      ? "alto"
      : matches.some((item) => item.severity === "medium")
      ? "medio"
      : "bajo";
    const text = totalRows
      ? `Podrías ocultar ${totalRows} registros`
      : `Podrías ocultar ${matches.length} issues`;
    return { text, risk: severity };
  };

  const totalImpact = (disabledList: string[]) => {
    const issues = dataset?.quality_summary?.issues ?? [];
    const anomalies = dataset?.anomaly_summary?.anomalies ?? [];
    const disabled = new Set(disabledList);
    const issueHits = issues.filter((item) => disabled.has(item.code));
    const anomalyFieldMap: Record<string, string> = {
      anomaly_price: "price",
      anomaly_weight_kg: "weight_kg",
      anomaly_lead_time_days: "lead_time_days",
      anomaly_quantity: "quantity",
      anomaly_stock: "stock",
      anomaly_discount_pct: "discount_pct",
    };
    const disabledAnomalies = Object.entries(anomalyFieldMap)
      .filter(([ruleId]) => disabled.has(ruleId))
      .map(([, field]) => field);
    const anomalyHits = anomalies.filter((item) => disabledAnomalies.includes(item.field));
    const sumBySeverity = (severity: string) =>
      issueHits
        .filter((item) => item.severity === severity)
        .reduce((acc: number, item) => acc + (Number(item.count) || 0), 0);
    const high = sumBySeverity("high");
    const medium = sumBySeverity("medium");
    const low = sumBySeverity("low");
    const issueRows = issueHits.reduce(
      (acc: number, item) => acc + (Number(item.count) || 0),
      0
    );
    return {
      issues: issueRows,
      anomalies: anomalyHits.length,
      high,
      medium,
      low,
    };
  };

  const updateDomain = async (value: string) => {
    if (!dataset) return;
    if (!me?.is_admin) {
      emitToast({ message: "No tenés permisos para editar el dominio.", kind: "error" });
      return;
    }
    setSavingDomain(true);
    try {
      const updated = await apiFetch<DatasetDetail>(`/datasets/${dataset.id}/domain`, {
        method: "PATCH",
        body: JSON.stringify({ domain: value }),
      });
      setDataset(updated);
      emitToast({ message: "Dominio actualizado.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setSavingDomain(false);
    }
  };

  const saveAssignment = async () => {
    if (!dataset) return;
    if (!canAdmin) {
      emitToast({ message: "Solo administradores pueden editar asignación.", kind: "error" });
      return;
    }
    if (assignmentMode === "owner" && !assignmentOwner) {
      emitToast({ message: "Seleccioná un owner válido.", kind: "info" });
      return;
    }
    setSavingAssignment(true);
    try {
      const updated = await apiFetch<DatasetDetail>(`/datasets/${dataset.id}/assignment`, {
        method: "PATCH",
        body: JSON.stringify({
          mode: assignmentMode,
          owner: assignmentMode === "owner" ? assignmentOwner : null,
        }),
      });
      setDataset(updated);
      emitToast({ message: "Asignación actualizada.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setSavingAssignment(false);
    }
  };

  const totalCounts = () => {
    const issues = dataset?.quality_summary?.issues ?? [];
    const anomalies = dataset?.anomaly_summary?.anomalies ?? [];
    const issueRows = issues.reduce(
      (acc: number, item) => acc + (Number(item.count) || 0),
      0
    );
    return { issueRows, anomalies: anomalies.length };
  };

  const toggleRule = (ruleId: string) => {
    setDisabledRules((prev) =>
      prev.includes(ruleId) ? prev.filter((item) => item !== ruleId) : [...prev, ruleId]
    );
  };

  const saveRules = async () => {
    if (!dataset) return;
    if (!me?.is_admin) {
      emitToast({ message: "No tenés permisos para editar reglas.", kind: "error" });
      return;
    }
    setSavingRules(true);
    try {
      const updated = await apiFetch<DatasetDetail>(`/datasets/${dataset.id}/rules`, {
        method: "PATCH",
        body: JSON.stringify({ disabled_rules: disabledRules }),
      });
      setDataset(updated);
      emitToast({ message: "Reglas actualizadas.", kind: "success" });
      setShowRules(false);
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setSavingRules(false);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Dataset</p>
        <h2 className="mt-2 text-3xl font-semibold">{dataset.name}</h2>
        <p className="mt-2 text-sm text-[var(--muted)]">{dataset.domain}</p>
      </div>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="panel">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Estado</p>
          <p className="mt-3 text-sm text-white/70">
            Fuente: {dataset.source_type}
          </p>
          <p className="mt-2 text-xs text-white/50">
            Archivo: {dataset.file_path ?? "Sin archivo"}
          </p>
        </div>
        <div className="panel">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Acciones</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <label className="btn-secondary cursor-pointer">
              Subir CSV
              <input
                type="file"
                className="hidden"
                accept=".csv"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) uploadFile(file);
                }}
                disabled={!canEdit}
              />
            </label>
            <button className="btn-secondary" onClick={generateData} disabled={!canEdit}>
              Generar datos
            </button>
            <button className="btn-primary" onClick={runQuality} disabled={!canEdit}>
              Ejecutar calidad
            </button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="btn-mini" onClick={() => downloadReport("json")}>
              Exportar JSON
            </button>
            <button className="btn-mini" onClick={() => downloadReport("csv")}>
              Exportar CSV
            </button>
            <button className="btn-mini" onClick={() => downloadReport("html")}>
              Exportar HTML
            </button>
            <button className="btn-mini" onClick={openHtmlReport}>
              Ver reporte
            </button>
          </div>
          {message && <p className="mt-3 text-xs text-[var(--muted)]">{message}</p>}
          {me && !canEdit && (
            <p className="mt-2 text-xs text-[var(--muted)]">
              Solo administradores o analistas pueden ejecutar acciones.
            </p>
          )}
        </div>
        <div className="panel">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Resumen</p>
          <p className="mt-3 text-2xl font-semibold">
            {dataset.quality_summary?.summary?.total_rows ?? 0}
          </p>
          <p className="text-sm text-[var(--muted)]">Filas analizadas</p>
          <div className="card-box text-xs text-white/70">
            <p className="text-white/50">Perfil de reglas</p>
            <p className="mt-1 font-semibold text-white/80">{profileLabel()}</p>
            <p className="mt-1 text-[var(--muted)]">
              Ajusta validaciones y anomalías según el dominio.
            </p>
            <p className="mt-2 text-[var(--muted)]">
              Activas: {activeRuleLabels().length} reglas
            </p>
            <button
              type="button"
              className="btn-mini mt-3"
              onClick={() => setShowRules(true)}
              disabled={!canAdmin}
            >
              Configurar reglas
            </button>
            <label className="mt-3 block text-[10px] uppercase tracking-[0.3em] text-white/40">
              Cambiar dominio
              <select
                className="input-base mt-2"
                value={dataset.domain}
                onChange={(event) => updateDomain(event.target.value)}
                disabled={savingDomain || !canAdmin}
              >
                <option value="ecommerce-logistica">Ecommerce + Logística</option>
                <option value="ecommerce">Ecommerce</option>
                <option value="logistica">Logística</option>
              </select>
            </label>
            {me && !canAdmin && (
              <p className="mt-2 text-xs text-[var(--muted)]">
                Solo administradores pueden cambiar dominio y reglas.
              </p>
            )}
            {savingDomain && (
              <p className="mt-2 text-xs text-[var(--muted)]">Guardando...</p>
            )}
          </div>
        </div>
        <div className="panel">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Asignación</p>
          <p className="mt-3 text-sm text-white/70">
            Automatiza el owner de casos creados en corridas y recomendaciones.
          </p>
          <div className="mt-3 grid gap-3 text-sm">
            <label className="text-xs uppercase tracking-[0.3em] text-white/40">
              Modo
              <select
                className="input-base mt-2"
                value={assignmentMode}
                onChange={(event) => setAssignmentMode(event.target.value)}
                disabled={!canAdmin}
              >
                <option value="manual">Manual (sin asignar)</option>
                <option value="owner">Owner fijo</option>
                <option value="round_robin">Round robin</option>
              </select>
            </label>
            {assignmentMode === "owner" && (
              <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                Owner
                <select
                  className="input-base mt-2"
                  value={assignmentOwner}
                  onChange={(event) => setAssignmentOwner(event.target.value)}
                  disabled={!canAdmin}
                >
                  <option value="">Seleccionar usuario</option>
                  {assignableUsers.map((user) => (
                    <option key={user.id} value={user.email}>
                      {user.email}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {assignmentMode === "round_robin" && (
              <div className="card-box text-xs text-white/70">
                <p className="text-white/50">Próximo en la ronda</p>
                <p className="mt-1 font-semibold">{nextRoundRobin() ?? "Sin usuarios activos"}</p>
                <p className="mt-1 text-[var(--muted)]">
                  Usuarios activos: {assignableUsers.length}
                </p>
              </div>
            )}
            <button
              className="btn-secondary"
              onClick={saveAssignment}
              disabled={!canAdmin || savingAssignment}
            >
              {savingAssignment ? "Guardando..." : "Guardar asignación"}
            </button>
            {!canAdmin && (
              <p className="text-xs text-[var(--muted)]">
                Solo administradores pueden editar asignación.
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="panel">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Vista previa</p>
              <h3 className="mt-2 text-xl font-semibold">Primeras filas</h3>
            </div>
            <button className="btn-mini" onClick={loadPreview} disabled={previewLoading}>
              {previewLoading ? "Actualizando..." : "Actualizar"}
            </button>
          </div>
          {!dataset.file_path && (
            <p className="mt-4 text-sm text-[var(--muted)]">
              Subí o generá un archivo para visualizar datos.
            </p>
          )}
          {previewError && (
            <p className="mt-4 text-sm text-[var(--danger)]">{previewError}</p>
          )}
          {previewLoading ? (
            <div className="mt-4 grid gap-3">
              {Array.from({ length: 3 }).map((_, idx) => (
                <div key={`preview-skel-${idx}`} className="skeleton h-12" />
              ))}
            </div>
          ) : preview && preview.columns.length > 0 ? (
            <div className="scroll-soft mt-4 overflow-auto rounded-xl border border-white/10">
              <table className="table-base table-sm">
                <thead>
                  <tr>
                    {preview.columns.map((col) => (
                      <th key={col}>{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((row, idx) => (
                    <tr key={`row-${idx}`}>
                      {preview.columns.map((col) => (
                        <td key={`${col}-${idx}`}>
                          {(row as Record<string, string>)[col] ?? "-"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            dataset.file_path && (
              <div className="mt-4">
                <EmptyState
                  title="No hay datos para mostrar todavía."
                  description="Verificá el archivo subido o generá un dataset de prueba."
                  actions={[
                    { label: "Subir CSV", onClick: () => setMessage("Subí un CSV en Acciones."), variant: "secondary" },
                    { label: "Generar datos", onClick: generateData, variant: "primary" },
                  ]}
                />
              </div>
            )
          )}
          {!dataset.file_path && canEdit && (
            <div className="mt-4 flex flex-wrap gap-2">
              <button className="btn-secondary" onClick={() => setMessage("Subí un CSV en Acciones.")}>
                Subir CSV
              </button>
              <button className="btn-secondary" onClick={generateData}>
                Generar datos
              </button>
            </div>
          )}
          {preview?.sampled && (
            <p className="mt-2 text-xs text-[var(--muted)]">
              Estadísticas calculadas sobre una muestra de {preview.sample_size} filas.
            </p>
          )}
        </div>

        <div className="panel">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Historial</p>
              <h3 className="mt-2 text-xl font-semibold">Corridas recientes</h3>
            </div>
            <button className="btn-mini" onClick={() => setShowRuns(true)} disabled={runs.length === 0}>
              Ver todo
            </button>
          </div>
          {runsLoading ? (
            <div className="mt-4 grid gap-3">
              {Array.from({ length: 3 }).map((_, idx) => (
                <div key={`run-skel-${idx}`} className="skeleton h-12" />
              ))}
            </div>
          ) : runs.length === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No hay corridas registradas."
                description="Ejecutá la primera corrida de calidad para ver resultados."
                actions={[
                  { label: "Ejecutar calidad", onClick: runQuality, variant: "primary" },
                ]}
                compact
              />
            </div>
          ) : (
            <div className="mt-4 grid gap-3">
              {runs.slice(0, 5).map((run) => (
                <div key={run.id} className="card-box">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{formatDate(run.run_at)}</p>
                    <span className="text-xs text-white/50">{formatDuration(run.duration_ms)}</span>
                  </div>
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Filas: {run.total_rows ?? 0} · Issues: {run.issue_rows ?? 0} ·
                    Anomalías: {run.anomaly_count ?? 0}
                  </p>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    Riesgo: {run.risk_score ?? 0} · Calidad: {run.quality_score ?? 0}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {preview && (
        <section className="panel">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Perfil</p>
            <h3 className="mt-2 text-xl font-semibold">Perfil de columnas</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Resumen rápido por columna para detectar vacíos y rangos.
            </p>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {preview.columns.map((col) => {
              const stat = preview.stats[col];
              if (!stat) return null;
              return (
                <div key={col} className="card-box">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{col}</p>
                    <span className="badge">
                      {stat.type === "number" ? "Numérico" : "Texto"}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Vacíos: {stat.missing} · Únicos: {stat.unique}
                  </p>
                  {stat.type === "number" && (
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      Min: {stat.min ?? "-"} · Max: {stat.max ?? "-"} · Avg: {stat.avg ?? "-"}
                    </p>
                  )}
                  {stat.samples.length > 0 && (
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      Ejemplos: {stat.samples.join(", ")}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="panel">
        <h3 className="text-xl font-semibold">Issues detectados</h3>
        <div className="mt-4 grid gap-3">
          {issues.length === 0 ? (
            <EmptyState
              title="Sin issues por ahora."
              description="Corré calidad para detectar nuevos issues."
              actions={[{ label: "Ejecutar calidad", onClick: runQuality, variant: "secondary" }]}
              compact
            />
          ) : (
            issues.map((issue, index: number) => (
              <div key={`${issue.code}-${index}`} className="card-box">
                <div className="flex items-center justify-between">
                  <p className="font-medium">{issue.code}</p>
                  <span className="text-xs text-white/60">{issue.count} casos</span>
                </div>
                <p className="text-xs text-[var(--muted)]">Severidad: {issue.severity}</p>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="panel">
          <h3 className="text-xl font-semibold">Anomalías</h3>
          <div className="mt-4 grid gap-3 text-sm">
            {anomalies.length === 0 ? (
              <EmptyState
                title="Sin anomalías críticas."
                description="Corré calidad para detectar outliers."
                actions={[{ label: "Ejecutar calidad", onClick: runQuality, variant: "secondary" }]}
                compact
              />
            ) : (
              anomalies.slice(0, 6).map((item, index: number) => (
                <div key={`${item.field}-${index}`} className="card-box">
                  <p className="font-medium">{item.field}</p>
                  <p className="text-xs text-[var(--muted)]">
                    Valor: {item.value} · Score: {item.score}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
        <div className="panel">
          <h3 className="text-xl font-semibold">Acciones recomendadas</h3>
          <div className="mt-4 grid gap-3 text-sm">
            {recommendations.length === 0 ? (
              <EmptyState
                title="Sin recomendaciones aún."
                description="Ejecutá calidad para generar recomendaciones."
                actions={[{ label: "Ejecutar calidad", onClick: runQuality, variant: "secondary" }]}
                compact
              />
            ) : (
              recommendations.map((rec, index: number) => (
                <div key={`${rec.code}-${index}`} className="card-box">
                  <p className="font-medium">{rec.code}</p>
                  <p className="text-xs text-[var(--muted)]">{rec.action}</p>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      {showRules && (
        <div className="modal-backdrop" onClick={() => setShowRules(false)}>
          <div
            className="modal-panel relative max-h-[85vh] max-w-lg overflow-hidden"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="absolute right-10 top-6 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
              onClick={() => setShowRules(false)}
            >
              Cerrar
            </button>
            <div className="scroll-soft flex max-h-[75vh] flex-col gap-4 overflow-auto pr-2">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">Reglas activas</p>
                <h3 className="mt-2 text-xl font-semibold">
                  Perfil {profileLabel()}
                </h3>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  Estas reglas se aplican en la validación de calidad y anomalías.
                </p>
              </div>
              <ul className="space-y-2 text-sm text-white/80">
                {profileRuleIds().map((ruleId) => (
                  <li key={ruleId} className="card-box px-3 py-2">
                    <label className="flex items-start justify-between gap-4">
                      <span>
                        {rulesCatalog[ruleId] ?? ruleId}
                        {disabledRules.includes(ruleId) && (
                          <span className="ml-2 text-xs text-[var(--muted)]">(Desactivada)</span>
                        )}
                        {impactPreview(ruleId) && (
                          <span className="mt-1 flex items-center gap-2 text-xs text-[var(--muted)]">
                            {impactPreview(ruleId)?.text}
                            <span
                              className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] ${
                                impactPreview(ruleId)?.risk === "alto"
                                  ? "border border-[var(--danger)]/50 bg-[var(--danger)]/15 text-[var(--danger)]"
                                  : impactPreview(ruleId)?.risk === "medio"
                                  ? "border border-[var(--warning)]/50 bg-[var(--warning)]/15 text-[var(--warning)]"
                                  : "border border-[var(--success)]/50 bg-[var(--success)]/15 text-[var(--success)]"
                              }`}
                            >
                              {impactPreview(ruleId)?.risk}
                            </span>
                          </span>
                        )}
                      </span>
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 accent-[var(--accent)]"
                        checked={!disabledRules.includes(ruleId)}
                        onChange={() => toggleRule(ruleId)}
                        disabled={!canAdmin}
                      />
                    </label>
                  </li>
                ))}
                {profileRuleIds().length === 0 && (
                  <li className="card-box px-3 py-2 text-[var(--muted)]">
                    No hay reglas configuradas.
                  </li>
                )}
              </ul>
              {!canAdmin && (
                <p className="text-xs text-[var(--muted)]">
                  Solo administradores pueden editar reglas.
                </p>
              )}
              <div className="card-box text-xs text-white/70">
                <p className="text-white/60">Impacto estimado</p>
                {(() => {
                  const baseline = dataset?.rules_config?.disabled_rules ?? [];
                  const current = disabledRules;
                  const total = totalCounts();
                  const baseImpact = totalImpact(baseline);
                  const currentImpact = totalImpact(current);
                  const beforeIssues = Math.max(0, total.issueRows - baseImpact.issues);
                  const afterIssues = Math.max(0, total.issueRows - currentImpact.issues);
                  const beforeAnoms = Math.max(0, total.anomalies - baseImpact.anomalies);
                  const afterAnoms = Math.max(0, total.anomalies - currentImpact.anomalies);
                  return (
                    <div className="grid gap-2">
                      <p>
                        Ahora visibles: {beforeIssues} issues · {beforeAnoms} anomalías
                      </p>
                      <p className="text-[var(--muted)]">
                        Con cambios: {afterIssues} issues · {afterAnoms} anomalías
                      </p>
                      <p className="text-[var(--muted)]">
                        Ocultarías {currentImpact.issues} registros y {currentImpact.anomalies} anomalías.
                      </p>
                      <p className="text-[var(--muted)]">
                        Alta: {currentImpact.high} · Media: {currentImpact.medium} · Baja:{" "}
                        {currentImpact.low}
                      </p>
                    </div>
                  );
                })()}
              </div>
              <div className="flex justify-end gap-2">
                <button className="btn-secondary" onClick={() => setShowRules(false)}>
                  Cancelar
                </button>
                <button
                  className="btn-primary"
                  onClick={saveRules}
                  disabled={savingRules || !canAdmin}
                >
                  {savingRules ? "Guardando..." : "Guardar"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showRuns && (
        <div className="modal-backdrop">
          <div className="modal-panel max-w-4xl space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">Historial</p>
                <h3 className="mt-2 text-xl font-semibold">Todas las corridas</h3>
              </div>
              <button className="btn-secondary" onClick={() => setShowRuns(false)}>
                Cerrar
              </button>
            </div>
            <div className="scroll-soft overflow-auto rounded-xl border border-white/10">
              <table className="table-base table-sm">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Duración</th>
                    <th>Filas</th>
                    <th>Issues</th>
                    <th>Anomalías</th>
                    <th>Riesgo</th>
                    <th>Calidad</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td>{formatDate(run.run_at)}</td>
                      <td className="text-white/60">{formatDuration(run.duration_ms)}</td>
                      <td className="text-white/60">{run.total_rows ?? 0}</td>
                      <td className="text-white/60">{run.issue_rows ?? 0}</td>
                      <td className="text-white/60">{run.anomaly_count ?? 0}</td>
                      <td className="text-white/60">{run.risk_score ?? 0}</td>
                      <td className="text-white/60">{run.quality_score ?? 0}</td>
                    </tr>
                  ))}
                  {runs.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-6 text-center text-sm text-[var(--muted)]">
                        No hay corridas registradas.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
