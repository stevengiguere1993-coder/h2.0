"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router)

# Future endpoints will be included here:
# api_router.include_router(users.router, prefix="/users", tags=["users"])
# api_router.include_router(clients.router, prefix="/clients", tags=["clients"])
# api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
