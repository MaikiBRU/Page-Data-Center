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
        <p className="text-xs uppercase tracking-[0.3em] text-white/55">Overview</p>
        <h2 className="mt-2 text-3xl font-semibold">{title}</h2>
      </div>
      {/* On a phone these were three stacked full-width blocks that pushed the
          first metric below the fold. The two secondary actions now share a
          row and only the primary one spans the width. */}
      <div className="grid w-full grid-cols-2 gap-3 sm:flex sm:w-auto sm:flex-wrap sm:justify-end">
        {onGuide && (
          <button className="btn-secondary" onClick={onGuide}>
            Guía rápida
          </button>
        )}
        <Link href="/datasets" className="btn-secondary text-center">
          Nuevo dataset
        </Link>
        {onExport && (
          <button className="btn-primary col-span-2 sm:col-span-1" onClick={onExport}>
            Exportar reporte
          </button>
        )}
      </div>
    </div>
  );
}
