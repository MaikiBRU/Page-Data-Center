 "use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { clearToken } from "@/lib/auth";

type MeResponse = {
  email: string;
  is_admin: boolean;
  role?: string;
};

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/datasets", label: "Datasets" },
  { href: "/runs", label: "Corridas" },
  { href: "/cases", label: "Casos" },
  { href: "/recommendations", label: "Recomendaciones" },
];

export function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<MeResponse | null>(null);

  useEffect(() => {
    const loadMe = async () => {
      try {
        const data = await apiFetch<MeResponse>("/auth/me");
        setMe(data);
      } catch {
        setMe(null);
      }
    };
    loadMe();
  }, []);

  const handleLogout = () => {
    clearToken();
    router.push("/login");
  };

  return (
    <aside className="hidden lg:flex lg:w-64 lg:flex-col lg:gap-8 lg:border-r lg:border-white/10 lg:bg-[var(--panel-2)]/80 lg:px-6 lg:py-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Control Center</p>
        <h1 className="mt-3 text-2xl font-semibold">Data Quality</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Ecommerce + Logistica
        </p>
      </div>
      <nav className="flex flex-col gap-3 text-sm">
        {navItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-xl border px-4 py-3 transition ${
              pathname === item.href || pathname?.startsWith(`${item.href}/`)
                ? "border-[var(--accent)]/60 bg-[var(--accent)]/15 text-white shadow-[0_12px_30px_rgba(255,122,26,0.18)]"
                : "border-white/10 bg-white/5 text-white/80 hover:border-[var(--accent)]/60 hover:text-white"
            }`}
          >
            {item.label}
          </Link>
        ))}
        {me?.is_admin && (
          <Link
            href="/users"
            className={`rounded-xl border px-4 py-3 transition ${
              pathname === "/users" || pathname?.startsWith("/users/")
                ? "border-[var(--accent)]/60 bg-[var(--accent)]/15 text-white shadow-[0_12px_30px_rgba(255,122,26,0.18)]"
                : "border-white/10 bg-white/5 text-white/80 hover:border-[var(--accent)]/60 hover:text-white"
            }`}
          >
            Usuarios
          </Link>
        )}
      </nav>
      <div className="mt-auto grid gap-3 rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-white/70">
        <div>
          Sistema interno para monitorear calidad, anomalías y acciones recomendadas.
        </div>
        {me && (
          <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-white/70">
            <p className="text-white/50">Sesión</p>
            <p className="truncate">{me.email}</p>
            <p className="text-[var(--accent-2)]">
              {me.is_admin ? "Administrador" : me.role === "analyst" ? "Analista" : "Viewer"}
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={handleLogout}
          className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-[11px] font-semibold text-white/80 transition hover:border-white/30"
        >
          Cerrar sesión
        </button>
      </div>
    </aside>
  );
}
