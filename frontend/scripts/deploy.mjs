#!/usr/bin/env node
/**
 * Despliega el frontend a Cloudflare Workers.
 *
 * Existe por una razon concreta: OpenNext no compila bien en Windows. El build
 * termina sin errores y wrangler sube el Worker sin quejarse, pero el bundle
 * resultante falla en tiempo de ejecucion con
 *
 *   ChunkLoadError: Failed to load chunk server/chunks/ssr/...
 *
 * y el sitio entero devuelve 500. Ya paso una vez en produccion. El propio
 * OpenNext lo avisa ("OpenNext is not fully compatible with Windows"), pero es
 * un warning entre muchos y el fallo aparece despues del deploy, no durante.
 *
 * Asi que en Windows este script compila dentro de un contenedor Linux y sube
 * ese artefacto. En Linux y macOS compila directo. El comando es el mismo en
 * los tres casos:
 *
 *   npm run deploy
 */

import { execFileSync, execSync } from "node:child_process";
import { cpSync, mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = resolve(fileURLToPath(new URL("..", import.meta.url)));
const ES_WINDOWS = process.platform === "win32";

function paso(texto) {
  console.log(`\n\x1b[1m==> ${texto}\x1b[0m`);
}

/**
 * `npx` en Windows es un .cmd y necesita shell; `docker` es un ejecutable real
 * y NO debe usarlo: con shell:true el `sh -c "a && b"` pierde las comillas y el
 * `&&` lo interpreta cmd.exe en vez del contenedor.
 */
function correr(comando, args, opciones = {}) {
  const necesitaShell = ES_WINDOWS && comando !== "docker";
  execFileSync(comando, args, {
    stdio: "inherit",
    cwd: RAIZ,
    shell: necesitaShell,
    ...opciones,
  });
}

/** El bundle publicado tiene que hablar con la API de produccion. */
function verificarBundle(directorio) {
  const chunks = join(directorio, ".open-next", "assets", "_next", "static", "chunks");
  if (!existsSync(chunks)) {
    throw new Error(`No se genero el bundle en ${chunks}`);
  }
  const buscar = (patron) => {
    try {
      // grep devuelve 1 cuando no hay coincidencias; eso no es un fallo aca.
      execSync(`grep -rl "${patron}" "${chunks}"`, { stdio: "pipe" });
      return true;
    } catch {
      return false;
    }
  };
  if (!buscar("api-datacenter.aaronbrumat.com.ar")) {
    throw new Error("El bundle no contiene la URL de la API de produccion. No se despliega.");
  }
  if (buscar("localhost:8000")) {
    throw new Error("El bundle contiene una URL local. No se despliega.");
  }
  console.log("Bundle correcto: apunta a la API de produccion.");
}

function construirEnDocker() {
  paso("Windows detectado: compilando dentro de un contenedor Linux");

  try {
    execFileSync("docker", ["info"], { stdio: "ignore" });
  } catch {
    throw new Error(
      "Hace falta Docker para desplegar desde Windows, porque OpenNext produce " +
        "un bundle roto compilado nativamente aqui.\n\n" +
        "Alternativa sin Docker: Actions -> \"Deploy frontend (Cloudflare Workers)\" " +
        "-> Run workflow, que compila en Ubuntu.",
    );
  }

  const staging = mkdtempSync(join(tmpdir(), "dc-deploy-"));
  try {
    // Copia limpia: sin node_modules (binarios de Windows), sin artefactos
    // previos y sin .env.local, que apunta al backend de desarrollo y ganaria
    // sobre .env.production.
    cpSync(RAIZ, staging, {
      recursive: true,
      filter: (origen) => {
        const rel = origen.slice(RAIZ.length + 1);
        if (!rel) return true;
        const primero = rel.split(/[\\/]/)[0];
        return ![
          "node_modules",
          ".next",
          ".open-next",
          ".wrangler",
          ".env.local",
          ".env.production.local",
        ].includes(primero);
      },
    });

    correr(
      "docker",
      [
        "run", "--rm",
        "-v", `${staging}:/app`,
        "-w", "/app",
        "node:22",
        "sh", "-c",
        "npm ci --no-audit --no-fund && npx opennextjs-cloudflare build",
      ],
      { cwd: staging, env: { ...process.env, MSYS_NO_PATHCONV: "1" } },
    );

    verificarBundle(staging);

    paso("Trayendo el artefacto compilado");
    rmSync(join(RAIZ, ".open-next"), { recursive: true, force: true });
    cpSync(join(staging, ".open-next"), join(RAIZ, ".open-next"), { recursive: true });
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

function construirNativo() {
  paso("Compilando");
  correr("npx", ["opennextjs-cloudflare", "build"]);
  verificarBundle(RAIZ);
}

try {
  if (ES_WINDOWS) {
    construirEnDocker();
  } else {
    construirNativo();
  }

  paso("Desplegando a Cloudflare Workers");
  correr("npx", ["opennextjs-cloudflare", "deploy"]);

  paso("Comprobando el sitio publicado");
  // fetch de Node en vez de curl: en cmd.exe el %{http_code} de curl se
  // interpreta como una variable de entorno y la comprobacion nunca corria.
  let codigo = "000";
  for (let intento = 1; intento <= 5; intento += 1) {
    try {
      const respuesta = await fetch("https://datacenter.aaronbrumat.com.ar/demo", {
        redirect: "follow",
      });
      codigo = String(respuesta.status);
      if (codigo === "200") break;
    } catch {
      codigo = "000";
    }
    if (intento < 5) await new Promise((r) => setTimeout(r, 5000));
  }
  console.log(`  /demo -> ${codigo}`);
  if (codigo !== "200") {
    throw new Error(
      `/demo respondio ${codigo}. Revisa los registros con:\n` +
        "  npx wrangler tail data-center-frontend\n" +
        "Y si hace falta volver atras:\n" +
        "  npx wrangler deployments list\n" +
        "  npx wrangler rollback <version-id>",
    );
  }
  console.log("\n\x1b[32m/demo responde 200. Despliegue correcto.\x1b[0m");
} catch (error) {
  console.error(`\n\x1b[31m${error.message ?? error}\x1b[0m`);
  process.exit(1);
}
