"use client";

import Link from "next/link";

type Action = {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "mini";
};

type EmptyStateProps = {
  title: string;
  description?: string;
  actions?: Action[];
  compact?: boolean;
};

const actionClass = (variant?: Action["variant"]) => {
  if (variant === "primary") return "btn-primary";
  if (variant === "mini") return "btn-mini";
  return "btn-secondary";
};

export function EmptyState({ title, description, actions = [], compact }: EmptyStateProps) {
  return (
    <div
      className={`rounded-2xl border border-dashed border-white/12 bg-white/5 p-4 text-sm text-[var(--muted)] ${
        compact ? "" : "min-h-[120px]"
      }`}
    >
      <p className="text-white/80">{title}</p>
      {description && <p className="mt-2 text-xs text-[var(--muted)]">{description}</p>}
      {actions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((action) =>
            action.href ? (
              <Link key={action.label} className={actionClass(action.variant)} href={action.href}>
                {action.label}
              </Link>
            ) : (
              <button
                key={action.label}
                className={actionClass(action.variant)}
                onClick={action.onClick}
              >
                {action.label}
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
