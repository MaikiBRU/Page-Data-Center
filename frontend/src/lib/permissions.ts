/**
 * Client-side mirror of the backend PERMISSIONS table (app/api/deps.py).
 *
 * It exists only to decide what to grey out: the API enforces the real thing.
 * It is here because every screen was writing `is_admin || role === "analyst"`
 * by hand, which silently locked demo visitors out of uploading a CSV and
 * running quality -- the two actions the sandbox is built to show off.
 */

export type Principal = {
  is_admin?: boolean;
  role?: string;
} | null;

const TABLA: Record<string, readonly string[]> = {
  "dataset:create": ["admin", "analyst", "demo"],
  "dataset:upload": ["admin", "analyst", "demo"],
  "dataset:generate": ["admin", "analyst", "demo"],
  "dataset:run_quality": ["admin", "analyst", "demo"],
  // Schema and routing configuration stay outside the sandbox.
  "dataset:edit_domain": ["admin"],
  "dataset:edit_rules": ["admin"],
  "dataset:edit_assignment": ["admin"],
  "case:create": ["admin", "analyst", "demo"],
  "case:update": ["admin", "analyst", "demo"],
  "case:add_note": ["admin", "analyst", "demo"],
  "dashboard:demo": ["admin", "analyst"],
  "users:assignable": ["admin", "analyst"],
};

export function can(me: Principal, action: keyof typeof TABLA | string): boolean {
  if (!me) return false;
  if (me.is_admin) return true;
  return (TABLA[action] ?? []).includes(me.role ?? "");
}

/** True while the principal is still unknown, to avoid a flash of disabled UI. */
export function isDemoRole(me: Principal): boolean {
  return me?.role === "demo";
}
