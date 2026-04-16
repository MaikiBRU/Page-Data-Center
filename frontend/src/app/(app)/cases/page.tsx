"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, API_URL } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { emitToast } from "@/lib/toast";
import { FlowSteps } from "@/components/FlowSteps";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";

interface CaseItem {
  id: number;
  dataset_id: number;
  title: string;
  severity: string;
  status: string;
  assignee?: string | null;
  summary?: string | null;
  recommendation?: string | null;
  due_date?: string | null;
  sla_hours?: number | null;
  blocked_reason?: string | null;
  blocked_until?: string | null;
  escalated_reason?: string | null;
  escalated_level?: number | null;
  escalated_to?: string | null;
  created_at?: string;
  updated_at?: string;
}

interface CaseNote {
  id: number;
  case_id: number;
  author: string;
  note: string;
  created_at: string;
}

interface CaseDetail extends CaseItem {
  notes: CaseNote[];
}

interface TimelineItem {
  type: "created" | "status" | "note" | "assignment" | "sla";
  label: string;
  created_at: string;
  actor?: string | null;
  meta?: {
    from?: string | null;
    to?: string | null;
    from_due?: string | null;
    to_due?: string | null;
    note?: string;
    reason?: string | null;
  } | null;
}

interface DatasetOption {
  id: number;
  name: string;
  domain: string;
}

type CaseSummary = {
  total: number;
  open: number;
  resolved: number;
  overdue: number;
  due_soon: number;
  no_sla: number;
  unassigned: number;
  avg_age_hours: number;
  avg_sla_remaining_hours: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
};

type SlaStateKey = "overdue" | "due_soon" | "on_track" | "none";

const statusOptions = ["backlog", "open", "in_progress", "blocked", "escalated", "resolved"];
const severityOptions = ["high", "medium", "low"];
const slaOptions = [4, 12, 24, 48, 72, 120, 168];
const slaMatrix: Record<string, Record<string, number>> = {
  default: { high: 24, medium: 48, low: 72 },
  ecommerce: { high: 18, medium: 40, low: 72 },
  logistica: { high: 12, medium: 36, low: 72 },
  "ecommerce-logistica": { high: 16, medium: 40, low: 80 },
};

const defaultSlaHours = (severity: string, domain?: string | null) => {
  const matrix = slaMatrix[domain ?? ""] ?? slaMatrix.default;
  return matrix[severity] ?? slaMatrix.default.medium;
};

export default function CasesPage() {
  const router = useRouter();
  const [me, setMe] = useState<{ is_admin: boolean; role?: string; email?: string } | null>(null);
  const initialParams =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search)
      : new URLSearchParams();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [statusFilter, setStatusFilter] = useState(initialParams.get("status") ?? "");
  const [severityFilter, setSeverityFilter] = useState(initialParams.get("severity") ?? "");
  const [datasetFilter, setDatasetFilter] = useState(initialParams.get("dataset_id") ?? "");
  const [search, setSearch] = useState(initialParams.get("q") ?? "");
  const [assigneeFilter, setAssigneeFilter] = useState(initialParams.get("assignee") ?? "");
  const [slaFilter, setSlaFilter] = useState(initialParams.get("sla_state") ?? "");
  const [sort, setSort] = useState(initialParams.get("sort") ?? "recent");
  const [summary, setSummary] = useState<CaseSummary | null>(null);
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [createDatasetId, setCreateDatasetId] = useState<number | "">("");
  const [createTitle, setCreateTitle] = useState("");
  const [createSeverity, setCreateSeverity] = useState("medium");
  const [createStatus, setCreateStatus] = useState("open");
  const [createAssignee, setCreateAssignee] = useState("");
  const [createSlaHours, setCreateSlaHours] = useState<number | "">("");
  const [createCustomSla, setCreateCustomSla] = useState("");
  const [createSummary, setCreateSummary] = useState("");
  const [createRecommendation, setCreateRecommendation] = useState("");
  const [createBlockedReason, setCreateBlockedReason] = useState("");
  const [createBlockedUntil, setCreateBlockedUntil] = useState("");
  const [createEscalatedReason, setCreateEscalatedReason] = useState("");
  const [createEscalatedLevel, setCreateEscalatedLevel] = useState("1");
  const [createEscalatedTo, setCreateEscalatedTo] = useState("");
  const [creating, setCreating] = useState(false);
  const [qualityDatasetId, setQualityDatasetId] = useState<number | "">("");
  const [runningQuality, setRunningQuality] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formTouched, setFormTouched] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const [loadingDatasets, setLoadingDatasets] = useState(true);
  const canEdit = me?.is_admin || me?.role === "analyst";
  const [assignableUsers, setAssignableUsers] = useState<
    { id: number; email: string; role: string; is_admin: boolean }[]
  >([]);
  const [selectedIds, setSelectedIds] = useState<Record<number, boolean>>({});
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkAssignee, setBulkAssignee] = useState("");
  const [bulkSla, setBulkSla] = useState<number | "">("");
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const [viewMode, setViewMode] = useState<"list" | "kanban">("list");
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverStatus, setDragOverStatus] = useState<string | null>(null);
  const [pendingMove, setPendingMove] = useState<{ id: number; from: string; to: string } | null>(
    null
  );
  const [moveReason, setMoveReason] = useState("");
  const [moveBlockedUntil, setMoveBlockedUntil] = useState("");
  const [moveEscalatedLevel, setMoveEscalatedLevel] = useState("1");
  const [moveEscalatedTo, setMoveEscalatedTo] = useState("");
  const flow = useFlowData();
  const slaSelectValue =
    createSlaHours !== "" ? String(createSlaHours) : createCustomSla ? "custom" : "";
  const computedCreateSla = useMemo(() => {
    if (createSlaHours !== "") return Number(createSlaHours);
    if (createCustomSla) return Number(createCustomSla);
    const domain = datasets.find((dataset) => dataset.id === createDatasetId)?.domain;
    return defaultSlaHours(createSeverity, domain);
  }, [createSlaHours, createCustomSla, createSeverity, datasets, createDatasetId]);
  const createDomain = useMemo(
    () => datasets.find((dataset) => dataset.id === createDatasetId)?.domain ?? "default",
    [datasets, createDatasetId]
  );
  const previewDueDate = useMemo(() => {
    if (!Number.isFinite(computedCreateSla)) return null;
    return new Date(Date.now() + computedCreateSla * 60 * 60 * 1000);
  }, [computedCreateSla]);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter) params.append("status", statusFilter);
    if (severityFilter) params.append("severity", severityFilter);
    if (datasetFilter) params.append("dataset_id", datasetFilter);
    if (search.trim()) params.append("q", search.trim());
    if (assigneeFilter) params.append("assignee", assigneeFilter);
    if (slaFilter) params.append("sla_state", slaFilter);
    if (sort) params.append("sort", sort);
    const qs = params.toString();
    return qs ? `?${qs}` : "";
  }, [statusFilter, severityFilter, datasetFilter, search, assigneeFilter, slaFilter, sort]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);
    if (severityFilter) params.set("severity", severityFilter);
    if (datasetFilter) params.set("dataset_id", datasetFilter);
    if (search.trim()) params.set("q", search.trim());
    if (assigneeFilter) params.set("assignee", assigneeFilter);
    if (slaFilter) params.set("sla_state", slaFilter);
    if (sort) params.set("sort", sort);
    const qs = params.toString();
    router.replace(qs ? `/cases?${qs}` : "/cases");
  }, [statusFilter, severityFilter, datasetFilter, search, assigneeFilter, slaFilter, sort, router]);

  const loadCases = useCallback(() => {
    setLoadingCases(true);
    apiFetch<CaseItem[]>(`/cases${queryString}`)
      .then(setCases)
      .catch(() => null)
      .finally(() => setLoadingCases(false));
  }, [queryString]);

  const loadSummary = useCallback(() => {
    apiFetch<CaseSummary>(`/cases/summary${queryString}`)
      .then(setSummary)
      .catch(() => setSummary(null));
  }, [queryString]);

  const loadDatasets = useCallback(() => {
    setLoadingDatasets(true);
    apiFetch<DatasetOption[]>("/datasets")
      .then((data) => {
        setDatasets(data);
        if (data.length > 0) {
          const firstId = data[0].id;
          setCreateDatasetId((prev) => (prev === "" ? firstId : prev));
          setQualityDatasetId((prev) => (prev === "" ? firstId : prev));
        }
      })
      .catch(() => null)
      .finally(() => setLoadingDatasets(false));
  }, []);

  const openCase = async (caseId: number) => {
    setTimelineLoading(true);
    const detail = await apiFetch<CaseDetail>(`/cases/${caseId}`);
    setSelectedCase(detail);
    setNoteText("");
    apiFetch<TimelineItem[]>(`/cases/${caseId}/timeline`)
      .then(setTimeline)
      .catch(() => setTimeline([]))
      .finally(() => setTimelineLoading(false));
  };

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    apiFetch<{ is_admin: boolean; role?: string; email?: string }>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
    apiFetch<{ id: number; email: string; role: string; is_admin: boolean }[]>(
      "/users/assignable"
    )
      .then(setAssignableUsers)
      .catch(() => setAssignableUsers([]));
    loadDatasets();
    loadCases();
    loadSummary();
  }, [router, queryString, loadCases, loadDatasets, loadSummary]);

  useEffect(() => {
    setSelectedIds({});
  }, [queryString]);

  useEffect(() => {
    if (createStatus !== "blocked") {
      setCreateBlockedReason("");
      setCreateBlockedUntil("");
    }
    if (createStatus !== "escalated") {
      setCreateEscalatedReason("");
      setCreateEscalatedLevel("1");
      setCreateEscalatedTo("");
    }
  }, [createStatus]);

  useEffect(() => {
    if (!pendingMove) return;
    setMoveReason("");
    setMoveBlockedUntil("");
    setMoveEscalatedLevel("1");
    setMoveEscalatedTo("");
  }, [pendingMove]);

  const createCase = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    setFormTouched(true);
    const canEdit = me?.is_admin || me?.role === "analyst";
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para crear casos.", kind: "error" });
      return;
    }
    if (!createDatasetId) {
      emitToast({ message: "Seleccioná un dataset.", kind: "info" });
      return;
    }
    const title = createTitle.trim();
    const summary = createSummary.trim();
    const recommendation = createRecommendation.trim();
    if (title.length < 6) {
      setFormError("El título debe tener al menos 6 caracteres.");
      emitToast({ message: "El título debe tener al menos 6 caracteres.", kind: "info" });
      return;
    }
    if (summary.length < 20) {
      setFormError("El resumen debe tener al menos 20 caracteres.");
      emitToast({ message: "El resumen debe tener al menos 20 caracteres.", kind: "info" });
      return;
    }
    if (recommendation.length < 20) {
      setFormError("La recomendación debe tener al menos 20 caracteres.");
      emitToast({ message: "La recomendación debe tener al menos 20 caracteres.", kind: "info" });
      return;
    }
    if (slaSelectValue === "custom" && !createCustomSla.trim()) {
      setFormError("Definí el SLA personalizado.");
      emitToast({ message: "Definí el SLA personalizado.", kind: "info" });
      return;
    }
    if (createStatus === "blocked" && createBlockedReason.trim().length < 8) {
      setFormError("Definí un motivo de bloqueo (mínimo 8 caracteres).");
      emitToast({ message: "Definí un motivo de bloqueo.", kind: "info" });
      return;
    }
    if (createStatus === "escalated" && createEscalatedReason.trim().length < 8) {
      setFormError("Definí un motivo de escalamiento (mínimo 8 caracteres).");
      emitToast({ message: "Definí un motivo de escalamiento.", kind: "info" });
      return;
    }
    const slaHours =
      createSlaHours !== ""
        ? Number(createSlaHours)
        : createCustomSla
        ? Number(createCustomSla)
        : undefined;
    if (slaHours && (Number.isNaN(slaHours) || slaHours < 1 || slaHours > 168)) {
      setFormError("El SLA debe estar entre 1 y 168 horas.");
      emitToast({ message: "El SLA debe estar entre 1 y 168 horas.", kind: "info" });
      return;
    }
    const autoAssign = createAssignee === "__auto__";
    const assigneeValue =
      createAssignee && createAssignee !== "__auto__" ? createAssignee : null;
    setCreating(true);
    try {
      await apiFetch("/cases", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: createDatasetId,
          title,
          severity: createSeverity,
          status: createStatus,
          assignee: assigneeValue,
          auto_assign: autoAssign,
          summary,
          recommendation,
          sla_hours: slaHours,
          blocked_reason: createStatus === "blocked" ? createBlockedReason.trim() : null,
          blocked_until:
            createStatus === "blocked" && createBlockedUntil
              ? fromLocalInput(createBlockedUntil)
              : null,
          escalated_reason:
            createStatus === "escalated" ? createEscalatedReason.trim() : null,
          escalated_level:
            createStatus === "escalated" ? Number(createEscalatedLevel) : null,
          escalated_to:
            createStatus === "escalated" && createEscalatedTo
              ? createEscalatedTo
              : null,
        }),
      });
      emitToast({ message: "Caso creado manualmente.", kind: "success" });
      setCreateTitle("");
      setCreateAssignee("");
      setCreateSlaHours("");
      setCreateCustomSla("");
      setCreateSummary("");
      setCreateRecommendation("");
      setCreateBlockedReason("");
      setCreateBlockedUntil("");
      setCreateEscalatedReason("");
      setCreateEscalatedLevel("1");
      setCreateEscalatedTo("");
      loadCases();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
      setFormError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const isFormValid = () => {
    return (
      Boolean(createDatasetId) &&
      createTitle.trim().length >= 6 &&
      createSummary.trim().length >= 20 &&
      createRecommendation.trim().length >= 20
    );
  };

  const runQuality = async () => {
    const canEdit = me?.is_admin || me?.role === "analyst";
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para ejecutar calidad.", kind: "error" });
      return;
    }
    if (!qualityDatasetId) {
      emitToast({ message: "Seleccioná un dataset.", kind: "info" });
      return;
    }
    setRunningQuality(true);
    try {
      await apiFetch(`/datasets/${qualityDatasetId}/run-quality`, { method: "POST" });
      emitToast({ message: "Corrida de calidad iniciada.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setRunningQuality(false);
    }
  };

  const statusBadge = (status: string) => {
    switch (status) {
      case "blocked":
        return "border-[var(--danger)]/40 bg-[var(--danger)]/10 text-[var(--danger)]";
      case "escalated":
        return "border-[var(--warning)]/50 bg-[var(--warning)]/10 text-[var(--warning)]";
      case "resolved":
        return "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]";
      case "in_progress":
        return "border-[var(--accent)]/40 bg-[var(--accent)]/10 text-[var(--accent-2)]";
      default:
        return "border-white/15 bg-white/5 text-white/70";
    }
  };

  const statusLabel = (status: string) => status.replace("_", " ");

  const slaState = (due?: string | null) => {
    if (!due) return { label: "Sin SLA", tone: "border-white/15 bg-white/5 text-white/60" };
    const dueDate = new Date(due);
    const now = new Date();
    const diffMs = dueDate.getTime() - now.getTime();
    const hours = diffMs / (1000 * 60 * 60);
    if (hours < 0) {
      return { label: "Vencido", tone: "border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]" };
    }
    if (hours <= 24) {
      return { label: "Vence pronto", tone: "border-[var(--warning)]/50 bg-[var(--warning)]/10 text-[var(--warning)]" };
    }
    return { label: "En plazo", tone: "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]" };
  };

  const slaKey = (due?: string | null): SlaStateKey => {
    if (!due) return "none";
    const dueDate = new Date(due);
    const now = new Date();
    const diffMs = dueDate.getTime() - now.getTime();
    const hours = diffMs / (1000 * 60 * 60);
    if (hours < 0) return "overdue";
    if (hours <= 24) return "due_soon";
    return "on_track";
  };

  const formatDate = (value?: string | null) => {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("es-AR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const formatRelative = (due?: string | null) => {
    if (!due) return "Sin SLA";
    const dueDate = new Date(due);
    if (Number.isNaN(dueDate.getTime())) return "Sin SLA";
    const diffMs = dueDate.getTime() - Date.now();
    const absHours = Math.abs(diffMs) / (1000 * 60 * 60);
    const days = Math.floor(absHours / 24);
    const hours = Math.round(absHours % 24);
    const label = days > 0 ? `${days}d ${hours}h` : `${Math.round(absHours)}h`;
    return diffMs < 0 ? `Vencido hace ${label}` : `Vence en ${label}`;
  };

  const slaProgress = (item: CaseItem) => {
    if (!item.due_date || !item.created_at) return null;
    const start = new Date(item.created_at).getTime();
    const end = new Date(item.due_date).getTime();
    if (!start || !end || end <= start) return null;
    const now = Date.now();
    const ratio = Math.min(1, Math.max(0, (now - start) / (end - start)));
    return Math.round(ratio * 100);
  };

  const datasetMap = useMemo(() => {
    const map = new Map<number, DatasetOption>();
    datasets.forEach((dataset) => map.set(dataset.id, dataset));
    return map;
  }, [datasets]);

  const heatmap = useMemo(() => {
    const stateKeys: SlaStateKey[] = ["overdue", "due_soon", "on_track", "none"];
    const base: Record<string, Record<string, number>> = {
      high: { overdue: 0, due_soon: 0, on_track: 0, none: 0 },
      medium: { overdue: 0, due_soon: 0, on_track: 0, none: 0 },
      low: { overdue: 0, due_soon: 0, on_track: 0, none: 0 },
    };
    cases.forEach((item) => {
      const sev = item.severity || "medium";
      const key = slaKey(item.due_date);
      if (base[sev] && stateKeys.includes(key)) {
        base[sev][key] += 1;
      }
    });
    let max = 1;
    Object.values(base).forEach((row) => {
      Object.values(row).forEach((count) => {
        if (count > max) max = count;
      });
    });
    return { data: base, max };
  }, [cases]);

  const metricsByUser = useMemo(() => {
    const rows: Record<
      string,
      { total: number; overdue: number; dueSoon: number; open: number }
    > = {};
    cases.forEach((item) => {
      const key = item.assignee || "Sin asignar";
      if (!rows[key]) {
        rows[key] = { total: 0, overdue: 0, dueSoon: 0, open: 0 };
      }
      rows[key].total += 1;
      if (item.status !== "resolved") rows[key].open += 1;
      const state = slaKey(item.due_date);
      if (state === "overdue") rows[key].overdue += 1;
      if (state === "due_soon") rows[key].dueSoon += 1;
    });
    return Object.entries(rows)
      .map(([assignee, values]) => ({ assignee, ...values }))
      .sort((a, b) => b.overdue - a.overdue || b.total - a.total);
  }, [cases]);

  const leastLoadedAssignee = useMemo(() => {
    const rows = metricsByUser.filter((row) => row.assignee !== "Sin asignar");
    if (!rows.length) return "";
    const sorted = [...rows].sort(
      (a, b) => a.open - b.open || a.overdue - b.overdue || a.total - b.total
    );
    return sorted[0].assignee;
  }, [metricsByUser]);

  const selectedDefaultSla = useMemo(() => {
    if (!selectedCase) return null;
    const domain = datasetMap.get(selectedCase.dataset_id)?.domain;
    return defaultSlaHours(selectedCase.severity, domain);
  }, [selectedCase, datasetMap]);

  const slaPriority = useMemo(() => {
    return cases
      .filter((item) => item.due_date)
      .sort(
        (a, b) =>
          new Date(a.due_date ?? "").getTime() - new Date(b.due_date ?? "").getTime()
      )
      .slice(0, 6);
  }, [cases]);

  const selectedCount = useMemo(
    () => Object.values(selectedIds).filter(Boolean).length,
    [selectedIds]
  );

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedIds({});
      return;
    }
    const next: Record<number, boolean> = {};
    cases.forEach((item) => {
      next[item.id] = true;
    });
    setSelectedIds(next);
  };

  const applyBulk = async () => {
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para editar casos.", kind: "error" });
      return;
    }
    if (selectedCount === 0) {
      emitToast({ message: "Seleccioná al menos un caso.", kind: "info" });
      return;
    }
    if (!bulkStatus && !bulkAssignee && bulkSla === "") {
      emitToast({ message: "Definí un cambio antes de aplicar.", kind: "info" });
      return;
    }
    setBulkUpdating(true);
    try {
      await apiFetch("/cases/bulk", {
        method: "POST",
        body: JSON.stringify({
          case_ids: Object.keys(selectedIds)
            .filter((key) => selectedIds[Number(key)])
            .map(Number),
          status: bulkStatus || undefined,
          assignee:
            bulkAssignee === "__none__"
              ? null
              : bulkAssignee || undefined,
          sla_hours: bulkSla !== "" ? Number(bulkSla) : undefined,
        }),
      });
      emitToast({ message: "Casos actualizados.", kind: "success" });
      setSelectedIds({});
      setBulkStatus("");
      setBulkAssignee("");
      setBulkSla("");
      loadCases();
      loadSummary();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setBulkUpdating(false);
    }
  };

  const autoAssignSelected = async () => {
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para editar casos.", kind: "error" });
      return;
    }
    if (selectedCount === 0) {
      emitToast({ message: "Seleccioná al menos un caso.", kind: "info" });
      return;
    }
    if (!leastLoadedAssignee) {
      emitToast({ message: "No hay usuarios disponibles para asignar.", kind: "info" });
      return;
    }
    setBulkUpdating(true);
    try {
      await apiFetch("/cases/bulk", {
        method: "POST",
        body: JSON.stringify({
          case_ids: Object.keys(selectedIds)
            .filter((key) => selectedIds[Number(key)])
            .map(Number),
          assignee: leastLoadedAssignee,
        }),
      });
      emitToast({ message: `Asignados a ${leastLoadedAssignee}.`, kind: "success" });
      setSelectedIds({});
      loadCases();
      loadSummary();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setBulkUpdating(false);
    }
  };

  const moveCaseStatus = async (
    caseId: number,
    status: string,
    extra?: {
      status_reason?: string | null;
      blocked_reason?: string | null;
      blocked_until?: string | null;
      escalated_reason?: string | null;
      escalated_level?: number | null;
      escalated_to?: string | null;
    }
  ) => {
    const current = cases.find((item) => item.id === caseId);
    if (!current) return;
    setCases((prev) =>
      prev.map((item) => (item.id === caseId ? { ...item, status } : item))
    );
    try {
      await apiFetch(`/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify({
          status,
          status_reason: extra?.status_reason ?? null,
          blocked_reason: extra?.blocked_reason ?? null,
          blocked_until: extra?.blocked_until ?? null,
          escalated_reason: extra?.escalated_reason ?? null,
          escalated_level: extra?.escalated_level ?? null,
          escalated_to: extra?.escalated_to ?? null,
        }),
      });
      emitToast({ message: "Estado actualizado.", kind: "success" });
      loadSummary();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
      loadCases();
    }
  };

  const exportCases = async (format: "csv" | "json") => {
    try {
      const token = getToken();
      if (!token) return;
      const qs = queryString ? `${queryString}&format=${format}` : `?format=${format}`;
      const response = await fetch(
        `${API_URL}/cases/export${qs}`,
        {
          headers: { Authorization: `Bearer ${token}` },
        }
      );
      if (!response.ok) {
        throw new Error("No se pudo exportar");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 10);
      link.href = url;
      link.download = `cases_${stamp}.${format}`;
      link.click();
      window.URL.revokeObjectURL(url);
      emitToast({ message: "Exportación lista.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const downloadCaseReport = async (caseId: number, format: "html" | "pdf") => {
    try {
      const token = getToken();
      if (!token) return;
      const response = await fetch(`${API_URL}/cases/${caseId}/report?format=${format}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error("No se pudo exportar el reporte");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      if (format === "html") {
        window.open(url, "_blank");
      } else {
        const link = document.createElement("a");
        link.href = url;
        link.download = `case_${caseId}.${format}`;
        link.click();
      }
      window.URL.revokeObjectURL(url);
      emitToast({ message: "Reporte generado.", kind: "success" });
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const assignCase = async (caseId: number, assignee: string | null) => {
    const current = cases.find((item) => item.id === caseId);
    if (!current) return;
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para asignar casos.", kind: "error" });
      return;
    }
    try {
      await apiFetch(`/cases/${caseId}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: current.status,
          assignee,
        }),
      });
      emitToast({ message: "Asignación actualizada.", kind: "success" });
      loadCases();
      loadSummary();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const toLocalInput = (value?: string | null) => {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n: number) => `${n}`.padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
      date.getHours()
    )}:${pad(date.getMinutes())}`;
  };

  const fromLocalInput = (value: string) => {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toISOString();
  };

  const saveCase = async () => {
    if (!selectedCase) return;
    const canEdit = me?.is_admin || me?.role === "analyst";
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para editar casos.", kind: "error" });
      return;
    }
    if (
      selectedCase.status === "blocked" &&
      (!selectedCase.blocked_reason || selectedCase.blocked_reason.trim().length < 8)
    ) {
      emitToast({ message: "Definí un motivo de bloqueo.", kind: "info" });
      return;
    }
    if (
      selectedCase.status === "escalated" &&
      (!selectedCase.escalated_reason || selectedCase.escalated_reason.trim().length < 8)
    ) {
      emitToast({ message: "Definí un motivo de escalamiento.", kind: "info" });
      return;
    }
    try {
      await apiFetch(`/cases/${selectedCase.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: selectedCase.status,
          assignee: selectedCase.assignee || null,
          summary: selectedCase.summary,
          recommendation: selectedCase.recommendation,
          due_date: selectedCase.due_date,
          sla_hours: selectedCase.sla_hours,
          blocked_reason: selectedCase.blocked_reason,
          blocked_until: selectedCase.blocked_until,
          escalated_reason: selectedCase.escalated_reason,
          escalated_level: selectedCase.escalated_level,
          escalated_to: selectedCase.escalated_to,
        }),
      });
      emitToast({ message: "Caso actualizado.", kind: "success" });
      await loadCases();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  const addNote = async () => {
    if (!selectedCase) return;
    const canEdit = me?.is_admin || me?.role === "analyst";
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para agregar notas.", kind: "error" });
      return;
    }
    if (!noteText.trim()) {
      emitToast({ message: "Escribí una nota antes de guardar.", kind: "info" });
      return;
    }
    try {
      await apiFetch(`/cases/${selectedCase.id}/notes`, {
        method: "POST",
        body: JSON.stringify({ note: noteText.trim() }),
      });
      emitToast({ message: "Nota agregada.", kind: "success" });
      await openCase(selectedCase.id);
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Casos</p>
        <h2 className="mt-2 text-3xl font-semibold">Workflow de incidentes</h2>
      </div>

      <FlowSteps flow={flow} />

      <OnboardingCoach
        flow={flow}
        stepKey="cases"
        title="Gestioná los casos críticos"
        description="Asigna responsables, define SLA y mueve estados para resolver incidencias."
        actionLabel="Crear caso manual"
        href="#manual-case"
        secondaryLabel="Ejecutar calidad"
        secondaryHref="#quality-run"
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <div className="panel kpi-card">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Total</p>
          <p className="mt-3 text-2xl font-semibold">{summary?.total ?? 0}</p>
          <p className="text-xs text-[var(--muted)]">Casos monitoreados</p>
        </div>
        <div className="panel kpi-card">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Abiertos</p>
          <p className="mt-3 text-2xl font-semibold">{summary?.open ?? 0}</p>
          <p className="text-xs text-[var(--muted)]">En workflow</p>
        </div>
        <div className="panel kpi-card">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Vencidos</p>
          <p className="mt-3 text-2xl font-semibold text-[var(--danger)]">
            {summary?.overdue ?? 0}
          </p>
          <p className="text-xs text-[var(--muted)]">SLA fuera de tiempo</p>
        </div>
        <div className="panel kpi-card">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Por vencer</p>
          <p className="mt-3 text-2xl font-semibold text-[var(--warning)]">
            {summary?.due_soon ?? 0}
          </p>
          <p className="text-xs text-[var(--muted)]">Próximas 24h</p>
        </div>
        <div className="panel kpi-card">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Sin asignar</p>
          <p className="mt-3 text-2xl font-semibold">{summary?.unassigned ?? 0}</p>
          <p className="text-xs text-[var(--muted)]">Necesitan owner</p>
        </div>
      </section>

      <section className="panel grid gap-4 md:grid-cols-6">
        <div className="md:col-span-2">
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Buscar</p>
          <input
            className="input-base mt-2"
            placeholder="Título, resumen, recomendación"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Estado</p>
          <select
            className="input-base mt-2"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">Todos</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Severidad</p>
          <select
            className="input-base mt-2"
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value)}
          >
            <option value="">Todas</option>
            {severityOptions.map((sev) => (
              <option key={sev} value={sev}>
                {sev}
              </option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">SLA</p>
          <select
            className="input-base mt-2"
            value={slaFilter}
            onChange={(event) => setSlaFilter(event.target.value)}
          >
            <option value="">Todos</option>
            <option value="overdue">Vencidos</option>
            <option value="due_soon">Vence pronto</option>
            <option value="on_track">En plazo</option>
            <option value="none">Sin SLA</option>
          </select>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Asignado</p>
          <select
            className="input-base mt-2"
            value={assigneeFilter}
            onChange={(event) => setAssigneeFilter(event.target.value)}
          >
            <option value="">Todos</option>
            <option value="__none__">Sin asignar</option>
            {assignableUsers.map((user) => (
              <option key={user.id} value={user.email}>
                {user.email}
              </option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Dataset</p>
          <select
            className="input-base mt-2"
            value={datasetFilter}
            onChange={(event) => setDatasetFilter(event.target.value)}
            disabled={loadingDatasets}
          >
            <option value="">Todos</option>
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">Orden</p>
          <select
            className="input-base mt-2"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="recent">Más recientes</option>
            <option value="updated">Actualizados</option>
            <option value="sla">SLA próximo</option>
            <option value="severity">Severidad</option>
            <option value="oldest">Más antiguos</option>
          </select>
        </div>
        <div className="flex items-end gap-2 md:col-span-2">
          {me?.email && (
            <button
              className="btn-secondary w-full"
              onClick={() => setAssigneeFilter(me.email ?? "")}
            >
              Mis casos
            </button>
          )}
          <button
            className="btn-secondary w-full"
            onClick={() => {
              setStatusFilter("");
              setSeverityFilter("");
              setDatasetFilter("");
              setSearch("");
              setAssigneeFilter("");
              setSlaFilter("");
              setSort("recent");
            }}
          >
            Limpiar
          </button>
          <button className="btn-secondary w-full" onClick={() => exportCases("csv")}>
            Exportar CSV
          </button>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
        <div className="panel flex flex-col gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Opción 1</p>
            <h3 className="mt-2 text-xl font-semibold">Corrida de calidad</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Ejecuta reglas y anomalías para generar casos automáticamente.
            </p>
          </div>
          <div id="quality-run" />
          <label className="text-sm text-white/70">
            Dataset
            <select
              className="input-base mt-2"
              value={qualityDatasetId}
              onChange={(event) => setQualityDatasetId(Number(event.target.value))}
              disabled={loadingDatasets || !canEdit}
            >
              {datasets.length === 0 && !loadingDatasets && (
                <option value="">Sin datasets</option>
              )}
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </label>
          {!loadingDatasets && datasets.length === 0 && (
            <div className="text-xs text-[var(--muted)]">
              Creá un dataset para poder ejecutar calidad.{" "}
              <Link className="text-[var(--accent-2)] underline" href="/datasets">
                Ir a Datasets
              </Link>
            </div>
          )}
          <button
            className="btn-primary"
            onClick={runQuality}
            disabled={runningQuality || (!loadingDatasets && datasets.length === 0) || !canEdit}
          >
            {runningQuality ? "Ejecutando..." : "Ejecutar calidad"}
          </button>
          {!canEdit && (
            <p className="text-xs text-[var(--muted)]">
              Solo administradores o analistas pueden ejecutar calidad.
            </p>
          )}
        </div>

        <form onSubmit={createCase} className="panel grid gap-4" id="manual-case">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Opción 2</p>
            <div className="mt-2 flex items-center gap-3">
              <h3 className="text-xl font-semibold">Crear caso manual</h3>
              {isFormValid() && (
                <span className="rounded-full border border-[var(--success)]/40 bg-[var(--success)]/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-[var(--success)]">
                  Listo
                </span>
              )}
            </div>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Registrá un incidente con contexto, severidad y recomendación.
            </p>
          </div>
          {formError && <p className="text-sm text-[var(--danger)]">{formError}</p>}
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm text-white/70">
              Dataset
              <select
                className={`input-base mt-2 ${
                  formTouched && !createDatasetId
                    ? "border-[var(--danger)]/60"
                    : formTouched
                    ? "border-[var(--success)]/40"
                    : ""
                }`}
                value={createDatasetId}
                onChange={(event) => setCreateDatasetId(Number(event.target.value))}
                disabled={loadingDatasets || !canEdit}
              >
                {datasets.length === 0 && !loadingDatasets && (
                  <option value="">Sin datasets</option>
                )}
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            </label>
            {!loadingDatasets && datasets.length === 0 && (
              <p className="text-xs text-[var(--muted)] md:col-span-2">
                No hay datasets disponibles.{" "}
                <Link className="text-[var(--accent-2)] underline" href="/datasets">
                  Creá uno en Datasets
                </Link>
                .
              </p>
            )}
            <label className="text-sm text-white/70">
              Título
              <input
                className={`input-base mt-2 ${
                  formTouched && createTitle.trim().length < 6
                    ? "border-[var(--danger)]/60"
                    : formTouched
                    ? "border-[var(--success)]/40"
                    : ""
                }`}
                value={createTitle}
                onChange={(event) => setCreateTitle(event.target.value)}
                placeholder="Ej: Direcciones incompletas"
                minLength={6}
                maxLength={140}
                required
                disabled={!canEdit}
              />
              <p className="mt-2 text-xs text-[var(--muted)]">
                {createTitle.trim().length}/140
              </p>
              {formTouched && createTitle.trim().length < 6 && (
                <p className="mt-2 text-xs text-[var(--danger)]">
                  Mínimo 6 caracteres.
                </p>
              )}
            </label>
            <label className="text-sm text-white/70">
              Severidad
              <select
                className="input-base mt-2"
                value={createSeverity}
                onChange={(event) => setCreateSeverity(event.target.value)}
                disabled={!canEdit}
              >
                {severityOptions.map((severity) => (
                  <option key={severity} value={severity}>
                    {severity}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-white/70">
              Estado
              <select
                className="input-base mt-2"
                value={createStatus}
                onChange={(event) => setCreateStatus(event.target.value)}
                disabled={!canEdit}
              >
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm text-white/70 md:col-span-2">
              Asignado a
              <select
                className="input-base mt-2"
                value={createAssignee}
                onChange={(event) => setCreateAssignee(event.target.value)}
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
              <p className="mt-2 text-xs text-[var(--muted)]">
                {createAssignee === "__auto__"
                  ? "Usa la regla de asignación del dataset."
                  : "Elegí un responsable o dejalo sin asignar."}
              </p>
            </label>
            {createStatus === "blocked" && (
              <>
                <label className="text-sm text-white/70 md:col-span-2">
                  Motivo de bloqueo
                  <textarea
                    className="input-base mt-2 h-20"
                    value={createBlockedReason}
                    onChange={(event) => setCreateBlockedReason(event.target.value)}
                    placeholder="Ej: Falta validación de integración externa."
                    disabled={!canEdit}
                  />
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Explicá qué impide avanzar y qué falta.
                  </p>
                </label>
                <label className="text-sm text-white/70 md:col-span-2">
                  Revisión esperada (opcional)
                  <input
                    className="input-base mt-2"
                    type="datetime-local"
                    value={createBlockedUntil}
                    onChange={(event) => setCreateBlockedUntil(event.target.value)}
                    disabled={!canEdit}
                  />
                </label>
              </>
            )}
            {createStatus === "escalated" && (
              <>
                <label className="text-sm text-white/70 md:col-span-2">
                  Motivo de escalamiento
                  <textarea
                    className="input-base mt-2 h-20"
                    value={createEscalatedReason}
                    onChange={(event) => setCreateEscalatedReason(event.target.value)}
                    placeholder="Ej: Impacto directo en entregas, requiere liderazgo."
                    disabled={!canEdit}
                  />
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Resumí por qué se eleva y qué decisión se requiere.
                  </p>
                </label>
                <label className="text-sm text-white/70">
                  Nivel de escalamiento
                  <select
                    className="input-base mt-2"
                    value={createEscalatedLevel}
                    onChange={(event) => setCreateEscalatedLevel(event.target.value)}
                    disabled={!canEdit}
                  >
                    <option value="1">Nivel 1</option>
                    <option value="2">Nivel 2</option>
                    <option value="3">Nivel 3</option>
                  </select>
                </label>
                <label className="text-sm text-white/70 md:col-span-1">
                  Escalar a
                  <select
                    className="input-base mt-2"
                    value={createEscalatedTo}
                    onChange={(event) => setCreateEscalatedTo(event.target.value)}
                    disabled={!canEdit}
                  >
                    <option value="">Sin asignar</option>
                    {assignableUsers.map((user) => (
                      <option key={user.id} value={user.email}>
                        {user.email}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <label className="text-sm text-white/70 md:col-span-2">
              SLA (horas)
              <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr]">
                <select
                  className="input-base"
                  value={slaSelectValue}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (!value || value === "custom") {
                      setCreateSlaHours("");
                      if (value !== "custom") setCreateCustomSla("");
                      return;
                    }
                    setCreateSlaHours(Number(value));
                    setCreateCustomSla("");
                  }}
                  disabled={!canEdit}
                >
                  <option value="">Auto por severidad</option>
                  {slaOptions.map((hours) => (
                    <option key={hours} value={hours}>
                      {hours} horas
                    </option>
                  ))}
                  <option value="custom">Personalizado</option>
                </select>
                {slaSelectValue === "custom" && (
                  <input
                    className="input-base"
                    type="number"
                    placeholder="Horas personalizadas"
                    value={createCustomSla}
                    onChange={(event) => {
                      setCreateCustomSla(event.target.value);
                      setCreateSlaHours("");
                    }}
                    min={1}
                    max={168}
                    disabled={!canEdit}
                  />
                )}
              </div>
              <p className="mt-2 text-xs text-[var(--muted)]">
                Si no elegís, se asigna por severidad (24/48/72h).
              </p>
              {previewDueDate && (
                <p className="mt-1 text-xs text-white/60">
                  Vence estimado: {formatDate(previewDueDate.toISOString())} ·{" "}
                  {formatRelative(previewDueDate.toISOString())}
                </p>
              )}
              <p className="mt-1 text-xs text-white/50">
                Regla SLA dominio: {createDomain} · Default {defaultSlaHours(createSeverity, createDomain)}h
              </p>
            </label>
            <label className="text-sm text-white/70 md:col-span-2">
              Resumen
              <textarea
                className={`input-base mt-2 h-24 ${
                  formTouched && createSummary.trim().length < 20
                    ? "border-[var(--danger)]/60"
                    : formTouched
                    ? "border-[var(--success)]/40"
                    : ""
                }`}
                value={createSummary}
                onChange={(event) => setCreateSummary(event.target.value)}
                placeholder="Contexto del caso y alcance del impacto"
                minLength={20}
                maxLength={600}
                required
                disabled={!canEdit}
              />
              <p className="mt-2 text-xs text-[var(--muted)]">
                Mínimo 20 caracteres. Sé concreto sobre el impacto.
              </p>
              <p className="mt-1 text-xs text-[var(--muted)]">
                {createSummary.trim().length}/600
              </p>
              {formTouched && createSummary.trim().length < 20 && (
                <p className="mt-1 text-xs text-[var(--danger)]">
                  El resumen es obligatorio.
                </p>
              )}
            </label>
            <label className="text-sm text-white/70 md:col-span-2">
              Recomendación
              <textarea
                className={`input-base mt-2 h-24 ${
                  formTouched && createRecommendation.trim().length < 20
                    ? "border-[var(--danger)]/60"
                    : formTouched
                    ? "border-[var(--success)]/40"
                    : ""
                }`}
                value={createRecommendation}
                onChange={(event) => setCreateRecommendation(event.target.value)}
                placeholder="Pasos sugeridos para resolver"
                minLength={20}
                maxLength={600}
                required
                disabled={!canEdit}
              />
              <p className="mt-2 text-xs text-[var(--muted)]">
                Mínimo 20 caracteres. Indicá los pasos propuestos.
              </p>
              <p className="mt-1 text-xs text-[var(--muted)]">
                {createRecommendation.trim().length}/600
              </p>
              {formTouched && createRecommendation.trim().length < 20 && (
                <p className="mt-1 text-xs text-[var(--danger)]">
                  La recomendación es obligatoria.
                </p>
              )}
            </label>
          </div>
          <div className="flex justify-end">
            <button
              className="btn-primary"
              type="submit"
              disabled={creating || (!loadingDatasets && datasets.length === 0) || !canEdit}
            >
              {creating ? "Creando..." : "Crear caso"}
            </button>
          </div>
          {!canEdit && (
            <p className="text-xs text-[var(--muted)]">
              Solo administradores o analistas pueden crear casos.
            </p>
          )}
        </form>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="panel">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">SLA</p>
              <h3 className="mt-2 text-lg font-semibold">Heatmap por severidad</h3>
              <p className="mt-1 text-xs text-[var(--muted)]">
                Vencidos, por vencer y en plazo por severidad.
              </p>
            </div>
          </div>
          <div className="mt-4 grid gap-3">
            {(["high", "medium", "low"] as const).map((sev) => (
              <div key={sev} className="grid grid-cols-[90px_repeat(4,1fr)] items-center gap-2">
                <span className="text-xs uppercase tracking-[0.2em] text-white/50">{sev}</span>
                {(["overdue", "due_soon", "on_track", "none"] as const).map((key) => {
                  const count = heatmap.data[sev][key];
                  const intensity = Math.max(0.1, count / heatmap.max);
                  const tone =
                    key === "overdue"
                      ? "var(--danger)"
                      : key === "due_soon"
                      ? "var(--warning)"
                      : key === "on_track"
                      ? "var(--success)"
                      : "rgba(255,255,255,0.25)";
                  return (
                    <div
                      key={`${sev}-${key}`}
                      className="rounded-xl border border-white/10 px-3 py-2 text-xs"
                      style={{
                        background: `linear-gradient(120deg, ${tone} ${intensity * 12}%, rgba(255,255,255,0.04))`,
                      }}
                    >
                      <div className="flex items-center justify-between text-white/80">
                        <span>
                          {key === "overdue"
                            ? "Vencidos"
                            : key === "due_soon"
                            ? "Pronto"
                            : key === "on_track"
                            ? "En plazo"
                            : "Sin SLA"}
                        </span>
                        <span>{count}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Usuarios</p>
            <h3 className="mt-2 text-lg font-semibold">Métricas por owner</h3>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Distribución de casos y SLA por responsable.
            </p>
          </div>
          <div className="mt-4 overflow-hidden rounded-2xl border border-white/10">
            <table className="table-base text-sm">
              <thead>
                <tr>
                  <th className="px-4 py-3">Responsable</th>
                  <th className="px-4 py-3">Total</th>
                  <th className="px-4 py-3">Abiertos</th>
                  <th className="px-4 py-3">Vencidos</th>
                  <th className="px-4 py-3">Por vencer</th>
                </tr>
              </thead>
              <tbody>
                {metricsByUser.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-sm text-[var(--muted)]">
                      No hay datos para mostrar.
                    </td>
                  </tr>
                ) : (
                  metricsByUser.map((row) => (
                    <tr key={row.assignee}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span>{row.assignee}</span>
                          {row.assignee === leastLoadedAssignee && (
                            <span className="badge">Sugerido</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-white/70">{row.total}</td>
                      <td className="px-4 py-3 text-white/70">{row.open}</td>
                      <td className="px-4 py-3 text-[var(--danger)]">{row.overdue}</td>
                      <td className="px-4 py-3 text-[var(--warning)]">{row.dueSoon}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Prioridades</p>
            <h3 className="mt-2 text-lg font-semibold">SLA más críticos</h3>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Los próximos a vencer o vencidos según deadline.
            </p>
          </div>
          <button className="btn-secondary" onClick={() => setSlaFilter("due_soon")}>
            Ver por vencer
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {slaPriority.length === 0 ? (
            <EmptyState
              title="No hay SLA críticos."
              description="Cuando existan casos cercanos al vencimiento aparecerán aquí."
              compact
            />
          ) : (
            slaPriority.map((item) => (
              <div key={item.id} className="card-box">
                <div className="flex items-center justify-between text-xs text-white/50">
                  <span>#{item.id}</span>
                  <span className={`badge ${slaState(item.due_date).tone}`}>
                    {slaState(item.due_date).label}
                  </span>
                </div>
                <p className="mt-2 text-sm font-medium">{item.title}</p>
                <p className="text-xs text-[var(--muted)]">
                  {datasetMap.get(item.dataset_id)?.name ?? `#${item.dataset_id}`}
                </p>
                <p className="mt-2 text-xs text-white/60">
                  {formatRelative(item.due_date)} · {formatDate(item.due_date)}
                </p>
                <div className="mt-2 flex gap-2">
                  <button className="btn-mini" onClick={() => openCase(item.id)}>
                    Abrir
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Backlog</p>
            <h3 className="mt-2 text-lg font-semibold">
              {cases.length} casos encontrados
            </h3>
            <p className="text-xs text-[var(--muted)]">
              Edad promedio: {summary?.avg_age_hours ?? 0}h · SLA restante:{" "}
              {summary?.avg_sla_remaining_hours ?? 0}h
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className={viewMode === "list" ? "btn-primary" : "btn-secondary"}
              onClick={() => setViewMode("list")}
            >
              Lista
            </button>
            <button
              className={viewMode === "kanban" ? "btn-primary" : "btn-secondary"}
              onClick={() => setViewMode("kanban")}
            >
              Kanban
            </button>
            <button className="btn-secondary" onClick={() => exportCases("json")}>
              Exportar JSON
            </button>
            <button className="btn-secondary" onClick={() => exportCases("csv")}>
              Exportar CSV
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-xs text-white/70">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[var(--accent)]"
              checked={cases.length > 0 && selectedCount === cases.length}
                onChange={(event) => toggleSelectAll(event.target.checked)}
              />
              Seleccionar todo
            </label>
            <div className="text-xs text-white/60">
              Seleccionados: {selectedCount}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto_auto]">
            <select
              className="input-base"
              value={bulkStatus}
              onChange={(event) => setBulkStatus(event.target.value)}
              disabled={!canEdit}
            >
              <option value="">Cambiar estado…</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <select
              className="input-base"
              value={bulkAssignee}
              onChange={(event) => setBulkAssignee(event.target.value)}
              disabled={!canEdit}
            >
              <option value="">Asignar a…</option>
              <option value="__none__">Quitar asignación</option>
              {assignableUsers.map((user) => (
                <option key={user.id} value={user.email}>
                  {user.email}
                </option>
              ))}
            </select>
            <select
              className="input-base"
              value={bulkSla}
              onChange={(event) =>
                setBulkSla(event.target.value ? Number(event.target.value) : "")
              }
              disabled={!canEdit}
            >
              <option value="">SLA rápido…</option>
              {slaOptions.map((hours) => (
                <option key={hours} value={hours}>
                  {hours} horas
                </option>
              ))}
            </select>
            <button
              className="btn-primary"
              onClick={applyBulk}
              disabled={bulkUpdating || !canEdit}
            >
              {bulkUpdating ? "Aplicando..." : "Aplicar"}
            </button>
            <button
              className="btn-secondary"
              onClick={autoAssignSelected}
              disabled={bulkUpdating || !canEdit}
            >
              Auto-asignar
            </button>
          </div>
          {!canEdit && (
            <p className="text-xs text-[var(--muted)]">
              Solo administradores o analistas pueden editar casos.
            </p>
          )}
        </div>

        {viewMode === "list" ? (
          <div className="mt-6 grid gap-3">
            {loadingCases ? (
              Array.from({ length: 3 }).map((_, index) => (
                <div key={`case-skel-${index}`} className="skeleton h-16" />
              ))
          ) : cases.length === 0 ? (
            <EmptyState
              title="Sin casos encontrados."
              description="Ejecutá una corrida o creá un caso manual para comenzar."
              actions={
                canEdit
                  ? [
                      { label: "Ejecutar calidad", href: "#quality-run", variant: "secondary" },
                      { label: "Crear caso manual", href: "#manual-case", variant: "primary" },
                    ]
                  : []
              }
            />
          ) : (
              cases.map((item) => {
                const datasetName = datasetMap.get(item.dataset_id)?.name ?? `#${item.dataset_id}`;
                const due = slaState(item.due_date);
                const progress = slaProgress(item);
                return (
                  <div
                    key={item.id}
                    className="card-row cursor-pointer"
                    onClick={() => openCase(item.id)}
                  >
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 accent-[var(--accent)]"
                        checked={Boolean(selectedIds[item.id])}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) =>
                          setSelectedIds((prev) => ({
                            ...prev,
                            [item.id]: event.target.checked,
                          }))
                        }
                      />
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium">{item.title}</p>
                          <span className="text-xs text-white/40">#{item.id}</span>
                        </div>
                        <p className="text-xs text-[var(--muted)]">
                          Dataset: {datasetName}
                        </p>
                        {item.assignee && (
                          <p className="mt-1 text-xs text-[var(--muted)]">
                            Asignado a: {item.assignee}
                          </p>
                        )}
                        {item.status === "blocked" && item.blocked_reason && (
                          <p className="mt-1 text-xs text-[var(--warning)]">
                            Bloqueado: {item.blocked_reason}
                          </p>
                        )}
                        {item.status === "blocked" && item.blocked_until && (
                          <p className="mt-1 text-xs text-[var(--muted)]">
                            Revisión: {formatDate(item.blocked_until)}
                          </p>
                        )}
                        {item.status === "escalated" && (
                          <p className="mt-1 text-xs text-[var(--warning)]">
                            Escalado nivel {item.escalated_level ?? 1}
                            {item.escalated_to ? ` → ${item.escalated_to}` : ""}
                          </p>
                        )}
                        <p className="mt-1 text-xs text-white/50">{formatRelative(item.due_date)}</p>
                        {progress !== null && (
                          <div className="mt-2 h-1.5 w-full rounded-full bg-white/10">
                            <div
                              className="h-1.5 rounded-full bg-[var(--accent)]"
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-2 text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`badge ${statusBadge(item.status)}`}>
                          {statusLabel(item.status)}
                        </span>
                        <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-white/70">
                          {item.severity}
                        </span>
                        <span className={`badge ${due.tone}`}>{due.label}</span>
                      </div>
                      <div className="text-xs text-white/50">
                        {item.due_date ? `Deadline ${formatDate(item.due_date)}` : "Sin SLA"}
                      </div>
                      <select
                        className="input-base h-8 w-40 text-xs"
                        value={item.assignee ?? ""}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) =>
                          assignCase(item.id, event.target.value ? event.target.value : null)
                        }
                        disabled={!canEdit}
                      >
                        <option value="">Sin asignar</option>
                        {assignableUsers.map((user) => (
                          <option key={user.id} value={user.email}>
                            {user.email}
                          </option>
                        ))}
                      </select>
                      <div className="flex gap-2">
                        {me?.email && (
                          <button
                            className="btn-mini"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedIds((prev) => ({ ...prev, [item.id]: true }));
                              setBulkAssignee(me.email ?? "");
                            }}
                          >
                            Asignarme
                          </button>
                        )}
                        <button
                          className="btn-mini"
                          onClick={(event) => {
                            event.stopPropagation();
                            openCase(item.id);
                          }}
                        >
                          Abrir
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        ) : (
          <div className="mt-6 grid gap-4 overflow-x-auto lg:grid-cols-6">
            {statusOptions.map((status) => {
              const column = cases.filter((item) => item.status === status);
              return (
                <div
                  key={status}
                  className={`kanban-column min-w-[220px] rounded-2xl border border-white/10 bg-white/5 p-3 ${
                    dragOverStatus === status ? "kanban-column-active" : ""
                  }`}
                  onDragOver={(event) => {
                    if (!canEdit) return;
                    event.preventDefault();
                    setDragOverStatus(status);
                  }}
                  onDragLeave={() => setDragOverStatus(null)}
                  onDrop={(event) => {
                    if (!canEdit) return;
                    event.preventDefault();
                    if (draggingId) {
                      const current = cases.find((item) => item.id === draggingId);
                      if (current && current.status !== status) {
                        setPendingMove({ id: draggingId, from: current.status, to: status });
                      }
                    }
                    setDragOverStatus(null);
                    setDraggingId(null);
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs uppercase tracking-[0.2em] text-white/50">
                      {statusLabel(status)}
                    </span>
                    <span className="text-xs text-white/60">{column.length}</span>
                  </div>
                  <div className="mt-3 grid gap-3">
                    {column.length === 0 ? (
                      <EmptyState
                        title="Sin casos"
                        description="Mové un caso o creá uno manual."
                        compact
                      />
                    ) : (
                      column.map((item) => {
                        const due = slaState(item.due_date);
                        return (
                          <button
                            key={item.id}
                            className={`card-box text-left kanban-card ${
                              draggingId === item.id ? "opacity-60 scale-[0.98]" : ""
                            }`}
                            onClick={() => openCase(item.id)}
                            draggable={canEdit}
                            onDragStart={() => canEdit && setDraggingId(item.id)}
                            onDragEnd={() => setDraggingId(null)}
                          >
                            <div className="flex items-center justify-between text-xs text-white/50">
                              <span>#{item.id}</span>
                              <span className={`badge ${due.tone}`}>{due.label}</span>
                            </div>
                            <p className="mt-2 text-sm font-medium">{item.title}</p>
                            <p className="mt-1 text-xs text-[var(--muted)]">
                              {datasetMap.get(item.dataset_id)?.name ?? `#${item.dataset_id}`}
                            </p>
                            {item.status === "blocked" && item.blocked_reason && (
                              <p className="mt-1 text-xs text-[var(--warning)]">
                                Bloqueado: {item.blocked_reason}
                              </p>
                            )}
                            {item.status === "escalated" && (
                              <p className="mt-1 text-xs text-[var(--warning)]">
                                Escalado nivel {item.escalated_level ?? 1}
                              </p>
                            )}
                            <p className="mt-1 text-xs text-white/50">
                              {formatRelative(item.due_date)}
                            </p>
                            <div className="mt-2 flex items-center gap-2 text-xs">
                              <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-white/70">
                                {item.severity}
                              </span>
                              {item.assignee && (
                                <span className="text-white/50">{item.assignee}</span>
                              )}
                            </div>
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {selectedCase && (
        <div className="modal-backdrop">
          <div className="modal-panel relative max-h-[85vh] w-[92vw] max-w-4xl overflow-hidden">
            <button
              className="absolute right-6 top-6 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70"
              onClick={() => setSelectedCase(null)}
            >
              Cerrar
            </button>
            <div className="scroll-soft flex flex-col gap-6 overflow-auto pr-2 max-h-[75vh]">
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">Caso</p>
                <h3 className="mt-2 text-xl font-semibold">{selectedCase.title}</h3>
                <p className="mt-2 text-sm text-[var(--muted)]">
                  Dataset{" "}
                  <Link
                    className="text-[var(--accent-2)] underline"
                    href={`/datasets/${selectedCase.dataset_id}`}
                  >
                    {datasetMap.get(selectedCase.dataset_id)?.name ?? `#${selectedCase.dataset_id}`}
                  </Link>{" "}
                  · {selectedCase.severity}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                  <span className={`badge ${statusBadge(selectedCase.status)}`}>
                    {statusLabel(selectedCase.status)}
                  </span>
                  <span className={`badge ${slaState(selectedCase.due_date).tone}`}>
                    {slaState(selectedCase.due_date).label}
                  </span>
                  {selectedCase.due_date && (
                    <span className="text-white/50">Vence {formatDate(selectedCase.due_date)}</span>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-white/50">
                  <span>ID #{selectedCase.id}</span>
                  <span>
                    Actualizado {formatDate(selectedCase.updated_at ?? selectedCase.created_at)}
                  </span>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    className="btn-secondary"
                    onClick={() => downloadCaseReport(selectedCase.id, "html")}
                  >
                    Ver reporte
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => downloadCaseReport(selectedCase.id, "pdf")}
                  >
                    Exportar PDF
                  </button>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Estado</p>
                  <select
                    className="input-base mt-2"
                    value={selectedCase.status}
                    onChange={(event) => {
                      const nextStatus = event.target.value;
                      setSelectedCase({
                        ...selectedCase,
                        status: nextStatus,
                        blocked_reason: nextStatus === "blocked" ? selectedCase.blocked_reason : "",
                        blocked_until: nextStatus === "blocked" ? selectedCase.blocked_until : null,
                        escalated_reason:
                          nextStatus === "escalated" ? selectedCase.escalated_reason : "",
                        escalated_level:
                          nextStatus === "escalated" ? selectedCase.escalated_level ?? 1 : null,
                        escalated_to:
                          nextStatus === "escalated" ? selectedCase.escalated_to ?? "" : "",
                      });
                    }}
                    disabled={!canEdit}
                  >
                    {statusOptions.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Asignado a</p>
                  <select
                    className="input-base mt-2"
                    value={selectedCase.assignee ?? ""}
                    onChange={(event) =>
                      setSelectedCase({ ...selectedCase, assignee: event.target.value })
                    }
                    disabled={!canEdit}
                  >
                    <option value="">Sin asignar</option>
                    {assignableUsers.map((user) => (
                      <option key={user.id} value={user.email}>
                        {user.email}
                      </option>
                    ))}
                  </select>
                  {me?.email && (
                    <button
                      type="button"
                      className="btn-mini mt-2"
                      onClick={() =>
                        setSelectedCase({ ...selectedCase, assignee: me.email })
                      }
                      disabled={!canEdit}
                    >
                      Asignarme
                    </button>
                  )}
                </div>
              </div>

              {selectedCase.status === "blocked" && (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                      Motivo de bloqueo
                    </p>
                    <textarea
                      className="input-base mt-2 h-20"
                      value={selectedCase.blocked_reason ?? ""}
                      onChange={(event) =>
                        setSelectedCase({
                          ...selectedCase,
                          blocked_reason: event.target.value,
                        })
                      }
                      disabled={!canEdit}
                    />
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                      Revisión esperada
                    </p>
                    <input
                      className="input-base mt-2"
                      type="datetime-local"
                      value={toLocalInput(selectedCase.blocked_until)}
                      onChange={(event) =>
                        setSelectedCase({
                          ...selectedCase,
                          blocked_until: fromLocalInput(event.target.value),
                        })
                      }
                      disabled={!canEdit}
                    />
                  </div>
                </div>
              )}

              {selectedCase.status === "escalated" && (
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                      Motivo de escalamiento
                    </p>
                    <textarea
                      className="input-base mt-2 h-20"
                      value={selectedCase.escalated_reason ?? ""}
                      onChange={(event) =>
                        setSelectedCase({
                          ...selectedCase,
                          escalated_reason: event.target.value,
                        })
                      }
                      disabled={!canEdit}
                    />
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                      Nivel de escalamiento
                    </p>
                    <select
                      className="input-base mt-2"
                      value={String(selectedCase.escalated_level ?? 1)}
                      onChange={(event) =>
                        setSelectedCase({
                          ...selectedCase,
                          escalated_level: Number(event.target.value),
                        })
                      }
                      disabled={!canEdit}
                    >
                      <option value="1">Nivel 1</option>
                      <option value="2">Nivel 2</option>
                      <option value="3">Nivel 3</option>
                    </select>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-[0.3em] text-white/40">
                      Escalar a
                    </p>
                    <select
                      className="input-base mt-2"
                      value={selectedCase.escalated_to ?? ""}
                      onChange={(event) =>
                        setSelectedCase({
                          ...selectedCase,
                          escalated_to: event.target.value,
                        })
                      }
                      disabled={!canEdit}
                    >
                      <option value="">Sin asignar</option>
                      {assignableUsers.map((user) => (
                        <option key={user.id} value={user.email}>
                          {user.email}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">Timeline</p>
                <div className="timeline mt-4">
                  {timelineLoading ? (
                    <div className="skeleton h-16" />
                  ) : timeline.length === 0 ? (
                    <p className="text-sm text-[var(--muted)]">Sin eventos registrados.</p>
                  ) : (
                    timeline.map((item, idx) => {
                      const meta = item.meta ?? {};
                      const from = meta.from;
                      const to = meta.to;
                      const fromDue = meta.from_due;
                      const toDue = meta.to_due;
                      const note = meta.note;
                      return (
                      <div key={`${item.type}-${idx}`} className="card-box timeline-item">
                        <span className="timeline-dot" />
                        <div className="flex items-center justify-between text-xs text-white/50">
                          <span>
                            {item.type === "status"
                              ? "Cambio de estado"
                              : item.type === "note"
                              ? "Nota"
                              : item.type === "assignment"
                              ? "Asignación"
                              : item.type === "sla"
                              ? "SLA"
                              : "Creación"}
                          </span>
                          <span>{formatDate(item.created_at)}</span>
                        </div>
                        <p className="mt-2 text-sm text-white/80">{item.label}</p>
                        {item.actor && (
                          <p className="mt-1 text-xs text-[var(--muted)]">por {item.actor}</p>
                        )}
                        {item.type === "assignment" && (
                          <p className="mt-2 text-xs text-white/70">
                            {from || "Sin asignar"} → {to || "Sin asignar"}
                          </p>
                        )}
                        {item.type === "sla" && (
                          <div className="mt-2 text-xs text-white/70">
                            <p>
                              SLA: {from ?? "-"} → {to ?? "-"} horas
                            </p>
                            <p className="text-[var(--muted)]">
                              {fromDue ? `Antes: ${formatDate(fromDue)}` : "Antes: -"} ·{" "}
                              {toDue ? `Ahora: ${formatDate(toDue)}` : "Ahora: -"}
                            </p>
                          </div>
                        )}
                        {item.type === "note" && note && (
                          <p className="mt-2 text-xs text-white/70">
                            {note.slice(0, 200)}
                          </p>
                        )}
                      </div>
                    );
                    })
                  )}
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">SLA</p>
                  <div className="mt-2 text-xs text-white/60">
                    {formatRelative(selectedCase.due_date)}
                  </div>
                  {slaProgress(selectedCase) !== null && (
                    <div className="mt-2 h-2 w-full rounded-full bg-white/10">
                      <div
                        className="h-2 rounded-full bg-[var(--accent)]"
                        style={{ width: `${slaProgress(selectedCase)}%` }}
                      />
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {[24, 48, 72].map((hours) => (
                      <button
                        key={hours}
                        type="button"
                        className="btn-mini"
                        onClick={() => {
                          const due = new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
                          setSelectedCase({ ...selectedCase, due_date: due, sla_hours: hours });
                        }}
                        disabled={!canEdit}
                      >
                        {hours}h
                      </button>
                    ))}
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => {
                        const hours = selectedDefaultSla ?? defaultSlaHours(selectedCase.severity);
                        const due = new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
                        setSelectedCase({ ...selectedCase, due_date: due, sla_hours: hours });
                      }}
                      disabled={!canEdit}
                    >
                      Auto
                    </button>
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => {
                        const base = selectedCase.due_date
                          ? new Date(selectedCase.due_date).getTime()
                          : Date.now();
                        const due = new Date(base + 24 * 60 * 60 * 1000).toISOString();
                        setSelectedCase({ ...selectedCase, due_date: due });
                      }}
                      disabled={!canEdit}
                    >
                      +24h
                    </button>
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => {
                        const base = selectedCase.due_date
                          ? new Date(selectedCase.due_date).getTime()
                          : Date.now();
                        const due = new Date(base + 48 * 60 * 60 * 1000).toISOString();
                        setSelectedCase({ ...selectedCase, due_date: due });
                      }}
                      disabled={!canEdit}
                    >
                      +48h
                    </button>
                    <button
                      type="button"
                      className="btn-mini"
                      onClick={() => setSelectedCase({ ...selectedCase, due_date: null, sla_hours: null })}
                      disabled={!canEdit}
                    >
                      Quitar
                    </button>
                  </div>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Fecha límite</p>
                  <input
                    className="input-base mt-2"
                    type="datetime-local"
                    value={toLocalInput(selectedCase.due_date)}
                    onChange={(event) =>
                      setSelectedCase({
                        ...selectedCase,
                        due_date: fromLocalInput(event.target.value),
                      })
                    }
                    disabled={!canEdit}
                  />
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    {slaState(selectedCase.due_date).label} ·{" "}
                    {selectedCase.due_date ? formatDate(selectedCase.due_date) : "Sin fecha"}
                  </p>
                  <p className="mt-1 text-xs text-white/50">
                    SLA actual: {selectedCase.sla_hours ?? selectedDefaultSla ?? defaultSlaHours(selectedCase.severity)}h
                  </p>
                  <p className="mt-1 text-xs text-white/50">
                    Regla dominio: {datasetMap.get(selectedCase.dataset_id)?.domain ?? "default"}
                  </p>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Resumen</p>
                  <textarea
                    className="input-base mt-2 h-24"
                    value={selectedCase.summary ?? ""}
                    onChange={(event) =>
                      setSelectedCase({ ...selectedCase, summary: event.target.value })
                    }
                    disabled={!canEdit}
                  />
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-white/40">Recomendación</p>
                  <textarea
                    className="input-base mt-2 h-24"
                    value={selectedCase.recommendation ?? ""}
                    onChange={(event) =>
                      setSelectedCase({ ...selectedCase, recommendation: event.target.value })
                    }
                    disabled={!canEdit}
                  />
                </div>
              </div>

              <div className="flex justify-end">
                <button className="btn-primary" onClick={saveCase} disabled={!canEdit}>
                  Guardar cambios
                </button>
                {canEdit && selectedCase.status !== "resolved" && (
                  <button
                    className="btn-secondary ml-2"
                    onClick={() =>
                      setSelectedCase({ ...selectedCase, status: "resolved" })
                    }
                  >
                    Marcar resuelto
                  </button>
                )}
              </div>

              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-white/40">Notas</p>
                <div className="mt-4 grid gap-3">
                  {selectedCase.notes.length === 0 ? (
                    <p className="text-sm text-[var(--muted)]">Sin notas todavía.</p>
                  ) : (
                    selectedCase.notes.map((note) => (
                      <div key={note.id} className="card-box">
                        <div className="flex items-center justify-between text-xs text-white/50">
                          <span>{note.author}</span>
                          <span>{new Date(note.created_at).toLocaleString("es-AR")}</span>
                        </div>
                        <p className="mt-2 text-white/80">{note.note}</p>
                      </div>
                    ))
                  )}
                </div>
                <div className="mt-4 grid gap-3">
                  <textarea
                    className="input-base h-24"
                    placeholder="Agregar nota..."
                    value={noteText}
                    onChange={(event) => setNoteText(event.target.value)}
                    disabled={!canEdit}
                  />
                  <div className="flex justify-end">
                    <button className="btn-secondary" onClick={addNote} disabled={!canEdit}>
                      Añadir nota
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {pendingMove && (
        <div className="modal-backdrop" onClick={() => setPendingMove(null)}>
          <div
            className="modal-panel max-w-md space-y-4"
            onClick={(event) => event.stopPropagation()}
          >
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-white/40">Mover caso</p>
              <h3 className="mt-2 text-lg font-semibold">Confirmar cambio de estado</h3>
              <p className="mt-2 text-sm text-[var(--muted)]">
                {pendingMove.from} → {pendingMove.to}
              </p>
            </div>
            {pendingMove.to === "blocked" && (
              <div className="grid gap-3 text-sm">
                <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                  Motivo de bloqueo
                  <textarea
                    className="input-base mt-2 h-20"
                    value={moveReason}
                    onChange={(event) => setMoveReason(event.target.value)}
                    placeholder="Describe el bloqueo"
                  />
                </label>
                <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                  Revisión esperada (opcional)
                  <input
                    className="input-base mt-2"
                    type="datetime-local"
                    value={moveBlockedUntil}
                    onChange={(event) => setMoveBlockedUntil(event.target.value)}
                  />
                </label>
              </div>
            )}
            {pendingMove.to === "escalated" && (
              <div className="grid gap-3 text-sm">
                <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                  Motivo de escalamiento
                  <textarea
                    className="input-base mt-2 h-20"
                    value={moveReason}
                    onChange={(event) => setMoveReason(event.target.value)}
                    placeholder="Describe el escalamiento"
                  />
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                    Nivel
                    <select
                      className="input-base mt-2"
                      value={moveEscalatedLevel}
                      onChange={(event) => setMoveEscalatedLevel(event.target.value)}
                    >
                      <option value="1">Nivel 1</option>
                      <option value="2">Nivel 2</option>
                      <option value="3">Nivel 3</option>
                    </select>
                  </label>
                  <label className="text-xs uppercase tracking-[0.3em] text-white/40">
                    Escalar a
                    <select
                      className="input-base mt-2"
                      value={moveEscalatedTo}
                      onChange={(event) => setMoveEscalatedTo(event.target.value)}
                    >
                      <option value="">Sin asignar</option>
                      {assignableUsers.map((user) => (
                        <option key={user.id} value={user.email}>
                          {user.email}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button className="btn-secondary" onClick={() => setPendingMove(null)}>
                Cancelar
              </button>
              <button
                className="btn-primary"
                onClick={() => {
                  if (
                    pendingMove.to === "blocked" &&
                    moveReason.trim().length < 8
                  ) {
                    emitToast({
                      message: "Definí un motivo de bloqueo.",
                      kind: "info",
                    });
                    return;
                  }
                  if (
                    pendingMove.to === "escalated" &&
                    moveReason.trim().length < 8
                  ) {
                    emitToast({
                      message: "Definí un motivo de escalamiento.",
                      kind: "info",
                    });
                    return;
                  }
                  moveCaseStatus(pendingMove.id, pendingMove.to, {
                    status_reason: moveReason.trim() || null,
                    blocked_reason:
                      pendingMove.to === "blocked" ? moveReason.trim() || null : null,
                    blocked_until:
                      pendingMove.to === "blocked" && moveBlockedUntil
                        ? fromLocalInput(moveBlockedUntil)
                        : null,
                    escalated_reason:
                      pendingMove.to === "escalated" ? moveReason.trim() || null : null,
                    escalated_level:
                      pendingMove.to === "escalated"
                        ? Number(moveEscalatedLevel)
                        : null,
                    escalated_to:
                      pendingMove.to === "escalated" && moveEscalatedTo
                        ? moveEscalatedTo
                        : null,
                  });
                  setPendingMove(null);
                }}
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
