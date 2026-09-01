import { Suspense } from "react";

import DemoClient from "./DemoClient";

export const metadata = {
  title: "Probar la demo",
  description:
    "Sandbox temporal para probar la plataforma de calidad de datos sin registro.",
};

export default function DemoPage() {
  return (
    // DemoClient reads the query string via useSearchParams, which needs a
    // boundary so the rest of the page can still be prerendered.
    <Suspense fallback={<div className="panel mx-auto max-w-lg">Cargando demo...</div>}>
      <DemoClient />
    </Suspense>
  );
}
