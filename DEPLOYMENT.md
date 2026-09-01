# Data Center deployment

Production domains:

- Frontend: `https://datacenter.aaronbrumat.com.ar`
- Backend API: `https://api-datacenter.aaronbrumat.com.ar`
- Portfolio link: `https://aaronbrumat.com.ar`

## Backend on AWS

Recommended AWS services:

- PostgreSQL: Amazon RDS PostgreSQL.
- API runtime: AWS App Runner from the `backend/Dockerfile`.

App Runner settings:

- Source repository: `MaikiBRU/Page-Data-Center`
- Source directory: `backend`
- Dockerfile: `Dockerfile`
- Port: `8000`
- Health check path: `/health` (verifies the database connection; `/` only
  reports that the process is up)

The container entrypoint runs `alembic upgrade head` before uvicorn, so schema
changes are applied before the API accepts traffic.

Required environment variables:

```env
ENVIRONMENT=production
SECRET_KEY=<generate-a-long-random-secret>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/<database>
ALLOWED_ORIGINS=https://datacenter.aaronbrumat.com.ar
FRONTEND_URL=https://datacenter.aaronbrumat.com.ar
GOOGLE_REDIRECT_URI=https://api-datacenter.aaronbrumat.com.ar/auth/google/callback
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SENDGRID_API_KEY=
EMAIL_FROM=no-reply@aaronbrumat.com.ar

# Demo sandbox. See DEMO.md for the full table and the reasoning behind
# each limit. The defaults are usable as-is; set the maintenance token only
# if you want to drive cleanup from outside the process.
DEMO_ENABLED=true
DEMO_MAINTENANCE_TOKEN=<generate-a-long-random-secret-or-leave-unset>
```

Cleanup of expired sandboxes runs inside the API process on a timer
(`DEMO_CLEANUP_INTERVAL_SECONDS`, default 300s), so no scheduler is required.
Expired sessions are rejected at request time regardless of whether cleanup has
run yet.

`ENVIRONMENT=production` turns off `/docs`, `/redoc` and `/openapi.json`, and
forces the password reset link never to be written to a log. Both are on by
default in development.

`SECRET_KEY` is required and has no default: the service will not start
without it.

Brute force protection on `/auth/login` and `/auth/forgot-password` is
in-process. On a single instance the limits are exact; if App Runner scales to
several instances each keeps its own counters, so the effective allowance
multiplies by the instance count. Redis was judged not worth adding for this.

After App Runner is live, create a Cloudflare DNS record:

```text
Type: CNAME
Name: api-datacenter
Target: <app-runner-default-domain>
Proxy: Proxied
```

## Frontend on Cloudflare Workers

The frontend uses OpenNext for Cloudflare Workers.

### The API URL is baked in at build time

`NEXT_PUBLIC_*` variables are not read at runtime: Next.js substitutes them
into the client bundle during `next build`. Three consequences follow, and
getting any of them wrong ships a frontend that calls the wrong host while
still building and deploying successfully.

1. **`vars` in `wrangler.jsonc` does not cover this.** Those are runtime
   bindings for the Worker. The browser code has already been compiled by
   then, so the entry there is inert for `NEXT_PUBLIC_API_URL`.
2. **`.env.local` wins over everything and is read during production builds
   too.** A developer machine with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`
   in `frontend/.env.local` will bake *localhost* into the deployed bundle,
   and every visitor gets "No se pudo contactar el servidor".
3. **So the variable must be exported in the shell that runs the build**, not
   only configured in Cloudflare.

Deploy from `frontend/` like this:

```powershell
$env:NEXT_PUBLIC_API_URL = "https://api-datacenter.aaronbrumat.com.ar"
npm run deploy
```

Verify before shipping — the production host must appear in the compiled
assets and localhost must not:

```powershell
Select-String -Path .open-next/assets/_next/static/chunks/*.js -Pattern "api-datacenter" -List
Select-String -Path .open-next/assets/_next/static/chunks/*.js -Pattern "localhost:8000" -List
```

The first command must return matches and the second must return none.

After the Worker is live, bind the custom domain:

```text
datacenter.aaronbrumat.com.ar
```

## Verification

Expected checks:

```powershell
curl.exe -I https://api-datacenter.aaronbrumat.com.ar/
curl.exe -I https://datacenter.aaronbrumat.com.ar/
```

The backend root should return `200 OK`. The frontend root redirects an
anonymous visitor to `/demo` (not to the login page), and API calls should
use `https://api-datacenter.aaronbrumat.com.ar`.

Demo sandbox:

```powershell
curl.exe https://api-datacenter.aaronbrumat.com.ar/health
curl.exe https://api-datacenter.aaronbrumat.com.ar/demo/config
curl.exe -I https://datacenter.aaronbrumat.com.ar/demo
```

`/health` should report `database: true`, `/demo/config` should return the
configured limits, and `/dashboard` without a session should redirect to
`/demo` rather than rendering the application shell.

## Portfolio link

Point the portfolio's "Visualizar app" button at:

```text
https://datacenter.aaronbrumat.com.ar/demo
```

`/dashboard` also works — an anonymous visitor is redirected to `/demo` — but
linking `/demo` directly avoids the extra hop.
