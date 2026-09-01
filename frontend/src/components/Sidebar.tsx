"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { markDemoMode, useIsDemoMode } from "@/lib/demo";

type MeResponse = {
  email: string;
  is_admin: boolean;
  role?: string;
  is_demo?: boolean;
};

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/datasets", label: "Datasets" },
  { href: "/runs", label: "Corridas" },
  { href: "/cases", label: "Casos" },
  { href: "/recommendations", label: "Recomendaciones" },
];

// Administration is not reachable from a sandbox: the API refuses demo tokens
// on /users, so the entry point is hidden there too.
const USERS_ITEM = { href: "/users", label: "Usuarios" };

export function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<MeResponse | null>(null);

  useEffect(() => {
    // Without this guard the sidebar fired /auth/me on every render, including
    // for anonymous visitors. The 401 that came back triggered the global
    // "session expired" redirect, which is how somebody arriving from the
    // portfolio was greeted with an error for a session they never had.
    if (!getToken()) {
      return;
    }
    let cancelled = false;
    apiFetch<MeResponse>("/auth/me")
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch(() => {
        if (!cancelled) setMe(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  // Never read localStorage during render: see useIsDemoMode.
  const demoFlag = useIsDemoMode();
  const demo = me?.is_demo ?? demoFlag;

  const handleLogout = () => {
    clearToken();
    if (demo) {
      markDemoMode(false);
      router.push("/demo");
      return;
    }
    router.push("/login");
  };

  const isActive = (href: string) =>
    pathname === href || Boolean(pathname?.startsWith(`${href}/`));

  const linkClass = (href: string) => {
    const activeRoute = isActive(href);
    return `rounded-xl border px-4 py-3 transition ${
      activeRoute
        ? "border-[var(--accent)]/60 bg-[var(--accent)]/15 text-white shadow-[0_12px_30px_rgba(255,122,26,0.18)]"
        : "border-white/10 bg-white/5 text-white/80 hover:border-[var(--accent)]/60 hover:text-white"
    }`;
  };

  const sections = me?.is_admin && !demo ? [...navItems, USERS_ITEM] : navItems;

  return (
    <>
      {/* Below lg the sidebar is hidden, which used to leave Dashboard,
          Corridas, Casos and Recomendaciones with no reachable link. Same
          destinations, same active styling, in a strip that scrolls sideways
          when the labels do not fit. */}
      <nav
        aria-label="Secciones"
        className="scroll-soft sticky top-0 z-30 flex gap-2 overflow-x-auto rounded-xl border border-white/10 bg-[var(--bg-1)]/95 p-2 backdrop-blur lg:hidden"
      >
        {sections.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive(item.href) ? "page" : undefined}
            className={`shrink-0 rounded-lg border px-3 py-2 text-xs transition ${
              isActive(item.href)
                ? "border-[var(--accent)]/60 bg-[var(--accent)]/15 text-white"
                : "border-white/10 bg-white/5 text-white/70"
            }`}
          >
            {item.label}
          </Link>
        ))}
        <button
          type="button"
          onClick={handleLogout}
          className="ml-auto shrink-0 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-xs font-semibold text-white/80"
        >
          {demo ? "Salir" : "Cerrar sesion"}
        </button>
      </nav>

      <aside className="hidden lg:flex lg:w-64 lg:flex-col lg:gap-8 lg:border-r lg:border-white/10 lg:bg-[var(--panel-2)]/80 lg:px-6 lg:py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Data Center</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">Calidad de datos</p>
      </div>
      <nav className="flex flex-col gap-3 text-sm">
        {sections.map((item) => (
          <Link key={item.href} href={item.href} className={linkClass(item.href)}>
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="mt-auto grid gap-3 rounded-xl border border-white/10 bg-black/40 p-4 text-xs text-white/70">
        <div className="text-white/70">
          Monitoreo de calidad, anomalias y acciones recomendadas sobre datos de
          ecommerce y logistica.
        </div>
        {me && (
          <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[11px] text-white/70">
            <p className="text-white/50">Sesion</p>
            <p className="truncate">{demo ? "Visitante" : me.email}</p>
            <p className="text-[var(--accent-2)]">
              {demo
                ? "Demo temporal"
                : me.is_admin
                ? "Administrador"
                : me.role === "analyst"
                ? "Analista"
                : "Viewer"}
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={handleLogout}
          className="rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-[11px] font-semibold text-white/80 transition hover:border-white/30"
        >
          {demo ? "Salir de la demo" : "Cerrar sesion"}
        </button>
      </div>
      </aside>
    </>
  );
}
