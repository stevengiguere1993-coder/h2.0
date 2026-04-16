"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, clients, contact, projects

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(clients.router)
api_router.include_router(contact.router)
api_router.include_router(projects.router)
