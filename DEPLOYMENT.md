# Data Center deployment

Production domains:

- Frontend: `https://datacenter.aaronbrumat.com.ar`
- Backend API: `https://api-datacenter.aaronbrumat.com.ar`
- Portfolio link: `https://aaronbrumat.com.ar`

> **Nota historica.** Una version anterior de este documento describia AWS App
> Runner, ECR y RDS. Nada de eso esta desplegado. Lo que sigue es la
> arquitectura verificada contra la infraestructura real.

## Arquitectura real

```
                        Cloudflare (DNS + TLS + Workers)
                                    |
   datacenter.aaronbrumat.com.ar ---+---> Worker (OpenNext / Next.js)
                                                    |
                                                    | fetch (https)
                                                    v
api-datacenter.aaronbrumat.com.ar --------> EC2  us-east-2, Ubuntu
                                              |
                                              +-- Caddy (systemd, TLS)
                                                    |
                                                    +-- docker compose
                                                          |-- api  (imagen data-center-api, uvicorn:8000)
                                                          `-- db   (postgres:16, volumen local)
```

Puntos que conviene tener claros porque contradicen suposiciones habituales:

- **No hay RDS.** PostgreSQL corre como contenedor en la misma instancia EC2,
  con un volumen de Docker. El respaldo es responsabilidad del despliegue, y
  por eso `scripts/deploy-backend.sh` hace un `pg_dump` antes de tocar nada.
- **No hay App Runner ni ECR.** La imagen se construye en la propia instancia
  con `docker compose build`.
- **No hay integracion automatica GitHub -> AWS.** Un push no despliega el
  backend. Hay que ejecutar el script en el servidor.
- El unico workflow que corre solo al hacer push es el de GitHub Pages, que
  publica el README en `maikibru.github.io/Page-Data-Center`. No es el sitio de
  produccion y no interviene en el despliegue.

## Backend (EC2)

Ubicacion en el servidor: `~/data-center`, que es un checkout de
`codex/public-clean`. El despliegue usa `docker-compose.prod.yml` (servicios
`db` y `api`) con `--env-file .env.prod`. El `docker-compose.yml` de la raiz
solo define la base para desarrollo local y no interviene en produccion.

```bash
ssh -i <clave>.pem ubuntu@<host>
cd ~/data-center
./scripts/deploy-backend.sh
```

El script: comprueba `.env.prod`, **respalda la base**, trae la rama, reconstruye la
imagen, levanta el contenedor y verifica. El entrypoint del contenedor corre
`alembic upgrade head` antes de uvicorn, de modo que el esquema se actualiza
antes de aceptar trafico; si una migracion falla el contenedor no arranca y la
version anterior sigue sirviendo.

El script imprime el comando exacto de vuelta atras, incluido el de restaurar
el volcado, si `/health` no responde.

### Seguridad de las migraciones

`0002` y `0003` son puramente aditivas: crean tablas y agregan columnas
anulables, cada paso consultando antes el catalogo, asi que son idempotentes y
no modifican ninguna fila existente. Se validaron reconstruyendo el esquema
anterior a Alembic (`create_all` mas los `ALTER` de arranque de la version
vieja) sobre PostgreSQL 16 con datos, aplicando `alembic upgrade head` y
comprobando que las filas seguian ahi y que `demo_session_id` quedaba en NULL,
es decir dentro de la particion de la aplicacion.

`0001` es un no-op deliberado: la base de produccion se construyo con
`create_all` y ALTERs ad-hoc, sin una revision anterior que reproducir, asi que
la primera revision vacia permite que `alembic upgrade head` funcione tanto
sobre esa base como sobre una nueva.

**Efecto esperado la primera vez:** los datasets analizados antes de esta
migracion no tienen conteo de filas distintas y no es recuperable de los
agregados viejos, asi que el dashboard mostrara "Sin datos" para ellos hasta
que se vuelva a correr calidad. Es intencional: la alternativa seria mostrar un
score que nunca se midio.

### Variables de entorno del backend

En `~/data-center/.env.prod`, nunca en el repositorio. Ademas de las de la
aplicacion, ese archivo aporta `POSTGRES_USER`, `POSTGRES_PASSWORD` y
`POSTGRES_DB`, que consume el servicio `db` del compose:

```env
ENVIRONMENT=production
SECRET_KEY=<generar: python -c "import secrets; print(secrets.token_urlsafe(48))">
DATABASE_URL=postgresql+psycopg://<usuario>:<clave>@db:5432/<base>
ALLOWED_ORIGINS=https://datacenter.aaronbrumat.com.ar
FRONTEND_URL=https://datacenter.aaronbrumat.com.ar
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://api-datacenter.aaronbrumat.com.ar/auth/google/callback
SENDGRID_API_KEY=
DEMO_ENABLED=true
DEMO_MAINTENANCE_TOKEN=
```

`SECRET_KEY` es obligatoria y no tiene valor por defecto: la aplicacion no
arranca sin ella, y rechaza valores conocidos como `change-me`. Cambiarla
invalida todos los tokens emitidos.

`ENVIRONMENT=production` no es cosmetico. Cierra `/docs`, `/redoc` y
`/openapi.json`, y fuerza que el enlace de recuperacion de contrasena nunca se
escriba en un log, sin importar lo que digan las otras variables. El script de
despliegue aborta si esta variable no esta en produccion, y comprueba despues
que esas rutas devuelvan 404.

## Frontend (Cloudflare Workers)

El frontend usa OpenNext sobre Cloudflare Workers.

### La URL de la API se hornea en el build

`NEXT_PUBLIC_API_URL` no se lee en tiempo de ejecucion: Next.js la sustituye
dentro del bundle del cliente durante `next build`. De ahi salen tres trampas
que compilan y despliegan sin error pero dejan el frontend llamando al host
equivocado:

1. **Los `vars` de `wrangler.jsonc` no cubren esto.** Son bindings de runtime
   del Worker; el codigo del navegador ya fue compilado para entonces.
2. **`.env.local` gana sobre todo lo demas y tambien se lee en builds de
   produccion.** Una maquina de desarrollo con `http://127.0.0.1:8000` ahi
   hornearia localhost en el bundle publicado, y cualquier visitante recibiria
   "No se pudo contactar el servidor".
3. Por eso el valor no puede depender de que alguien recuerde exportarlo.

El proyecto lo resuelve en dos capas:

- **`frontend/.env.production`** (versionado) fija la URL de produccion. Un
  clon limpio o un runner de CI compila correcto sin ningun paso manual. Se
  versiona a proposito: los valores `NEXT_PUBLIC_*` terminan visibles en el
  JavaScript publicado, asi que no hay nada que ocultar.
- **`frontend/next.config.ts`** corta el build de produccion si la variable
  falta, apunta a una direccion local o no usa https. Convierte el fallo
  silencioso en un error de build con el comando de solucion en el mensaje.

Para compilar a proposito un bundle de produccion contra un backend local:
`NEXT_PUBLIC_ALLOW_LOCAL_API=1 npm run build`. La comprobacion corre solo
durante `next build`; `next start` arranca un build ya compilado sin volver a
mirarla, porque a esa altura el valor ya esta horneado.

### Nada de middleware

`src/proxy.ts` (el nuevo nombre de `middleware.ts` en Next 16) siempre corre en
el runtime de Node y no admite cambiarlo -- fijar `runtime` ahi lanza un error.
OpenNext para Cloudflare no puede desplegar middleware de Node: el deploy
fallaba con "Node.js middleware is not currently supported", de modo que el
frontend entero era indesplegable.

La guarda de rutas vive ahora en `src/app/(app)/layout.tsx`, un componente de
servidor que lee la cookie y redirige. Mismo comportamiento, sin middleware. El
efecto secundario es que las paginas de la aplicacion pasan a renderizarse bajo
demanda en vez de prerenderizarse, que es lo correcto para pantallas que
dependen de la sesion.

### Desplegar

Preferido, sin depender de la maquina de nadie:

```
Actions -> "Deploy frontend (Cloudflare Workers)" -> Run workflow
```

Requiere dos secrets del repositorio (Settings > Secrets and variables >
Actions):

| Secret | De donde sale |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Cloudflare > My Profile > API Tokens, permiso `Workers Scripts: Edit` |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare > Workers & Pages, panel derecho |

El workflow compila, **verifica que el bundle apunte a la API de produccion y
no contenga localhost**, despliega y comprueba que `/demo` responda 200.

Manual, desde `frontend/`:

```powershell
npm run deploy
```

Funciona igual, siempre que `.env.local` no tenga una URL local; si la tiene,
el build se detiene con instrucciones en vez de publicar algo roto.

## Verificacion

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" https://api-datacenter.aaronbrumat.com.ar/health
curl.exe -s https://api-datacenter.aaronbrumat.com.ar/demo/config
curl.exe -s -o NUL -w "%{http_code}`n" https://datacenter.aaronbrumat.com.ar/demo
```

Esperado: `/health` devuelve 200 con `database: true`; `/demo/config` devuelve
los limites configurados; `/demo` responde 200.

Y estas tres deben devolver **404** en produccion:

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" https://api-datacenter.aaronbrumat.com.ar/docs
curl.exe -s -o NUL -w "%{http_code}`n" https://api-datacenter.aaronbrumat.com.ar/openapi.json
curl.exe -s -o NUL -w "%{http_code}`n" -X POST https://api-datacenter.aaronbrumat.com.ar/auth/register
```

Si `/docs` devuelve 200, `ENVIRONMENT` no es `production`. Si `/auth/register`
devuelve algo distinto de 404, el backend esta corriendo codigo anterior al
cierre del registro publico.

## Enlace desde el portfolio

```text
https://datacenter.aaronbrumat.com.ar/demo
```

`/dashboard` tambien funciona (un visitante anonimo es redirigido a `/demo`),
pero enlazar `/demo` evita el salto.
