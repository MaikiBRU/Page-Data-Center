"use client";

import { useCallback, useMemo, useSyncExternalStore } from "react";
import Link from "next/link";

import { FlowData } from "@/lib/flow";

type CoachProps = {
  flow: FlowData | null;
  stepKey: "datasets" | "runs" | "cases" | "recs";
  title: string;
  description: string;
  actionLabel: string;
  href: string;
  secondaryLabel?: string;
  secondaryHref?: string;
};

const order: Array<CoachProps["stepKey"]> = ["datasets", "runs", "cases", "recs"];

const resolveCurrent = (flow: FlowData) => {
  if (flow.datasets === 0) return "datasets";
  if (flow.runs === 0) return "runs";
  if (flow.cases === 0) return "cases";
  if (flow.recs === 0) return "recs";
  return "done";
};


/**
 * localStorage has no change event for the tab that wrote it, so the two
 * onboarding flags get a tiny store of their own: a cached snapshot (required,
 * useSyncExternalStore compares by identity) plus a manual notify on write.
 */
const oyentes = new Set<() => void>();
const cache = new Map<string, boolean>();

function subscribeToFlags(onChange: () => void) {
  oyentes.add(onChange);
  return () => {
    oyentes.delete(onChange);
  };
}

function leerBandera(clave: string): boolean {
  if (typeof window === "undefined") return false;
  if (!cache.has(clave)) {
    cache.set(clave, window.localStorage.getItem(clave) === "1");
  }
  return cache.get(clave)!;
}

function escribirBandera(clave: string, valor: boolean) {
  window.localStorage.setItem(clave, valor ? "1" : "0");
  cache.set(clave, valor);
  oyentes.forEach((oyente) => oyente());
}

export function OnboardingCoach({
  flow,
  stepKey,
  title,
  description,
  actionLabel,
  href,
  secondaryHref,
  secondaryLabel,
}: CoachProps) {
  // Both flags live in localStorage, which the server cannot see. Reading them
  // during render made the first client paint disagree with the server HTML,
  // so they are subscribed to instead, with a server snapshot of "not hidden".
  const dismissed = useSyncExternalStore(
    subscribeToFlags,
    useCallback(() => leerBandera(`dq_onboarding_dismiss_${stepKey}`), [stepKey]),
    () => false,
  );
  const done = useSyncExternalStore(
    subscribeToFlags,
    () => leerBandera("dq_onboarding_done"),
    () => false,
  );

  const current = useMemo(() => (flow ? resolveCurrent(flow) : "none"), [flow]);
  if (!flow || current !== stepKey || dismissed || done) return null;

  const stepIndex = order.indexOf(stepKey);

  return (
    <section className="panel coach-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">
            Onboarding · Paso {stepIndex + 1}
          </p>
          <h3 className="mt-2 text-xl font-semibold">{title}</h3>
          <p className="mt-2 text-sm text-[var(--muted)]">{description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {secondaryHref && secondaryLabel && (
            <Link className="btn-secondary" href={secondaryHref}>
              {secondaryLabel}
            </Link>
          )}
          <Link className="btn-primary" href={href}>
            {actionLabel}
          </Link>
        </div>
      </div>
      <div className="mt-4 flex justify-end">
        <button
          className="btn-mini"
          onClick={() => escribirBandera(`dq_onboarding_dismiss_${stepKey}`, true)}
        >
          Ocultar este paso
        </button>
      </div>
    </section>
  );
}
