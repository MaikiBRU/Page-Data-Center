"use client";

import { useEffect, useState } from "react";

type ToastItem = {
  id: string;
  message: string;
  kind: "success" | "error" | "info";
  durationMs: number;
};

function makeId() {
  return Math.random().toString(36).slice(2);
}

export function ToastHost() {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail as Omit<ToastItem, "id">;
      const id = makeId();
      const toast: ToastItem = {
        id,
        message: detail.message,
        kind: detail.kind ?? "info",
        durationMs: detail.durationMs ?? 3500,
      };
      setItems((prev) => [...prev, toast]);
      setTimeout(() => {
        setItems((prev) => prev.filter((item) => item.id !== id));
      }, toast.durationMs);
    };

    window.addEventListener("app-toast", handler);
    return () => window.removeEventListener("app-toast", handler);
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="pointer-events-none fixed left-1/2 top-4 z-50 flex w-[360px] -translate-x-1/2 flex-col gap-3">
      {items.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-[0_12px_30px_rgba(0,0,0,0.45)] ${
            toast.kind === "success"
              ? "border-[var(--success)]/50 bg-[var(--success)]/15 text-[var(--success)]"
              : toast.kind === "error"
              ? "border-[var(--danger)]/50 bg-[var(--danger)]/15 text-[var(--danger)]"
              : "border-white/15 bg-white/10 text-white/80"
          }`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
