# Data Quality Control Center

Aplicacion full-stack para monitoreo de calidad de datos orientada a ecommerce y logistica. Incluye autenticacion local + Google, datasets simulados o cargados por usuario, corridas de calidad, deteccion de anomalias, recomendaciones accionables, gestion de casos y administracion de usuarios/roles.

## Stack

- Frontend: Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts
- Backend: FastAPI, SQLAlchemy, Pydantic, PostgreSQL
- Auth: JWT + Google OAuth
- Infra local: Docker Compose para Postgres

## Modulos

- `Dashboard`: KPIs, comparativas, insights y exportes
- `Datasets`: alta, generacion, carga CSV, preview, reglas, corridas e historial
- `Casos`: SLA, estados avanzados, timeline, notas y exportes
- `Recomendaciones`: acciones sugeridas, impacto agregado y creacion en lote
- `Usuarios`: alta/baja, roles, admins, auditoria y reset manual de password

## Estructura

- `backend/`: API FastAPI y modelo de dominio
- `frontend/`: app web Next.js
- `data/uploads/`: datasets generados/cargados localmente
- `logs/`: logs locales de ejecucion y reset de password

## Requisitos

- Python 3.12+ recomendado
- Node.js 20+
- Docker Desktop

## Variables de entorno

Backend: copiar `backend/.env.example` a `backend/.env`

Frontend: copiar `frontend/.env.example` a `frontend/.env.local`

## Puesta en marcha

1. Base de datos:

```powershell
cd "C:\Users\Aaron\Desktop\COSAS\Proyecto 02"
docker compose up -d
```

2. Backend:

```powershell
cd "C:\Users\Aaron\Desktop\COSAS\Proyecto 02\backend"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

3. Frontend:

```powershell
cd "C:\Users\Aaron\Desktop\COSAS\Proyecto 02\frontend"
npm install
npm run dev
```

App: `http://127.0.0.1:3000`

API: `http://127.0.0.1:8000`

## Calidad y smoke test

Frontend:

```powershell
cd "C:\Users\Aaron\Desktop\COSAS\Proyecto 02\frontend"
npm run lint
npm run build
```

Backend:

```powershell
cd "C:\Users\Aaron\Desktop\COSAS\Proyecto 02\backend"
python scripts/smoke_test.py
```
