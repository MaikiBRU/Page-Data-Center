"use client";

import Link from "next/link";

import { FlowData } from "@/lib/flow";

type FlowStepsProps = {
  flow: FlowData | null;
  onGuide?: () => void;
};

type Step = {
  key: "datasets" | "runs" | "cases" | "recs";
  title: string;
  description: string;
  href: string;
  cta: string;
};

const steps: Step[] = [
  {
    key: "datasets",
    title: "Dataset",
    description: "Definí el origen y el dominio para empezar.",
    href: "/datasets",
    cta: "Crear dataset",
  },
  {
    key: "runs",
    title: "Corrida",
    description: "Ejecutá calidad y anomalías sobre tus datos.",
    href: "/datasets",
    cta: "Correr calidad",
  },
  {
    key: "cases",
    title: "Casos",
    description: "Asigná responsables, SLA y estados.",
    href: "/cases",
    cta: "Gestionar casos",
  },
  {
    key: "recs",
    title: "Acciones",
    description: "Convertí recomendaciones en casos.",
    href: "/recommendations",
    cta: "Ver recomendaciones",
  },
];

const statusBadge = (status: "done" | "current" | "todo") => {
  if (status === "done") {
    return "border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]";
  }
  if (status === "current") {
    return "border-[var(--accent)]/50 bg-[var(--accent)]/15 text-[var(--accent-2)]";
  }
  return "border-white/15 bg-white/5 text-white/60";
};

const resolveCurrentIndex = (flow: FlowData) => {
  if (flow.datasets === 0) return 0;
  if (flow.runs === 0) return 1;
  if (flow.cases === 0) return 2;
  if (flow.recs === 0) return 3;
  return steps.length;
};

export function FlowSteps({ flow, onGuide }: FlowStepsProps) {
  if (!flow) {
    return (
      <section className="panel">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Flujo</p>
            <h3 className="mt-2 text-xl font-semibold">Cargando progreso...</h3>
          </div>
          {onGuide && (
            <button className="btn-secondary" onClick={onGuide}>
              Ver guía
            </button>
          )}
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          {steps.map((step) => (
            <div key={step.key} className="card-box">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton mt-3 h-4 w-32" />
              <div className="skeleton mt-3 h-3 w-full" />
            </div>
          ))}
        </div>
      </section>
    );
  }

  const currentIndex = resolveCurrentIndex(flow);
  const isComplete = currentIndex >= steps.length;

  return (
    <section className="panel">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/40">UX / Flujo</p>
          <h3 className="mt-2 text-xl font-semibold">Progreso operativo</h3>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Seguí este orden para maximizar impacto desde datos hasta acciones.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {onGuide && (
            <button className="btn-secondary" onClick={onGuide}>
              Ver guía
            </button>
          )}
          {currentIndex < steps.length && (
            <Link className="btn-primary" href={steps[currentIndex].href}>
              {steps[currentIndex].cta}
            </Link>
          )}
          {isComplete && (
            <span className="badge border-[var(--success)]/50 bg-[var(--success)]/10 text-[var(--success)]">
              Flujo completo
            </span>
          )}
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        {steps.map((step, index) => {
          const status =
            index < currentIndex
              ? "done"
              : index === currentIndex
              ? "current"
              : "todo";
          return (
            <div key={step.key} className="card-box">
              <div className="flex items-center justify-between">
                <span className={`badge ${statusBadge(status)}`}>
                  {status === "done" ? "OK" : status === "current" ? "Ahora" : "Pendiente"}
                </span>
                <span className="text-xs text-white/50">Paso {index + 1}</span>
              </div>
              <p className="mt-3 text-sm font-semibold">{step.title}</p>
              <p className="mt-2 text-xs text-[var(--muted)]">{step.description}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
