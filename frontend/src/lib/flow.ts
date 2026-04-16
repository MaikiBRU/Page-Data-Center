import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

type RecommendationSummary = {
  code: string;
};

type Dataset = {
  id: number;
  last_run_at?: string | null;
  quality_summary?: { recommendations?: RecommendationSummary[] } | null;
};

type CaseSummary = {
  total?: number;
};

export type FlowData = {
  datasets: number;
  runs: number;
  cases: number;
  recs: number;
};

export const loadFlowData = async (): Promise<FlowData> => {
  const [datasets, cases] = await Promise.all([
    apiFetch<Dataset[]>("/datasets"),
    apiFetch<CaseSummary>("/cases/summary"),
  ]);
  const datasetsCount = datasets.length;
  const runsCount = datasets.filter((dataset) => dataset.last_run_at).length;
  const recsCount = datasets.reduce(
    (acc, dataset) => acc + (dataset.quality_summary?.recommendations?.length ?? 0),
    0
  );
  return {
    datasets: datasetsCount,
    runs: runsCount,
    cases: cases.total ?? 0,
    recs: recsCount,
  };
};

export const useFlowData = () => {
  const [flow, setFlow] = useState<FlowData | null>(null);

  useEffect(() => {
    loadFlowData()
      .then(setFlow)
      .catch(() => setFlow(null));
  }, []);

  return flow;
};
