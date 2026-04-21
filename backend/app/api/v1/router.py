"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    blog,
    clients,
    contact,
    projects,
    qbo_token,
    soumission_items,
    soumission_qbo,
    soumission_send,
    soumission_status,
    soumission_to_project,
    webhooks,
)
from app.api.v1.endpoints.business import (
    achats_router,
    agenda_router,
    bons_router,
    employes_router,
    factures_router,
    fournisseurs_router,
    punch_router,
    soumissions_router,
    sous_traitants_router,
)

api_router = APIRouter()

# Core
api_router.include_router(auth.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(contact.router)
api_router.include_router(blog.router)
api_router.include_router(webhooks.router)
api_router.include_router(qbo_token.router)

# Business
api_router.include_router(employes_router)
api_router.include_router(fournisseurs_router)
api_router.include_router(sous_traitants_router)
api_router.include_router(soumissions_router)
api_router.include_router(soumission_items.router)
api_router.include_router(soumission_qbo.router)
api_router.include_router(soumission_send.router)
api_router.include_router(soumission_status.router)
api_router.include_router(soumission_to_project.router)
api_router.include_router(agenda_router)
api_router.include_router(bons_router)
api_router.include_router(punch_router)
api_router.include_router(factures_router)
api_router.include_router(achats_router)
