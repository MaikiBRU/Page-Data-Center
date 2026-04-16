"use client";

import Link from "next/link";

type OnboardingStep = {
  title: string;
  description: string;
  ctaLabel: string;
  href: string;
};

type OnboardingModalProps = {
  open: boolean;
  steps: OnboardingStep[];
  onClose: () => void;
  onDone: () => void;
};

export function OnboardingModal({ open, steps, onClose, onDone }: OnboardingModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal-panel w-full max-w-3xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Guía rápida</p>
            <h3 className="mt-2 text-2xl font-semibold">Primeros pasos</h3>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Seguí este flujo para construir valor en minutos.
            </p>
          </div>
          <button className="btn-secondary" onClick={onClose}>
            Cerrar
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {steps.map((step, index) => (
            <div
              key={step.title}
              className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="badge">Paso {index + 1}</span>
                <span className="text-xs text-white/50">{step.title}</span>
              </div>
              <p className="mt-3 text-white/80">{step.description}</p>
              <Link
                href={step.href}
                className="btn-primary mt-4 inline-flex"
                onClick={onClose}
              >
                {step.ctaLabel}
              </Link>
            </div>
          ))}
        </div>

        <div className="flex justify-end">
          <button className="btn-primary" onClick={onDone}>
            Listo, entendí
          </button>
        </div>
      </div>
    </div>
  );
}
