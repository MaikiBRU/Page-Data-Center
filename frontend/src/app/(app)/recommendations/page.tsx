"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import Link from "next/link";
import { emitToast } from "@/lib/toast";
import { FlowSteps } from "@/components/FlowSteps";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";

interface Dataset {
  id: number;
  name: string;
  domain: string;
  quality_summary?: {
    recommendations?: Recommendation[];
  } | null;
}

type Recommendation = {
  code: string;
  label?: string;
  action: string;
  severity?: string;
  count?: number;
  priority?: string;
  dataset: string;
  dataset_id: number;
  domain?: string;
};

const baseValue = (domain?: string) => {
  if (domain === "ecommerce") return 120;
  if (domain === "logistica") return 90;
  if (domain === "ecommerce-logistica") return 110;
  return 100;
};

const riskPointsFor = (rec: Recommendation) => {
  const count = rec.count ?? 0;
  const severity = rec.severity ?? "medium";
  const weight = severity === "high" ? 1 : severity === "low" ? 0.3 : 0.6;
  return count * weight;
};

const impactFor = (rec: Recommendation) => {
  const count = rec.count ?? 0;
  const severity = rec.severity ?? "medium";
  const weight = severity === "high" ? 1 : severity === "low" ? 0.3 : 0.6;
  return count * weight * baseValue(rec.domain);
};

export default function RecommendationsPage() {
  const router = useRouter();
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [me, setMe] = useState<{ is_admin: boolean; role?: string } | null>(null);
  const [search, setSearch] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [datasetFilter, setDatasetFilter] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [assignableUsers, setAssignableUsers] = useState<
    { id: number; email: string; role: string; is_admin: boolean }[]
  >([]);
  const [assignmentTarget, setAssignmentTarget] = useState("__auto__");
  const [caseStatus, setCaseStatus] = useState("open");
  const [slaHours, setSlaHours] = useState<number | "">("");
  const [customSla, setCustomSla] = useState("");
  const [slaMode, setSlaMode] = useState<"auto" | "preset" | "custom">("auto");
  const [creatingBatch, setCreatingBatch] = useState(false);
  const [showBulkConfirm, setShowBulkConfirm] = useState(false);
  const flow = useFlowData();

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    apiFetch<{ is_admin: boolean; role?: string }>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
    apiFetch<{ id: number; email: string; role: string; is_admin: boolean }[]>(
      "/users/assignable"
    )
      .then(setAssignableUsers)
      .catch(() => setAssignableUsers([]));
    apiFetch<Dataset[]>("/datasets")
      .then((datasets) => {
        const collected: Recommendation[] = [];
        datasets.forEach((dataset) => {
          const recs = dataset.quality_summary?.recommendations ?? [];
          recs.forEach((rec) =>
            collected.push({
              ...rec,
              dataset: dataset.name,
              dataset_id: dataset.id,
              domain: dataset.domain,
            })
          );
        });
        setRecommendations(collected);
      })
      .catch(() => null)
      .finally(() => setLoading(false));
  }, [router]);

  const canEdit = me?.is_admin || me?.role === "analyst";
  const slaSelectValue =
    slaMode === "custom" ? "custom" : slaHours !== "" ? String(slaHours) : "";

  const priorities = useMemo(() => {
    const counts = { alta: 0, media: 0, baja: 0 };
    recommendations.forEach((rec) => {
      const key = (rec.priority as "alta" | "media" | "baja") ?? "baja";
      if (counts[key] !== undefined) counts[key] += 1;
    });
    return counts;
  }, [recommendations]);

  const filtered = recommendations.filter((rec) => {
    const matchSearch =
      !search.trim() ||
      rec.code.toLowerCase().includes(search.trim().toLowerCase()) ||
      (rec.label ?? "").toLowerCase().includes(search.trim().toLowerCase()) ||
      rec.dataset.toLowerCase().includes(search.trim().toLowerCase());
    const matchPriority = !priorityFilter || rec.priority === priorityFilter;
    const matchDataset = !datasetFilter || String(rec.dataset_id) === datasetFilter;
    return matchSearch && matchPriority && matchDataset;
  });

  const selectedList = useMemo(
    () => filtered.filter((rec) => selected[`${rec.dataset_id}-${rec.code}`]),
    [filtered, selected]
  );

  const aggregateImpact = useMemo(() => {
    const list = selectedList.length > 0 ? selectedList : filtered;
    const totalCount = list.reduce((acc, rec) => acc + (rec.count ?? 0), 0);
    const impact = list.reduce((acc, rec) => acc + impactFor(rec), 0);
    const risk = list.reduce((acc, rec) => acc + riskPointsFor(rec), 0);
    return { totalCount, impact, risk };
  }, [filtered, selectedList]);

  const totalRisk = useMemo(() => {
    return recommendations.reduce((acc, rec) => acc + riskPointsFor(rec), 0);
  }, [recommendations]);

  const riskReductionPct = useMemo(() => {
    if (!totalRisk) return 0;
    const applied = selectedList.length > 0 ? selectedList : filtered;
    const appliedRisk = applied.reduce((acc, rec) => acc + riskPointsFor(rec), 0);
    return Math.min(100, Math.round((appliedRisk / totalRisk) * 100));
  }, [filtered, selectedList, totalRisk]);

  const appliedRisk = useMemo(() => {
    const applied = selectedList.length > 0 ? selectedList : filtered;
    return applied.reduce((acc, rec) => acc + riskPointsFor(rec), 0);
  }, [filtered, selectedList]);

  const remainingRisk = useMemo(() => {
    return Math.max(0, totalRisk - appliedRisk);
  }, [totalRisk, appliedRisk]);

  const priorityImpact = useMemo(() => {
    const list = selectedList.length > 0 ? selectedList : filtered;
    const base = { alta: { risk: 0, impact: 0 }, media: { risk: 0, impact: 0 }, baja: { risk: 0, impact: 0 } };
    list.forEach((rec) => {
      const key = (rec.priority as "alta" | "media" | "baja") ?? "baja";
      base[key].risk += riskPointsFor(rec);
      base[key].impact += impactFor(rec);
    });
    return base;
  }, [filtered, selectedList]);

  const datasetImpact = useMemo(() => {
    const list = selectedList.length > 0 ? selectedList : filtered;
    const map = new Map<string, { dataset: string; count: number; risk: number; impact: number }>();
    list.forEach((rec) => {
      const key = `${rec.dataset_id}-${rec.dataset}`;
      if (!map.has(key)) {
        map.set(key, { dataset: rec.dataset, count: 0, risk: 0, impact: 0 });
      }
      const row = map.get(key)!;
      row.count += rec.count ?? 0;
      row.risk += riskPointsFor(rec);
      row.impact += impactFor(rec);
    });
    return Array.from(map.values()).sort((a, b) => b.risk - a.risk);
  }, [filtered, selectedList]);

  const datasetOptions = useMemo(() => {
    const map = new Map<number, string>();
    recommendations.forEach((rec) => map.set(rec.dataset_id, rec.dataset));
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [recommendations]);

  const badgeClass = (priority?: string) => {
    switch (priority) {
      case "alta":
        return "border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]";
      case "media":
        return "border-[var(--warning)]/50 bg-[var(--warning)]/10 text-[var(--warning)]";
      default:
        return "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]";
    }
  };

  const createCaseFromRec = async (rec: Recommendation, silent = false) => {
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para crear casos.", kind: "error" });
      return;
    }
    const autoAssign = assignmentTarget === "__auto__";
    const assignee = assignmentTarget && assignmentTarget !== "__auto__" ? assignmentTarget : null;
    if (slaMode === "custom" && !customSla.trim()) {
      emitToast({ message: "Definí el SLA personalizado.", kind: "info" });
      return;
    }
    const sla =
      slaMode === "preset"
        ? Number(slaHours)
        : slaMode === "custom"
        ? Number(customSla)
        : undefined;
    const label = rec.label ?? rec.code;
    const severity =
      rec.severity ??
      (rec.priority === "alta" ? "high" : rec.priority === "media" ? "medium" : "low");
    const count = rec.count ?? 0;
    const summary = `Se detectaron ${count} registros con ${label} en ${rec.dataset}.`;
    try {
      await apiFetch("/cases", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: rec.dataset_id,
          title: `Recomendación: ${label}`,
          severity,
          status: caseStatus,
          assignee,
          auto_assign: autoAssign,
          summary,
          recommendation: rec.action,
          sla_hours: sla,
        }),
      });
      if (!silent) {
        emitToast({ message: "Caso creado desde recomendación.", kind: "success" });
      }
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const toggleSelectAll = (value: boolean) => {
    const next: Record<string, boolean> = { ...selected };
    filtered.forEach((rec) => {
      next[`${rec.dataset_id}-${rec.code}`] = value;
    });
    setSelected(next);
  };

  const clearSelection = () => setSelected({});

  const requestBulkCreate = () => {
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para crear casos.", kind: "error" });
      return;
    }
    const list = selectedList;
    if (list.length === 0) {
      emitToast({ message: "Seleccioná al menos una recomendación.", kind: "info" });
      return;
    }
    if (slaMode === "custom" && !customSla.trim()) {
      emitToast({ message: "Definí el SLA personalizado.", kind: "info" });
      return;
    }
    setShowBulkConfirm(true);
  };

  const createBulkCases = async () => {
    const list = selectedList;
    const sla =
      slaMode === "preset"
        ? Number(slaHours)
        : slaMode === "custom"
        ? Number(customSla)
        : undefined;
    const autoAssign = assignmentTarget === "__auto__";
    const assignee = assignmentTarget && assignmentTarget !== "__auto__" ? assignmentTarget : null;
    const items = list.map((rec) => {
      const label = rec.label ?? rec.code;
      const severity =
        rec.severity ??
        (rec.priority === "alta" ? "high" : rec.priority === "media" ? "medium" : "low");
      const count = rec.count ?? 0;
      const summary = `Se detectaron ${count} registros con ${label} en ${rec.dataset}.`;
      return {
        dataset_id: rec.dataset_id,
        title: `Recomendación: ${label}`,
        severity,
        status: caseStatus,
        assignee,
        auto_assign: autoAssign,
        summary,
        recommendation: rec.action,
        sla_hours: sla,
      };
    });
    setCreatingBatch(true);
    emitToast({ message: "Creando casos en lote...", kind: "info" });
    try {
      await apiFetch("/cases/bulk-create", {
        method: "POST",
        body: JSON.stringify({ items }),
      });
      emitToast({ message: "Casos creados.", kind: "success" });
      clearSelection();
      setShowBulkConfirm(false);
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setCreatingBatch(false);
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Acciones</p>
        <h2 className="mt-2 text-3xl font-semibold">Recomendaciones</h2>
      </div>

      <FlowSteps flow={flow} />

      <OnboardingCoach
        flow={flow}
        stepKey="recs"
        title="Aplicá recomendaciones"
        description="Seleccioná acciones y creá casos en lote para reducir riesgo."
        actionLabel="Ir a acciones"
        href="#batch-actions"
      />

      <section className="panel grid gap-4 md:grid-cols-[1.2fr_0.8fr] items-center">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Resumen</p>
          <h3 className="mt-2 text-lg font-semibold">Acciones priorizadas</h3>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Filtrá por prioridad o dataset y convertí recomendaciones en casos.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 justify-end text-xs">
          <span className={`badge ${badgeClass("alta")}`}>Alta {priorities.alta}</span>
          <span className={`badge ${badgeClass("media")}`}>Media {priorities.media}</span>
          <span className={`badge ${badgeClass("baja")}`}>Baja {priorities.baja}</span>
        </div>
      </section>

      <section className="panel grid gap-4 md:grid-cols-3">
        <input
          className="input-base"
          placeholder="Buscar por código o dataset"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="input-base"
          value={priorityFilter}
          onChange={(event) => setPriorityFilter(event.target.value)}
        >
          <option value="">Todas las prioridades</option>
          <option value="alta">Alta</option>
          <option value="media">Media</option>
          <option value="baja">Baja</option>
        </select>
        <select
          className="input-base"
          value={datasetFilter}
          onChange={(event) => setDatasetFilter(event.target.value)}
        >
          <option value="">Todos los datasets</option>
          {datasetOptions.map((item) => (
            <option key={item.id} value={String(item.id)}>
              {item.name}
            </option>
          ))}
        </select>
      </section>

      <section className="panel" id="batch-actions">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Impacto agregado</p>
            <p className="mt-2 text-sm text-[var(--muted)]">
              {selectedList.length > 0
                ? `Resumen de ${selectedList.length} seleccionadas.`
                : "Resumen de resultados filtrados."}
            </p>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Riesgo reducido estimado: {riskReductionPct}% del total.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 text-xs">
            <span className="badge">Registros: {aggregateImpact.totalCount}</span>
            <span className="badge">
              Impacto:{" "}
              {new Intl.NumberFormat("es-AR", {
                style: "currency",
                currency: "USD",
                maximumFractionDigits: 0,
              }).format(aggregateImpact.impact)}
            </span>
            <span className="badge">Riesgo: {aggregateImpact.risk.toFixed(1)}</span>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="card-box">
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Riesgo aplicado</p>
            <p className="mt-2 text-lg font-semibold">{appliedRisk.toFixed(1)}</p>
            <p className="text-xs text-[var(--muted)]">
              Acciones cubiertas {selectedList.length > 0 ? selectedList.length : filtered.length}
            </p>
          </div>
          <div className="card-box">
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Riesgo restante</p>
            <p className="mt-2 text-lg font-semibold">{remainingRisk.toFixed(1)}</p>
            <p className="text-xs text-[var(--muted)]">Base total {totalRisk.toFixed(1)}</p>
          </div>
          <div className="card-box">
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Reducción total</p>
            <p className="mt-2 text-lg font-semibold">{riskReductionPct}%</p>
            <div className="mt-3 h-2 w-full rounded-full bg-white/10">
              <div
                className="h-2 rounded-full bg-[var(--accent)]"
                style={{ width: `${riskReductionPct}%` }}
              />
            </div>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <div className="card-box text-xs text-white/70">
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Por prioridad</p>
            <div className="mt-3 grid gap-2">
              <div className="flex items-center justify-between">
                <span>Alta</span>
                <span>
                  Riesgo {priorityImpact.alta.risk.toFixed(1)} ·{" "}
                  {new Intl.NumberFormat("es-AR", {
                    style: "currency",
                    currency: "USD",
                    maximumFractionDigits: 0,
                  }).format(priorityImpact.alta.impact)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Media</span>
                <span>
                  Riesgo {priorityImpact.media.risk.toFixed(1)} ·{" "}
                  {new Intl.NumberFormat("es-AR", {
                    style: "currency",
                    currency: "USD",
                    maximumFractionDigits: 0,
                  }).format(priorityImpact.media.impact)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span>Baja</span>
                <span>
                  Riesgo {priorityImpact.baja.risk.toFixed(1)} ·{" "}
                  {new Intl.NumberFormat("es-AR", {
                    style: "currency",
                    currency: "USD",
                    maximumFractionDigits: 0,
                  }).format(priorityImpact.baja.impact)}
                </span>
              </div>
            </div>
          </div>
          <div className="card-box text-xs text-white/70">
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">
              Datasets con mayor riesgo
            </p>
            {datasetImpact.length === 0 ? (
              <p className="mt-3 text-xs text-[var(--muted)]">Sin datos.</p>
            ) : (
              <div className="mt-3 space-y-2">
                {datasetImpact.slice(0, 5).map((row) => (
                  <div key={row.dataset} className="flex items-center justify-between">
                    <span>{row.dataset}</span>
                    <span>
                      Riesgo {row.risk.toFixed(1)} ·{" "}
                      {new Intl.NumberFormat("es-AR", {
                        style: "currency",
                        currency: "USD",
                        maximumFractionDigits: 0,
                      }).format(row.impact)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        {loading ? (
          <div className="grid gap-3">
            {Array.from({ length: 3 }).map((_, idx) => (
              <div key={`rec-skel-${idx}`} className="skeleton h-16" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title={
              recommendations.length === 0
                ? "Ejecutá una corrida para ver recomendaciones."
                : "No hay coincidencias con tus filtros."
            }
            description={
              recommendations.length === 0
                ? "Corré calidad y regresá para ver acciones recomendadas."
                : "Ajustá filtros o limpiá búsqueda."
            }
            actions={[
              { label: "Ejecutar calidad", href: "/datasets", variant: "primary" },
              { label: "Ver guía rápida", href: "/dashboard", variant: "secondary" },
            ]}
          />
        ) : (
          <div className="grid gap-3">
            <div className="card-box flex flex-wrap items-center justify-between gap-3 text-xs text-white/70">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                  Asignación al crear casos
                </p>
                <p className="mt-2 text-xs text-[var(--muted)]">
                  Se aplica a creación individual y en lote.
                </p>
              </div>
              <select
                className="input-base w-full md:w-72"
                value={assignmentTarget}
                onChange={(event) => setAssignmentTarget(event.target.value)}
                disabled={!canEdit}
              >
                <option value="__auto__">Auto (por dataset)</option>
                <option value="">Sin asignar</option>
                {assignableUsers.map((user) => (
                  <option key={user.id} value={user.email}>
                    {user.email}
                  </option>
                ))}
              </select>
            </div>
            <div className="card-box flex flex-wrap items-center gap-3 text-xs text-white/70">
              <div className="min-w-[220px]">
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                  Estado al crear
                </p>
                <select
                  className="input-base mt-2"
                  value={caseStatus}
                  onChange={(event) => setCaseStatus(event.target.value)}
                  disabled={!canEdit}
                >
                  <option value="open">Open</option>
                  <option value="backlog">Backlog</option>
                  <option value="in_progress">In progress</option>
                </select>
              </div>
              <div className="min-w-[220px]">
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">SLA</p>
                <select
                  className="input-base mt-2"
                  value={slaSelectValue}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (!value || value === "custom") {
                      setSlaHours("");
                      if (value === "custom") {
                        setSlaMode("custom");
                      } else {
                        setSlaMode("auto");
                        setCustomSla("");
                      }
                      return;
                    }
                    setSlaMode("preset");
                    setSlaHours(Number(value));
                    setCustomSla("");
                  }}
                  disabled={!canEdit}
                >
                  <option value="">Auto por severidad</option>
                  {[12, 24, 48, 72, 120, 168].map((hours) => (
                    <option key={hours} value={hours}>
                      {hours} horas
                    </option>
                  ))}
                  <option value="custom">Personalizado</option>
                </select>
              </div>
              {slaSelectValue === "custom" && (
                <div className="min-w-[220px]">
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                    SLA personalizado
                  </p>
                  <input
                    className="input-base mt-2"
                    type="number"
                    min={1}
                    max={168}
                    value={customSla}
                    onChange={(event) => {
                      setCustomSla(event.target.value);
                      setSlaHours("");
                      setSlaMode("custom");
                    }}
                    disabled={!canEdit}
                  />
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-white/60">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-[var(--accent)]"
                  checked={
                    filtered.length > 0 &&
                    filtered.every((rec) => selected[`${rec.dataset_id}-${rec.code}`])
                  }
                  onChange={(event) => toggleSelectAll(event.target.checked)}
                />
                Seleccionar todo lo filtrado
              </label>
              <div className="flex items-center gap-2">
                <button
                  className="btn-mini"
                  onClick={requestBulkCreate}
                  disabled={!canEdit || creatingBatch}
                >
                  Crear casos en lote
                </button>
                <button className="btn-mini" onClick={clearSelection}>
                  Limpiar
                </button>
              </div>
            </div>
            {filtered.map((rec, index) => (
              <div key={`${rec.code}-${index}`} className="card-box">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 accent-[var(--accent)]"
                      checked={Boolean(selected[`${rec.dataset_id}-${rec.code}`])}
                      onChange={(event) =>
                        setSelected((prev) => ({
                          ...prev,
                          [`${rec.dataset_id}-${rec.code}`]: event.target.checked,
                        }))
                      }
                    />
                    <div>
                      <p className="font-medium">{rec.label ?? rec.code}</p>
                      <p className="text-xs text-white/50">{rec.dataset}</p>
                    </div>
                  </label>
                <div className="flex items-center gap-2 text-xs">
                  {rec.count !== undefined && (
                    <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-white/70">
                      {rec.count} casos
                    </span>
                  )}
                  <span className={`badge ${badgeClass(rec.priority)}`}>
                    {(rec.priority ?? "baja").toUpperCase()}
                  </span>
                  <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-white/70">
                    Impacto {new Intl.NumberFormat("es-AR", {
                      style: "currency",
                      currency: "USD",
                      maximumFractionDigits: 0,
                    }).format(impactFor(rec))}
                  </span>
                </div>
                </div>
                <p className="text-xs text-[var(--muted)]">{rec.action}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link className="btn-secondary" href={`/datasets/${rec.dataset_id}`}>
                    Ver dataset
                  </Link>
                  <button
                    className="btn-primary"
                    onClick={() => createCaseFromRec(rec)}
                    disabled={!canEdit}
                  >
                    Crear caso
                  </button>
                </div>
                {!canEdit && (
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Solo administradores o analistas pueden crear casos.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {showBulkConfirm && (
        <div className="modal-backdrop" onClick={() => setShowBulkConfirm(false)}>
          <div
            className="modal-panel max-w-2xl space-y-4"
            onClick={(event) => event.stopPropagation()}
          >
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Batch</p>
              <h3 className="mt-2 text-xl font-semibold">Confirmar creación en lote</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Vas a crear {selectedList.length} casos con estas reglas:
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2 text-xs text-white/70">
              <div className="card-box">
                <p className="text-white/50">Estado</p>
                <p className="mt-1 font-semibold">{caseStatus}</p>
              </div>
              <div className="card-box">
                <p className="text-white/50">Asignación</p>
                <p className="mt-1 font-semibold">
                  {assignmentTarget === "__auto__"
                    ? "Auto por dataset"
                    : assignmentTarget || "Sin asignar"}
                </p>
              </div>
              <div className="card-box">
                <p className="text-white/50">SLA</p>
                <p className="mt-1 font-semibold">
                  {slaMode === "auto"
                    ? "Auto por severidad"
                    : slaMode === "preset"
                    ? `${slaHours}h`
                    : `${customSla}h`}
                </p>
              </div>
              <div className="card-box">
                <p className="text-white/50">Impacto</p>
                <p className="mt-1 font-semibold">
                  {new Intl.NumberFormat("es-AR", {
                    style: "currency",
                    currency: "USD",
                    maximumFractionDigits: 0,
                  }).format(aggregateImpact.impact)}
                </p>
                <p className="mt-1 text-[var(--muted)]">
                  Riesgo reducido {riskReductionPct}%
                </p>
              </div>
            </div>
            <div className="scroll-soft max-h-56 overflow-auto rounded-xl border border-white/10">
              <table className="table-base table-sm">
                <thead>
                  <tr>
                    <th>Recomendación</th>
                    <th>Dataset</th>
                    <th>Casos</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedList.map((rec, idx) => (
                    <tr key={`${rec.dataset_id}-${rec.code}-${idx}`}>
                      <td>{rec.label ?? rec.code}</td>
                      <td>{rec.dataset}</td>
                      <td>{rec.count ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex justify-end gap-3">
              <button className="btn-secondary" onClick={() => setShowBulkConfirm(false)}>
                Cancelar
              </button>
              <button
                className="btn-primary"
                onClick={createBulkCases}
                disabled={creatingBatch}
              >
                {creatingBatch ? "Creando..." : "Confirmar y crear"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
