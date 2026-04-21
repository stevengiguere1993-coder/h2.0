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
    facture_import,
    facture_items,
    facture_qbo,
    facture_send,
    project_to_facture,
    projects,
    punch_ops,
    qbo_token,
    soumission_items,
    soumission_qbo,
    soumission_send,
    soumission_status,
    soumission_to_client,
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
api_router.include_router(soumission_to_client.router)
api_router.include_router(soumission_to_project.router)
api_router.include_router(agenda_router)
api_router.include_router(bons_router)
# punch_ops FIRST so its literal paths (/me, /debug, /weekly, ...)
# are matched before the generic /{item_id} from punch_router, which
# would otherwise try to coerce "me"/"debug"/"weekly" to an int and
# return 422.
api_router.include_router(punch_ops.router)
api_router.include_router(punch_router)
api_router.include_router(factures_router)
api_router.include_router(facture_items.router)
api_router.include_router(facture_import.router)
api_router.include_router(facture_send.router)
api_router.include_router(facture_qbo.router)
api_router.include_router(project_to_facture.router)
api_router.include_router(achats_router)
