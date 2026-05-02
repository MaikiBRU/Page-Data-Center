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
  
## Calidad y smoke test

Frontend:

```powershell
npm run lint
npm run build
```

Backend:

```powershell
python scripts/smoke_test.py
```
