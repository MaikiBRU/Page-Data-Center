/**
 * Shared display formatters.
 *
 * Every screen was rolling its own copy of these, and the datasets listing had
 * none at all: it printed the raw ISO timestamp the API returns.
 */

const numbers = new Intl.NumberFormat("es-AR");

export function formatNumber(value?: number | null): string {
  return numbers.format(value ?? 0);
}

/** Short calendar date, e.g. "1 sept 2026". */
export function formatDate(value?: string | null, fallback = "Pendiente"): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-AR", { dateStyle: "medium" }).format(date);
}

/** Date with time, for anything where the hour matters. */
export function formatDateTime(value?: string | null, fallback = "-"): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-AR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
