"use client";

/**
 * Shown when a request failed, as opposed to succeeding with nothing in it.
 *
 * The list screens used to swallow load failures with `.catch(() => null)` and
 * fall through to their empty state, so an unreachable API told the visitor
 * "todavía no hay datasets" -- a confident lie about their data.
 */
export function ErrorState({
  title = "No se pudieron cargar los datos",
  message,
  onRetry,
  compact,
}: {
  title?: string;
  message?: string | null;
  onRetry?: () => void;
  compact?: boolean;
}) {
  return (
    <div
      role="alert"
      className={`rounded-2xl border border-[var(--danger)]/30 bg-[var(--danger)]/5 p-4 text-sm ${
        compact ? "" : "min-h-[120px]"
      }`}
    >
      <p className="font-medium text-white/90">{title}</p>
      {message && <p className="mt-2 text-xs text-white/70">{message}</p>}
      {onRetry && (
        <button className="btn-secondary mt-3" onClick={onRetry}>
          Reintentar
        </button>
      )}
    </div>
  );
}
