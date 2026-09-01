import type { NextConfig } from "next";

/**
 * Guard against shipping a bundle that points at a developer's machine.
 *
 * `NEXT_PUBLIC_API_URL` is substituted into the client bundle at build time,
 * so a wrong value cannot be corrected later by a runtime setting: not by
 * Cloudflare's `vars`, not by an environment variable on the Worker. It also
 * fails silently -- the build succeeds, the deploy succeeds, and every visitor
 * gets "No se pudo contactar el servidor" because their browser is trying to
 * reach localhost.
 *
 * Next.js reads `.env.local` during production builds too, and `.env.local`
 * normally holds a developer's local API. So the default path -- running the
 * deploy command on a development machine -- is exactly the path that produces
 * a broken bundle.
 *
 * This turns that silent failure into a build error. It only applies to
 * production builds: `next dev` and the test suite are untouched.
 */
function assertProductionApiUrl(): void {
  // NEXT_PUBLIC_ALLOW_LOCAL_API=1 is the deliberate escape hatch for building
  // a production bundle aimed at a local backend (useful when testing the
  // optimised build before deploying).
  if (process.env.NEXT_PUBLIC_ALLOW_LOCAL_API === "1") return;

  const url = process.env.NEXT_PUBLIC_API_URL;

  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL no esta definida.\n\n" +
        "Se hornea dentro del bundle del cliente durante el build, asi que no " +
        "se puede corregir despues desde Cloudflare ni desde el entorno del " +
        "Worker. Sin ella el frontend publicado llamaria a http://localhost:8000.\n\n" +
        "Exportala en la shell que corre el build:\n" +
        '  $env:NEXT_PUBLIC_API_URL = "https://api-datacenter.aaronbrumat.com.ar"\n\n' +
        "Para un build de produccion apuntado a un backend local, usa " +
        "NEXT_PUBLIC_ALLOW_LOCAL_API=1.",
    );
  }

  const esLocal = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:|\/|$)/i.test(url);
  if (esLocal) {
    throw new Error(
      `NEXT_PUBLIC_API_URL apunta a una direccion local (${url}).\n\n` +
        "Ese valor quedaria compilado dentro del bundle publicado y el sitio " +
        "seria inutilizable para cualquier visitante. Suele venir de " +
        "frontend/.env.local, que Next.js tambien lee en builds de produccion " +
        "y que gana sobre .env.production.\n\n" +
        "Exporta la URL publica en la shell que corre el build:\n" +
        '  $env:NEXT_PUBLIC_API_URL = "https://api-datacenter.aaronbrumat.com.ar"\n\n' +
        "Si el build local contra ese backend es intencional, usa " +
        "NEXT_PUBLIC_ALLOW_LOCAL_API=1.",
    );
  }

  if (!/^https:\/\//i.test(url)) {
    throw new Error(
      `NEXT_PUBLIC_API_URL debe usar https en produccion (recibido: ${url}).\n` +
        "El sitio se sirve por https y el navegador bloquearia las llamadas a " +
        "un origen http por contenido mixto.",
    );
  }
}

// Solo durante `next build`.
//
// `next start` tambien carga este archivo con NODE_ENV=production, y hacerlo
// fallar ahi impedia arrancar un build ya compilado: para entonces el valor ya
// esta horneado, asi que revisarlo de nuevo no protege nada y solo rompe el
// arranque.
//
// NEXT_PHASE seria lo natural, pero en Next 16 llega undefined cuando se carga
// la configuracion (comprobado). El subcomando de la CLI si esta disponible.
const esBuild = process.argv.includes("build");
if (esBuild) {
  assertProductionApiUrl();
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
