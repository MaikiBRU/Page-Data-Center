from fastapi import APIRouter

from app.api.routes import auth, cases, dashboard, datasets, users, runs

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(cases.router)
api_router.include_router(dashboard.router)
api_router.include_router(users.router)
api_router.include_router(runs.router)
