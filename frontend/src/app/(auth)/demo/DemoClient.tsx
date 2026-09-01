"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { emitToast } from "@/lib/toast";
import {
  DemoConfig,
  fetchDemoConfig,
  markDemoMode,
  startDemoSession,
} from "@/lib/demo";

const SAFE_NEXT = /^\/(dashboard|datasets|runs|cases|recommendations)(\/[\w-]*)?$/;

export default function DemoClient() {
  const router = useRouter();
  const [config, setConfig] = useState<DemoConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchParams = useSearchParams();

  // Derived from the URL rather than held in state, so the effect below has no
  // reason to call setState synchronously.
  const notice =
    searchParams.get("reason") === "expired"
      ? "Tu sesion anterior expiro. Podes iniciar una nueva ahora mismo."
      : null;

  useEffect(() => {
    // Arriving here always means the previous sandbox, if any, is gone.
    markDemoMode(false);
    let cancelled = false;
    fetchDemoConfig()
      .then((data) => {
        if (!cancelled) setConfig(data);
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const begin = async () => {
    setStarting(true);
    setError(null);
    try {
      await startDemoSession();
      const requested = searchParams.get("next");
      // Only follow an internal path we recognise; never an arbitrary URL.
      const destination =
        requested && SAFE_NEXT.test(requested) ? requested : "/dashboard";
      emitToast({ message: "Sandbox lista. Los datos ya estan analizados.", kind: "success" });
      router.replace(destination);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      emitToast({ message, kind: "error" });
      setStarting(false);
    }
  };

  const limits = config?.limits;
  const disabled = !loadingConfig && config?.enabled === false;

  return (
    // items-start so the action panel keeps its natural height instead of
    // stretching to match the taller description column.
    <div className="mx-auto grid w-full max-w-5xl items-start gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:gap-8">
      <div className="panel flex flex-col gap-7">
        <div>
          <span className="badge">Demo de portfolio</span>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">
            Data Center
          </h1>
          <p className="mt-4 text-base leading-relaxed text-white/75">
            Un pedido con precio negativo, una direccion vacia o un peso de 300 kg
            no rompen nada hasta que rompen la operacion. Data Center analiza
            datasets de ecommerce y logistica, encuentra esos registros y los
            convierte en incidencias con responsable y plazo.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { valor: "19", etiqueta: "reglas de validacion por dominio" },
            { valor: "z 3.5", etiqueta: "umbral robusto de outliers (MAD)" },
            { valor: "3", etiqueta: "perfiles de esquema soportados" },
          ].map((item) => (
            <div
              key={item.etiqueta}
              className="rounded-xl border border-white/10 bg-white/5 px-4 py-3"
            >
              <p className="text-xl font-semibold text-[var(--accent-2)]">{item.valor}</p>
              <p className="mt-1 text-xs leading-snug text-white/70">{item.etiqueta}</p>
            </div>
          ))}
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">
            Que vas a poder hacer
          </p>
          <ul className="mt-3 grid gap-2.5 text-sm text-white/75">
            {[
              "Explorar un dashboard con tres datasets ya analizados.",
              "Subir tu propio CSV y correr el motor de calidad.",
              "Revisar hallazgos, anomalias y recomendaciones.",
              "Gestionar casos con SLA, notas y timeline.",
              "Exportar reportes en JSON, CSV y HTML.",
            ].map((linea) => (
              <li key={linea} className="flex gap-2.5">
                <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--accent)]" />
                <span>{linea}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-white/55">Stack</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {[
              "Next.js",
              "React",
              "TypeScript",
              "Tailwind",
              "Recharts",
              "FastAPI",
              "SQLAlchemy",
              "PostgreSQL",
              "Alembic",
              "Docker",
            ].map((tech) => (
              <li
                key={tech}
                className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/70"
              >
                {tech}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* On a phone the description column pushed the button off the first
          screen, so the card that actually starts the demo comes first there
          and keeps its right-hand position on wide screens. */}
      <div className="panel order-first flex flex-col gap-6 lg:order-none">
        <div>
          {/* On a phone this panel comes first, so it has to say what the
              product is before it asks for a click. */}
          <p className="mb-3 text-xs uppercase tracking-[0.3em] text-white/55 lg:hidden">
            Data Center · Calidad de datos
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">Probar la demo</h2>
          <p className="mt-2 text-sm text-white/70">
            Sin registro, sin email y sin contrasena. Se crea un espacio de trabajo
            temporal solo para vos, con datos ya analizados.
          </p>
        </div>

        {notice && <p className="text-sm text-[var(--accent-2)]">{notice}</p>}
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

        {disabled ? (
          <p className="text-sm text-[var(--muted)]">
            La demo publica esta desactivada en este momento.
          </p>
        ) : (
          <button
            className="btn-primary w-full py-3 text-base"
            onClick={begin}
            disabled={starting || loadingConfig}
          >
            {starting ? "Preparando tu espacio..." : "Comenzar demo"}
          </button>
        )}

        <div className="grid gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-white/70">
          <p className="text-white/50">Limites de la sesion</p>
          {loadingConfig ? (
            <div className="skeleton h-24" />
          ) : limits ? (
            <ul className="grid gap-1.5">
              <li>Duracion: {limits.session_ttl_minutes} min</li>
              <li>Inactividad: {limits.idle_timeout_minutes} min</li>
              <li>Datasets: hasta {limits.max_datasets}</li>
              <li>
                Archivos: {limits.max_file_size_mb} MB por CSV, {limits.max_storage_mb} MB
                en total
              </li>
              <li>
                Analisis: {limits.max_runs} corridas · {limits.max_exports} exportaciones
              </li>
            </ul>
          ) : (
            <p className="text-[var(--muted)]">
              No se pudo contactar la API. Reintenta en unos segundos.
            </p>
          )}
        </div>

        <p className="text-xs text-[var(--muted)]">
          Sesion temporal y aislada. Todo lo que generes se elimina automaticamente
          al expirar, y podes borrarlo antes cuando quieras.
        </p>

        <div className="border-t border-white/10 pt-4 text-xs text-white/50">
          <Link className="hover:text-white" href="/login">
            Acceso para usuarios registrados
          </Link>
        </div>
      </div>
    </div>
  );
}
