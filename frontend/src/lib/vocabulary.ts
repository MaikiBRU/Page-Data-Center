/**
 * One vocabulary for the concepts the UI repeats on every screen.
 *
 * Before this module the same idea was written three ways: Cases printed the
 * raw API enums ("high", "in progress") into a Spanish interface,
 * Recommendations used its own Spanish set ("alta", "media", "baja") with a
 * different palette, and the dataset detail printed "Severidad: high". Reading
 * two screens felt like reading two products.
 *
 * Labels are Spanish; tones reuse the existing severity/status colours so
 * nothing changes appearance, only consistency.
 */

type Entry = { label: string; tone: string };

const NEUTRO = "border-white/15 bg-white/5 text-white/70";
const PELIGRO = "border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]";
const AVISO = "border-[var(--warning)]/50 bg-[var(--warning)]/10 text-[var(--warning)]";
const OK = "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]";
const ACENTO = "border-[var(--accent)]/40 bg-[var(--accent)]/10 text-[var(--accent-2)]";

/** Accepts both the API enum ("high") and the Spanish alias ("alta"). */
const SEVERIDADES: Record<string, Entry> = {
  high: { label: "Alta", tone: PELIGRO },
  alta: { label: "Alta", tone: PELIGRO },
  medium: { label: "Media", tone: AVISO },
  media: { label: "Media", tone: AVISO },
  low: { label: "Baja", tone: NEUTRO },
  baja: { label: "Baja", tone: NEUTRO },
};

const ESTADOS_CASO: Record<string, Entry> = {
  backlog: { label: "Backlog", tone: NEUTRO },
  open: { label: "Abierto", tone: ACENTO },
  in_progress: { label: "En curso", tone: ACENTO },
  blocked: { label: "Bloqueado", tone: AVISO },
  escalated: { label: "Escalado", tone: PELIGRO },
  resolved: { label: "Resuelto", tone: OK },
};

function buscar(tabla: Record<string, Entry>, clave?: string | null): Entry {
  if (!clave) return { label: "-", tone: NEUTRO };
  return tabla[clave] ?? { label: clave.replace(/_/g, " "), tone: NEUTRO };
}

export const severityLabel = (value?: string | null) => buscar(SEVERIDADES, value).label;
export const severityTone = (value?: string | null) => buscar(SEVERIDADES, value).tone;
export const caseStatusLabel = (value?: string | null) => buscar(ESTADOS_CASO, value).label;
export const caseStatusTone = (value?: string | null) => buscar(ESTADOS_CASO, value).tone;

/**
 * Low severity is deliberately neutral rather than green: a low-severity
 * finding is still a finding, and painting it with the success colour read as
 * "this one is fine".
 */
export const SEVERITY_ORDER = ["high", "medium", "low"] as const;
export const CASE_STATUS_ORDER = [
  "backlog",
  "open",
  "in_progress",
  "blocked",
  "escalated",
  "resolved",
] as const;
