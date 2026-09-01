import { useSyncExternalStore } from "react";

import { apiFetch, API_URL } from "@/lib/api";
import { setToken } from "@/lib/auth";

export type DemoLimits = {
  max_datasets: number;
  max_file_size_mb: number;
  max_storage_mb: number;
  max_runs: number;
  max_exports: number;
  session_ttl_minutes: number;
  idle_timeout_minutes: number;
};

export type DemoSessionState = {
  label: string;
  expires_at: string;
  seconds_remaining: number;
  idle_seconds_remaining: number;
  datasets_used: number;
  datasets_max: number;
  runs_used: number;
  runs_max: number;
  exports_used: number;
  exports_max: number;
  storage_bytes: number;
  storage_max_bytes: number;
  max_file_size_bytes: number;
};

export type DemoSession = {
  state: DemoSessionState;
  limits: DemoLimits;
};

export type DemoStartResponse = {
  access_token: string;
  token_type: string;
  session: DemoSession;
};

export type DemoConfig = {
  enabled: boolean;
  limits: DemoLimits;
};

const DEMO_FLAG_KEY = "dq_demo_mode";

/**
 * Whether this browser is running inside a demo sandbox.
 *
 * Purely a client-side hint used to pick the right chrome and the right
 * redirect target. It grants nothing: the server decides what a token may do
 * by re-reading the session on every request.
 */
export function isDemoMode(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(DEMO_FLAG_KEY) === "1";
  } catch {
    return false;
  }
}

export function markDemoMode(active: boolean) {
  if (typeof window === "undefined") return;
  try {
    if (active) {
      window.localStorage.setItem(DEMO_FLAG_KEY, "1");
    } else {
      window.localStorage.removeItem(DEMO_FLAG_KEY);
    }
  } catch {
    // Private browsing with storage disabled: the app still works, it just
    // cannot remember the mode across reloads.
  }
}

export async function fetchDemoConfig(): Promise<DemoConfig | null> {
  try {
    const response = await fetch(`${API_URL}/demo/config`);
    if (!response.ok) return null;
    return (await response.json()) as DemoConfig;
  } catch {
    return null;
  }
}

/** Provision a sandbox and store its token. Requires no credentials. */
export async function startDemoSession(): Promise<DemoStartResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/demo/session`, { method: "POST" });
  } catch {
    throw new Error(
      "No se pudo contactar el servidor. Puede estar iniciando: espera unos segundos y volve a intentar.",
    );
  }
  if (!response.ok) {
    let detail = "No se pudo iniciar la demo.";
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // keep the default message
    }
    throw new Error(detail);
  }
  const body = (await response.json()) as DemoStartResponse;
  setToken(body.access_token);
  markDemoMode(true);
  return body;
}

export async function readDemoSession(): Promise<DemoSession> {
  return apiFetch<DemoSession>("/demo/session");
}

export async function resetDemoSession(): Promise<DemoSession> {
  return apiFetch<DemoSession>("/demo/session/reset", { method: "POST" });
}

export async function endDemoSession(): Promise<void> {
  await apiFetch("/demo/session/end", { method: "POST" });
}

export function formatRemaining(seconds: number): string {
  if (seconds <= 0) return "expirada";
  const minutes = Math.floor(seconds / 60);
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours} h ${minutes % 60} min`;
  }
  if (minutes >= 1) return `${minutes} min`;
  return `${seconds} s`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Where to send a browser that has lost its session.
 *
 * A demo visitor has no credentials, so bouncing them to /login is a dead
 * end; they get the sandbox entry point instead.
 */
export function entryPath(): string {
  return isDemoMode() ? "/demo" : "/login";
}

function subscribeToDemoFlag(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/**
 * Read the demo flag from a component without breaking hydration.
 *
 * Calling isDemoMode() directly in a render body returns false on the server
 * and true in a demo session on the client, so the first client render did not
 * match the server HTML and React discarded the tree. useSyncExternalStore
 * takes a separate server snapshot, so hydration sees the same value the
 * server produced and the real value is picked up right after.
 */
export function useIsDemoMode(): boolean {
  return useSyncExternalStore(
    subscribeToDemoFlag,
    isDemoMode,
    () => false, // server snapshot: there is no localStorage during SSR
  );
}
