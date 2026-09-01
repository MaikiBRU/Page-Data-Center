"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { clearToken } from "@/lib/auth";
import {
  DemoSession,
  endDemoSession,
  formatBytes,
  formatRemaining,
  isDemoMode,
  markDemoMode,
  readDemoSession,
  resetDemoSession,
} from "@/lib/demo";
import { emitToast } from "@/lib/toast";

/**
 * Slim status strip shown only inside a demo sandbox.
 *
 * Deliberately one row: the point of the demo is the product underneath, so
 * the chrome states the mode, the quota and the time left, and gets out of
 * the way. It re-reads the session every 30 seconds, which doubles as the
 * signal that keeps the idle timer alive while somebody is reading a chart.
 */
export function DemoBanner() {
  const router = useRouter();
  const [session, setSession] = useState<DemoSession | null>(null);
  const [active, setActive] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState<"reset" | "end" | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await readDemoSession();
      setSession(data);
      setSeconds(data.state.seconds_remaining);
    } catch {
      // A 401 is already handled by apiFetch, which redirects to /demo.
    }
  }, []);

  useEffect(() => {
    if (!isDemoMode()) return;
    setActive(true);
    load();
    const poll = window.setInterval(load, 30_000);
    return () => window.clearInterval(poll);
  }, [load]);

  useEffect(() => {
    if (!active) return;
    const tick = window.setInterval(() => {
      setSeconds((value) => (value > 0 ? value - 1 : 0));
    }, 1000);
    return () => window.clearInterval(tick);
  }, [active]);

  if (!active || !session) return null;

  const { state } = session;
  const lowTime = seconds > 0 && seconds < 5 * 60;

  const handleReset = async () => {
    if (!window.confirm("Se borra todo lo que creaste y se vuelve a cargar la demo. Continuar?"))
      return;
    setBusy("reset");
    try {
      const data = await resetDemoSession();
      setSession(data);
      setSeconds(data.state.seconds_remaining);
      emitToast({ message: "Sandbox reiniciada.", kind: "success" });
      router.refresh();
      window.location.reload();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    } finally {
      setBusy(null);
    }
  };

  const handleEnd = async () => {
    if (!window.confirm("Se elimina la sesion y todos sus datos. Continuar?")) return;
    setBusy("end");
    try {
      await endDemoSession();
    } catch {
      // Ending is best effort: the sandbox expires on its own regardless.
    } finally {
      clearToken();
      markDemoMode(false);
      setBusy(null);
      window.location.href = "/demo";
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--accent)]/35 bg-[var(--accent)]/10 px-4 py-2.5 text-xs">
      <span className="badge border-[var(--accent)]/50 bg-[var(--accent)]/15 text-[var(--accent-2)]">
        Demo
      </span>
      <span className="text-white/70">
        Sesion temporal <span className="text-white/45">({state.label})</span>
      </span>

      <span className="text-white/60">
        {state.datasets_used}/{state.datasets_max} datasets
      </span>
      <span className="text-white/60">
        {state.runs_used}/{state.runs_max} corridas
      </span>
      <span className="text-white/60">
        {formatBytes(state.storage_bytes)}/{formatBytes(state.storage_max_bytes)}
      </span>
      <span
        className={lowTime ? "font-semibold text-[var(--warning)]" : "text-white/60"}
        title={`Expira ${new Date(state.expires_at).toLocaleString("es-AR")}`}
      >
        Restan {formatRemaining(seconds)}
      </span>

      <div className="ml-auto flex gap-2">
        <button className="btn-mini" onClick={handleReset} disabled={busy !== null}>
          {busy === "reset" ? "Reiniciando..." : "Reiniciar"}
        </button>
        <button className="btn-mini" onClick={handleEnd} disabled={busy !== null}>
          {busy === "end" ? "Cerrando..." : "Terminar"}
        </button>
      </div>
    </div>
  );
}
