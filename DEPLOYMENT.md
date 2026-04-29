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
- Health check path: `/`

Required environment variables:

```env
SECRET_KEY=<generate-a-long-random-secret>
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/<database>
ALLOWED_ORIGINS=https://datacenter.aaronbrumat.com.ar
FRONTEND_URL=https://datacenter.aaronbrumat.com.ar
GOOGLE_REDIRECT_URI=https://api-datacenter.aaronbrumat.com.ar/auth/google/callback
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SENDGRID_API_KEY=
EMAIL_FROM=no-reply@aaronbrumat.com.ar
```

After App Runner is live, create a Cloudflare DNS record:

```text
Type: CNAME
Name: api-datacenter
Target: <app-runner-default-domain>
Proxy: Proxied
```

## Frontend on Cloudflare Workers

The frontend uses OpenNext for Cloudflare Workers.

Required build/runtime variable:

```env
NEXT_PUBLIC_API_URL=https://api-datacenter.aaronbrumat.com.ar
```

Local deploy command from `frontend/`:

```powershell
npm run deploy
```

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

The backend root should return `200 OK`. The frontend should load the login page and API calls should use `https://api-datacenter.aaronbrumat.com.ar`.
