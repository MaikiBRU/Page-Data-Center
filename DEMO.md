# Demo Sandbox

Public, anonymous, throwaway workspaces so anyone can try Data Center from the
portfolio without an account.

```
Portfolio  ->  /demo  ->  "Comenzar demo"  ->  /dashboard (con datos)
                                    |
                             sesion temporal
                                    |
                        expira -> datos eliminados
```

The authenticated application (JWT + Google OAuth, roles, user administration)
is untouched. The sandbox is a second, parallel identity that lives beside it.

---

## 1. How a session is created

`POST /demo/session` — public, no credentials, no body.

1. **Rate limit.** Per client IP (from `X-Forwarded-For`, hashed with the app
   secret before storage), a sliding one-hour window.
2. **Capacity check.** A database count of live sessions against
   `DEMO_MAX_ACTIVE_SESSIONS`.
3. **Row insert.** `demo_sessions` gets a row whose primary key is
   `secrets.token_urlsafe(32)` — 43 URL-safe characters of CSPRNG output. Not a
   sequence, not enumerable.
4. **Seeding.** Three datasets are generated, stored and analysed through the
   *same* pipeline the authenticated app uses (`services/quality_run.py`), each
   with its own random seed so two visitors do not see identical numbers.
5. **Token.** A JWT is returned:

   ```json
   { "sub": "demo:<id>", "typ": "demo", "sid": "<id>", "exp": <ttl> }
   ```

If seeding fails at any point the session is torn down before responding, so a
half-built sandbox is never handed out.

### Why a bearer token and not a cookie

The frontend and API are on different origins
(`datacenter.…` → `api-datacenter.…`). A session cookie there needs
`SameSite=None; Secure` plus credentialed CORS, which *introduces* CSRF surface.
A bearer token in the `Authorization` header is immune to CSRF by construction
and reuses the transport the app already had.

A separate, value-free cookie (`dc_has_session=1`) is set purely so the Next.js
proxy can route. It is not a credential and grants nothing — see §6.

---

## 2. How data is isolated

Two columns carry the partition key:

| Table      | Column            | Meaning                                        |
| ---------- | ----------------- | ---------------------------------------------- |
| `datasets` | `demo_session_id` | `NULL` = the authenticated app; value = sandbox |
| `cases`    | `demo_session_id` | same (denormalised so no join is needed)        |

Everything else scopes through those two: `dataset_runs` via `dataset_id`,
`case_notes` / `case_status_logs` / `case_activity_logs` via `case_id`,
`demo_dataset_files` via both.

Enforcement lives in `app/api/deps.py`:

```python
def scope_datasets(query, principal):
    if principal.is_demo:
        return query.filter(Dataset.demo_session_id == principal.demo_session_id)
    return query.filter(Dataset.demo_session_id.is_(None))
```

Isolation is **bidirectional**: a demo session never sees application rows, and
the authenticated app never sees sandbox rows. Single-record loads go through
`get_scoped_dataset` / `get_scoped_case`, which raise **404, not 403**, so a
response never confirms that somebody else's id exists.

### The fail-closed property

`get_current_user` **rejects demo tokens** with 403. Every endpoint that was not
deliberately opened to the sandbox still depends on it — user administration,
the audit log, the assignable-users list — and is therefore closed to demo
callers by default. Forgetting to harden a new endpoint fails closed.

`tests/test_demo_permissions.py::test_demo_role_is_not_granted_any_administrative_permission`
pins the permission matrix so a future edit cannot quietly widen it.

---

## 3. What a sandbox may do

Allowed: dashboard, datasets, CSV upload, dataset generation, quality runs,
issues, anomalies, recommendations, cases (create, update, notes, SLA,
timeline), run history, exports.

Refused (403):

- `/users`, `/users/audit`, `/users/assignable` — user administration and real
  people's email addresses
- `PATCH /datasets/{id}/domain|rules|assignment` — configuration that changes
  how results are produced, and assignment routing that points at real users
- `/dashboard/demo/reset`, `/dashboard/demo/regenerate` — administrative
  operations over the *application's* datasets

Cases generated inside a sandbox are never assigned to a real user: the
round-robin assigner is skipped for demo datasets.

---

## 4. Where files live

Demo CSVs are rows in PostgreSQL (`demo_dataset_files.content`, `bytea`), not
files on disk.

The audit found that App Runner's filesystem is ephemeral: on every restart the
dataset row survived while its file did not, leaving `file_path` pointing at
nothing (preview 404, run-quality 500). Rather than add S3 for at most 6 MB per
session, the payload goes in the database it already has. It costs nothing new,
and a sandbox is erased atomically with its session.

The authenticated app keeps writing to `data/uploads` exactly as before — that
path is unchanged. *(Fixing it for the authenticated app is still open; see
§9.)*

### Untrusted uploads

`services/dataset_storage.py` handles all of it:

- **Filename**: reduced to a bare leaf name — separators, drive letters and
  parent references are stripped. `../../../app/main.py` becomes `main.py.csv`.
  The pre-existing path traversal (`dataset_dir / file.filename` with the raw
  value) is closed for both paths, and the disk path is additionally re-checked
  against its parent after resolution.
- **Size**: the body is read in 64 KB chunks and aborted the moment it exceeds
  the ceiling, so an oversized upload is never fully materialised.
- **Content**: the declared MIME type and the `.csv` extension are ignored. The
  bytes are decoded and parsed; a payload with NUL bytes, no header, no data
  row, or more than 200 columns is rejected with 400.

---

## 5. Expiry and cleanup

A session dies on **either** condition:

- absolute TTL — `DEMO_SESSION_TTL_MINUTES` after creation
- idle timeout — `DEMO_IDLE_TIMEOUT_MINUTES` after the last request

Expiry is decided **on every request** in `load_active_session`, not by the
cleanup job. A lapsed session stops working immediately, whether or not its rows
have been deleted yet. Unknown, revoked, TTL-expired and idle-expired sessions
all return the same 401 message, so probing cannot tell them apart.

Cleanup runs three ways, all calling the same idempotent
`purge_session_data`:

1. **Background loop** in the API process, every
   `DEMO_CLEANUP_INTERVAL_SECONDS`. App Runner has no scheduler and a portfolio
   demo does not justify standing one up. If the loop dies the demo stays
   *correct* — requests still reject expired sessions — and merely accumulates
   rows.
2. **`POST /demo/maintenance/cleanup`**, guarded by
   `X-Demo-Maintenance-Token`. Returns 404 when `DEMO_MAINTENANCE_TOKEN` is
   unset, so it is never open by default. For driving cleanup from outside the
   process.
3. **Visitor-initiated**: `POST /demo/session/end` wipes everything now;
   `POST /demo/session/reset` wipes and reseeds while keeping the same token.

Cleanup also reclaims orphans — demo rows whose session row is already gone —
and never touches rows with `demo_session_id IS NULL`.

---

## 6. Frontend

| Piece                        | Role                                                       |
| ---------------------------- | ---------------------------------------------------------- |
| `src/proxy.ts`               | Server-side routing guard (Next 16 renamed `middleware`)    |
| `src/app/(auth)/demo/`       | Public landing page                                        |
| `src/components/DemoBanner`  | One-row status strip: mode, quota, time left, reset/end    |
| `src/lib/demo.ts`            | Session client and demo-mode flag                          |

**The bug this fixes.** `/dashboard` used to answer 200 with the full shell to
anyone. The bounce to `/login` only happened after hydration, when the sidebar's
unconditional `/auth/me` call came back 401 — so a first-time visitor from the
portfolio saw the app flash and then a red *"Sesión expirada"* error for a
session they never had. Now the proxy redirects before anything renders, and the
sidebar no longer calls `/auth/me` without a token.

The `dc_has_session` cookie is a **routing** input, not an authorisation one.
Forging it buys nothing: the page loads and every API call behind it returns
401, because the API re-reads the bearer token and its session on each request.

---

## 7. Environment variables

| Variable                        | Default | Meaning                                       |
| ------------------------------- | ------- | --------------------------------------------- |
| `DEMO_ENABLED`                  | `true`  | Master switch; `false` makes `/demo/*` 404     |
| `DEMO_MAX_DATASETS`             | `3`     | Datasets per session (seed included)           |
| `DEMO_MAX_FILE_SIZE_MB`         | `2.0`   | Per CSV                                        |
| `DEMO_MAX_STORAGE_MB`           | `6.0`   | Total per session                              |
| `DEMO_MAX_RUNS`                 | `20`    | Quality runs per session                       |
| `DEMO_MAX_EXPORTS`              | `30`    | Report exports per session                     |
| `DEMO_SESSION_TTL_MINUTES`      | `45`    | Absolute lifetime                              |
| `DEMO_IDLE_TIMEOUT_MINUTES`     | `20`    | Inactivity lifetime                            |
| `DEMO_SEED_ROWS`                | `400`   | Rows per seeded dataset                        |
| `DEMO_SEED_ANOMALY_RATE`        | `0.12`  | Fault injection rate when seeding              |
| `DEMO_RATE_LIMIT_PER_HOUR`      | `12`    | Sessions per client IP per hour                |
| `DEMO_MAX_ACTIVE_SESSIONS`      | `200`   | Global concurrent cap                          |
| `DEMO_CLEANUP_INTERVAL_SECONDS` | `300`   | Cleanup loop period; `0` disables              |
| `DEMO_MAINTENANCE_TOKEN`        | unset   | Secret for the cleanup endpoint; unset = 404   |

### Where the limits come from

Measured on this codebase, not guessed:

```
generated row                  ~185 bytes
CSV -> parsed records in RAM   ~12x the file size
quality pipeline               ~28 us per row
```

So 2 MB ≈ 11,000 rows ≈ 250 ms of CPU and ~24 MB of peak RAM for one request —
comfortable on App Runner's smallest 1 vCPU / 2 GB configuration. Worst-case
storage is `DEMO_MAX_STORAGE_MB × DEMO_MAX_ACTIVE_SESSIONS` = 1.2 GB, and in
practice far less because sessions live 45 minutes.

---

## 8. Schema changes

Alembic now owns the schema (`backend/alembic/`).

- `0001_baseline` — intentionally empty. The production database was built by
  `create_all` plus ad-hoc `ALTER`s in `main.py`, so there is no earlier
  revision to replay. An empty first revision makes `alembic upgrade head`
  correct against both the existing database and a fresh one, with no manual
  stamping.
- `0002_demo_sandbox` — creates `demo_sessions` and `demo_dataset_files`, adds
  `demo_session_id` plus its index to `datasets` and `cases`. Every step checks
  the catalogue first, so it is safe to re-run. **No existing row is modified**:
  pre-existing datasets and cases keep `demo_session_id = NULL` and stay in the
  application partition.

The Dockerfile runs `alembic upgrade head` before uvicorn starts. The legacy
startup DDL is retained under `run_legacy_schema_sync()` so existing deployments
keep booting unchanged; nothing new is added there.

Verified against a database seeded to look like current production: the
migration applied, existing rows survived with `demo_session_id = NULL`, and a
second run was a no-op.

---

## 9. Known gaps

- **Rate limiting is per process.** In-memory, so if App Runner scales past one
  instance the effective limit becomes per-instance. The database-backed
  `DEMO_MAX_ACTIVE_SESSIONS` cap still holds globally.
- **The authenticated app still writes to the ephemeral filesystem.** Only the
  demo path was moved into the database. Fixing the app path is a separate
  change.
- **Dashboard metric definitions were not changed** — the "issues" ambiguity,
  the always-`+100%` weekly deltas and the invented USD impact figure from the
  audit are all still there. They are cosmetically visible in the demo.
- **Anomaly detection recall is still ~7%.** The z-score is computed over
  contaminated data. Unchanged here on purpose; it is its own task.

---

## 10. Tests

```bash
cd backend && python -m pytest
```

65 tests, no database container required (SQLite in-memory, the real app
otherwise). Coverage: session creation, valid/expired/idle/revoked/unknown
sessions, forged and wrong-secret tokens, cross-session isolation for datasets,
cases, runs, KPIs and bulk operations, IDOR on read and write, every quota,
filename sanitisation and traversal, content validation, cleanup and its
idempotency, orphan reclamation, application data survival, the administrative
surface, and abuse controls.
