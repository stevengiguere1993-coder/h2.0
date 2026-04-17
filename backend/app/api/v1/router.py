"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, blog, clients, contact, projects
from app.api.v1.endpoints.business import (
    achats_router,
    agenda_router,
    bons_router,
    employes_router,
    factures_router,
    fournisseurs_router,
    punch_router,
    soumissions_router,
)

api_router = APIRouter()

# Core
api_router.include_router(auth.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(contact.router)
api_router.include_router(blog.router)

# Business
api_router.include_router(employes_router)
api_router.include_router(fournisseurs_router)
api_router.include_router(soumissions_router)
api_router.include_router(agenda_router)
api_router.include_router(bons_router)
api_router.include_router(punch_router)
api_router.include_router(factures_router)
api_router.include_router(achats_router)
