"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { entryPath } from "@/lib/demo";
import { emitToast } from "@/lib/toast";
import { can } from "@/lib/permissions";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { formatDate } from "@/lib/format";

interface Dataset {
  id: number;
  name: string;
  domain: string;
  source_type: string;
  created_at: string;
  last_run_at?: string | null;
}

export default function DatasetsPage() {
  const router = useRouter();
  const initialSearch =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("q") ?? ""
      : "";
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [me, setMe] = useState<{ is_admin: boolean; role?: string } | null>(null);
  const [search, setSearch] = useState(initialSearch);
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("ecommerce-logistica");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const flow = useFlowData();
  const firstDatasetId = datasets[0]?.id;

  // A failed request used to fall through to the empty state, which told
  // the visitor they had no datasets when the API was simply unreachable.
  const fetchDatasets = useCallback(() => {
    apiFetch<Dataset[]>("/datasets")
      .then((data) => {
        setDatasets(data);
        setLoadError(null);
      })
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, []);

  /** Retry / refresh: unlike the first load, this one shows skeletons again. */
  const reloadDatasets = useCallback(() => {
    setLoading(true);
    fetchDatasets();
  }, [fetchDatasets]);

  useEffect(() => {
    if (!getToken()) {
      router.push(entryPath());
      return;
    }
    fetchDatasets();
    apiFetch<{ is_admin: boolean; role?: string }>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, [router, fetchDatasets]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set("q", search.trim());
    const qs = params.toString();
    router.replace(qs ? `/datasets?${qs}` : "/datasets");
  }, [search, router]);

  const canEdit = can(me, "dataset:create");
  const filtered = datasets.filter((dataset) =>
    dataset.name.toLowerCase().includes(search.trim().toLowerCase())
  );

  const createDataset = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canEdit) {
      emitToast({ message: "No tenés permisos para crear datasets.", kind: "error" });
      return;
    }
    try {
      await apiFetch<Dataset>("/datasets", {
        method: "POST",
        body: JSON.stringify({ name, domain }),
      });
      setName("");
      emitToast({ message: "Dataset creado.", kind: "success" });
      reloadDatasets();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/55">Datasets</p>
        <h2 className="mt-2 text-3xl font-semibold">Fuentes monitoreadas</h2>
        <p className="mt-2 max-w-2xl text-sm text-white/70">
          Cada dataset es un origen con su dominio de reglas. Entra a uno para subir
          un CSV, correr calidad y revisar los hallazgos.
        </p>
      </div>

      <OnboardingCoach
        flow={flow}
        stepKey="datasets"
        title="Creá el primer dataset"
        description="Definí nombre y dominio para activar el pipeline de calidad."
        actionLabel="Crear dataset"
        href="#dataset-create"
      />
      {firstDatasetId && (
        <OnboardingCoach
          flow={flow}
          stepKey="runs"
          title="Ejecutá la primera corrida"
          description="Entrá al dataset y corré calidad para generar hallazgos y casos."
          actionLabel="Ir al dataset"
          href={`/datasets/${firstDatasetId}`}
        />
      )}

      <section className="panel">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/55">Listado</p>
            <h3 className="mt-2 text-xl font-semibold">Buscar datasets</h3>
          </div>
          <input
            className="input-base w-full md:w-64"
            type="search"
            aria-label="Buscar datasets por nombre"
            placeholder="Buscar por nombre"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="grid gap-3">
          {loading ? (
            Array.from({ length: 3 }).map((_, index) => (
              <div key={`ds-row-${index}`} className="skeleton h-16" />
            ))
          ) : loadError ? (
            <ErrorState message={loadError} onRetry={reloadDatasets} />
          ) : filtered.length === 0 ? (
            <EmptyState
              title={
                datasets.length === 0
                  ? "Todavía no hay datasets."
                  : "No hay coincidencias con tu búsqueda."
              }
              description={
                datasets.length === 0
                  ? "Creá el primero para iniciar el flujo de calidad."
                  : "Probá con otro nombre o limpiá el filtro."
              }
              actions={
                datasets.length === 0
                  ? [
                      {
                        label: "Crear primer dataset",
                        onClick: () => {
                          const input =
                            document.querySelector<HTMLInputElement>("#dataset-name");
                          input?.scrollIntoView({ behavior: "smooth", block: "center" });
                          input?.focus();
                        },
                        variant: "primary",
                      },
                      {
                        label: "Ver guía rápida",
                        onClick: () => router.push("/dashboard"),
                        variant: "secondary",
                      },
                    ]
                  : [
                      {
                        label: "Limpiar filtros",
                        onClick: () => setSearch(""),
                        variant: "secondary",
                      },
                    ]
              }
            />
          ) : (
            filtered.map((dataset) => (
              <div key={dataset.id} className="card-row">
                <div>
                  <p className="text-white">{dataset.name}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {dataset.domain} · {dataset.source_type}
                  </p>
                </div>
                {/* This used to print the raw ISO timestamp the API returns. */}
                <div className="text-xs text-white/70">
                  {dataset.last_run_at ? (
                    <>
                      <span className="badge border-[var(--success)]/40 bg-[var(--success)]/10 text-[var(--success)]">
                        Analizado
                      </span>{" "}
                      <span className="whitespace-nowrap">
                        {formatDate(dataset.last_run_at)}
                      </span>
                    </>
                  ) : (
                    <span className="badge">Sin corridas</span>
                  )}
                </div>
                <Link
                  className="btn-secondary"
                  href={`/datasets/${dataset.id}`}
                  aria-label={`Gestionar el dataset ${dataset.name}`}
                >
                  Gestionar
                </Link>
              </div>
            ))
          )}
        </div>
      </section>

      <form
        id="dataset-create"
        onSubmit={createDataset}
        className="panel"
      >
        <p className="text-xs uppercase tracking-[0.3em] text-white/55">Nuevo dataset</p>
        <div className="mt-4 grid gap-4 md:grid-cols-[2fr_1fr_auto] md:items-end">
          <label className="grid gap-1.5 text-xs text-white/70">
            Nombre
            <input
              id="dataset-name"
              className="input-base"
              placeholder="Pedidos septiembre"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              disabled={!canEdit}
            />
          </label>
          <label className="grid gap-1.5 text-xs text-white/70">
            Dominio de reglas
            <select
              className="input-base"
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              disabled={!canEdit}
            >
              <option value="ecommerce-logistica">Ecommerce + Logística</option>
              <option value="ecommerce">Ecommerce</option>
              <option value="logistica">Logística</option>
            </select>
          </label>
          <button className="btn-primary" type="submit" disabled={!canEdit}>
            Crear dataset
          </button>
        </div>
        {me && !canEdit && (
          <p className="mt-3 text-xs text-[var(--muted)]">
            Solo administradores o analistas pueden crear datasets.
          </p>
        )}
      </form>
    </div>
  );
}
