# Data Center

Aplicacion full-stack de monitoreo de calidad de datos para operaciones de
ecommerce y logistica. Analiza datasets con reglas por dominio, detecta valores
fuera de rango, puntua la calidad y convierte los hallazgos en incidencias con
responsable y SLA.

Incluye autenticacion local + Google, datasets generados o cargados por CSV,
corridas de calidad, deteccion de anomalias, recomendaciones accionables,
gestion de casos y administracion de usuarios y roles.

## Demo publica

[**datacenter.aaronbrumat.com.ar/demo**](https://datacenter.aaronbrumat.com.ar/demo)

Cualquiera puede probar la aplicacion sin registrarse: `/demo` crea un sandbox
temporal y aislado, ya poblado con datasets analizados. La sesion expira sola y
sus datos se eliminan automaticamente.

Ver [DEMO.md](DEMO.md) para la arquitectura, los limites y las variables de
entorno.

## Metricas

Las metricas del dashboard (quality score, filas afectadas, filas criticas,
hallazgos, violaciones y tendencia) estan definidas y justificadas en
[METRICS.md](METRICS.md). Ninguna es estimada ni monetaria.

## Stack

- Frontend: Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts
- Backend: FastAPI, SQLAlchemy, Pydantic, PostgreSQL
- Migraciones: Alembic
- Auth: JWT + Google OAuth, y sesiones de demo anonimas
- Infra local: Docker Compose para Postgres

## Modulos

- `Dashboard`: KPIs de calidad, insights y exportes
- `Datasets`: alta, generacion, carga CSV, preview, validacion de esquema, reglas, corridas e historial
- `Casos`: SLA, estados avanzados, timeline, notas y exportes
- `Recomendaciones`: acciones sugeridas, peso por severidad y creacion en lote
- `Usuarios`: alta/baja, roles, admins, auditoria y reset manual de password
- `Demo`: sandbox publico, temporal y aislado por visitante

## Estructura

- `backend/`: API FastAPI y modelo de dominio
- `backend/alembic/`: migraciones de esquema
- `backend/tests/`: suite de pytest (no requiere Docker)
- `frontend/`: app web Next.js
- `data/uploads/`: datasets generados/cargados localmente
- `logs/`: logs locales de ejecucion y reset de password

## Requisitos

- Python 3.12+ recomendado
- Node.js 20+
- Docker Desktop (solo para la base de datos local)

## Puesta en marcha local

1. Base de datos:

```powershell
docker compose up -d db
```

2. Backend (desde `backend/`):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Editar `.env` y completar `SECRET_KEY`. No tiene valor por defecto y la
aplicacion no arranca sin el; se genera con:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Luego:

```powershell
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

3. Frontend (desde `frontend/`):

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

Abrir `http://localhost:3000/demo`. El sandbox se crea solo, sin registro:
no hace falta ninguna cuenta para recorrer la aplicacion completa.

## Calidad y smoke test

Frontend:

```powershell
npm run lint
npm run build
```

Backend:

```powershell
python -m pytest
```

Smoke test end to end (requiere PostgreSQL corriendo):

```powershell
$env:SMOKE_ADMIN_PASSWORD = "<elegi-una>"; python scripts/smoke_test.py
```

`SMOKE_ADMIN_PASSWORD` es obligatoria y no tiene valor por defecto: el script
crea o resetea la cuenta de administrador, asi que la contrasena no puede vivir
en el repositorio. Ademas aborta si `DATABASE_URL` no apunta a loopback, para
que no pueda correrse contra una base desplegada.

## Migraciones

```powershell
alembic upgrade head
```

Se ejecuta automaticamente al arrancar el contenedor, antes de uvicorn.
