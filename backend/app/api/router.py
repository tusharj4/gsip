"""Top-level API router — aggregates all versioned sub-routers."""

from fastapi import APIRouter

from app.api.v1 import layers, projects, analysis, routing, reports, ai

api_router = APIRouter()

api_router.include_router(layers.router, prefix="/v1/layers", tags=["layers"])
api_router.include_router(projects.router, prefix="/v1/projects", tags=["projects"])
api_router.include_router(analysis.router, prefix="/v1/analysis", tags=["analysis"])
api_router.include_router(routing.router, prefix="/v1/routing", tags=["routing"])
api_router.include_router(reports.router, prefix="/v1/reports", tags=["reports"])
api_router.include_router(ai.router, prefix="/v1/ai", tags=["ai"])
