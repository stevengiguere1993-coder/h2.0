"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, clients, projects

api_router = APIRouter()

# Authentication endpoints
api_router.include_router(auth.router)

# Client endpoints
api_router.include_router(clients.router)

# Project endpoints
api_router.include_router(projects.router)
