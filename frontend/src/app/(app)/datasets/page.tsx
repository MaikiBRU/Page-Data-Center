"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { emitToast } from "@/lib/toast";
import { FlowSteps } from "@/components/FlowSteps";
import { OnboardingCoach } from "@/components/OnboardingCoach";
import { useFlowData } from "@/lib/flow";
import { EmptyState } from "@/components/EmptyState";

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
  const flow = useFlowData();
  const firstDatasetId = datasets[0]?.id;

  const loadDatasets = () => {
    setLoading(true);
    apiFetch<Dataset[]>("/datasets")
      .then(setDatasets)
      .catch(() => null)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!getToken()) {
      router.push("/login");
      return;
    }
    apiFetch<Dataset[]>("/datasets")
      .then(setDatasets)
      .catch(() => null)
      .finally(() => setLoading(false));
    apiFetch<{ is_admin: boolean; role?: string }>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, [router]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (search.trim()) params.set("q", search.trim());
    const qs = params.toString();
    router.replace(qs ? `/datasets?${qs}` : "/datasets");
  }, [search, router]);

  const filtered = datasets.filter((dataset) =>
    dataset.name.toLowerCase().includes(search.trim().toLowerCase())
  );

  const createDataset = async (event: React.FormEvent) => {
    event.preventDefault();
    const canEdit = me?.is_admin || me?.role === "analyst";
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
      loadDatasets();
    } catch (err) {
      emitToast({ message: (err as Error).message, kind: "error" });
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Datasets</p>
        <h2 className="mt-2 text-3xl font-semibold">Fuentes monitoreadas</h2>
      </div>

      <FlowSteps flow={flow} />

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
          description="Entrá al dataset y corré calidad para generar issues y casos."
          actionLabel="Ir al dataset"
          href={`/datasets/${firstDatasetId}`}
        />
      )}

      <form
        id="dataset-create"
        onSubmit={createDataset}
        className="panel grid gap-4 md:grid-cols-[2fr_1fr_auto]"
      >
        <input
          className="input-base"
          placeholder="Nombre del dataset"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          disabled={!(me?.is_admin || me?.role === "analyst")}
        />
        <select
          className="input-base"
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          disabled={!(me?.is_admin || me?.role === "analyst")}
        >
          <option value="ecommerce-logistica">Ecommerce + Logística</option>
          <option value="ecommerce">Ecommerce</option>
          <option value="logistica">Logística</option>
        </select>
        <button
          className="btn-primary"
          type="submit"
          disabled={!(me?.is_admin || me?.role === "analyst")}
        >
          Crear
        </button>
        {me && !(me.is_admin || me.role === "analyst") && (
          <p className="text-xs text-[var(--muted)] md:col-span-3">
            Solo administradores o analistas pueden crear datasets.
          </p>
        )}
      </form>

      <section className="panel">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-white/40">Listado</p>
            <h3 className="mt-2 text-lg font-semibold">Buscar datasets</h3>
          </div>
          <input
            className="input-base w-full md:w-64"
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
                          const input = document.querySelector<HTMLInputElement>(
                            "input[placeholder='Nombre del dataset']"
                          );
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
                <div className="text-xs text-white/50">
                  Última corrida: {dataset.last_run_at ?? "Pendiente"}
                </div>
                <Link className="btn-secondary" href={`/datasets/${dataset.id}`}>
                  Gestionar
                </Link>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
