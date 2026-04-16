import Link from "next/link";

export function Topbar({
  title,
  onGuide,
  onExport,
}: {
  title: string;
  onGuide?: () => void;
  onExport?: () => void;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-white/40">Overview</p>
        <h2 className="mt-2 text-3xl font-semibold">{title}</h2>
      </div>
      <div className="flex w-full flex-wrap gap-3 sm:w-auto sm:justify-end">
        {onGuide && (
          <button className="btn-secondary w-full sm:w-auto" onClick={onGuide}>
            Guía rápida
          </button>
        )}
        <Link
          href="/datasets"
          className="btn-secondary w-full sm:w-auto"
        >
          Nuevo dataset
        </Link>
        {onExport && (
          <button className="btn-primary w-full sm:w-auto" onClick={onExport}>
            Exportar reporte
          </button>
        )}
      </div>
    </div>
  );
}
