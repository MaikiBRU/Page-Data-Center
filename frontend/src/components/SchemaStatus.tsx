"use client";

export type SchemaTypeMismatch = {
  column: string;
  expected: string;
  checked: number;
  invalid: number;
  invalid_ratio: number;
  samples: string[];
};

export type SchemaReport = {
  status: "compatible" | "warning" | "incompatible";
  domain: string;
  columns_present: string[];
  required_expected: string[];
  missing_required: string[];
  missing_optional: string[];
  unexpected_columns: string[];
  type_mismatches: SchemaTypeMismatch[];
  required_coverage: number;
  reasons: string[];
};

const TONE = {
  compatible: {
    label: "Esquema compatible",
    box: "border-[var(--success)]/40 bg-[var(--success)]/10",
    text: "text-[var(--success)]",
  },
  warning: {
    label: "Esquema con advertencias",
    box: "border-[var(--warning)]/40 bg-[var(--warning)]/10",
    text: "text-[var(--warning)]",
  },
  incompatible: {
    label: "Esquema incompatible",
    box: "border-[var(--danger)]/45 bg-[var(--danger)]/10",
    text: "text-[var(--danger)]",
  },
} as const;

function ColumnList({ title, columns }: { title: string; columns: string[] }) {
  if (columns.length === 0) return null;
  return (
    <div>
      <p className="text-white/50">{title}</p>
      <p className="mt-1 font-mono text-[11px] text-white/75">{columns.join(", ")}</p>
    </div>
  );
}

/**
 * Whether the file matches the columns the selected domain expects.
 *
 * Answers a question the quality score cannot: a CSV from another domain used
 * to be scored 0%, which reads as "your data is terrible" when the truth is
 * "this was never this kind of data".
 */
export function SchemaStatus({
  report,
  compact = false,
}: {
  report: SchemaReport;
  compact?: boolean;
}) {
  const tone = TONE[report.status] ?? TONE.warning;
  const presentRequired =
    report.required_expected.length - report.missing_required.length;

  return (
    <div className={`rounded-2xl border p-4 text-xs ${tone.box}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={`text-sm font-semibold ${tone.text}`}>{tone.label}</span>
        <span className="text-white/50">
          {presentRequired} de {report.required_expected.length} columnas requeridas
          {report.required_expected.length > 0
            ? ` (${Math.round(report.required_coverage * 100)}%)`
            : ""}
        </span>
      </div>

      {report.status === "incompatible" && (
        <p className="mt-2 text-white/75">
          No se ejecutaron las reglas de calidad: el archivo no corresponde al dominio{" "}
          <span className="font-mono">{report.domain}</span>. No hay score de calidad
          porque no se midió nada.
        </p>
      )}

      {report.reasons.length > 0 && report.status !== "compatible" && (
        <ul className="mt-2 grid gap-1 text-white/70">
          {report.reasons.map((reason) => (
            <li key={reason}>· {reason}</li>
          ))}
        </ul>
      )}

      {!compact && report.status !== "compatible" && (
        <div className="mt-3 grid gap-2 border-t border-white/10 pt-3">
          <ColumnList title="Columnas requeridas ausentes" columns={report.missing_required} />
          <ColumnList title="Columnas no reconocidas" columns={report.unexpected_columns} />
          {report.type_mismatches.length > 0 && (
            <div>
              <p className="text-white/50">Tipos incompatibles</p>
              <ul className="mt-1 grid gap-0.5 text-[11px] text-white/75">
                {report.type_mismatches.map((mismatch) => (
                  <li key={mismatch.column}>
                    <span className="font-mono">{mismatch.column}</span> deberia ser{" "}
                    {mismatch.expected} · {mismatch.invalid} de {mismatch.checked} valores no lo
                    son
                    {mismatch.samples.length > 0 && (
                      <span className="text-white/45"> (ej.: {mismatch.samples.join(", ")})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
