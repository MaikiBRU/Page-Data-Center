"use client";

import { useMemo, useState } from "react";
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
  const [dismissed, setDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(`dq_onboarding_dismiss_${stepKey}`) === "1";
  });
  const [done] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem("dq_onboarding_done") === "1";
  });

  const current = useMemo(() => (flow ? resolveCurrent(flow) : "none"), [flow]);
  if (!flow || current !== stepKey || dismissed || done) return null;

  const stepIndex = order.indexOf(stepKey);

  return (
    <section className="panel coach-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">
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
          onClick={() => {
            if (typeof window !== "undefined") {
              window.localStorage.setItem(`dq_onboarding_dismiss_${stepKey}`, "1");
            }
            setDismissed(true);
          }}
        >
          Ocultar este paso
        </button>
      </div>
    </section>
  );
}
