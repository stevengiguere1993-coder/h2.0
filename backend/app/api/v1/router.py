"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    appointments,
    audit,
    auth,
    blog,
    calendar,
    clients,
    contact,
    dashboard,
    achat_receipt,
    bon_items,
    bon_send,
    facture_import,
    facture_items,
    facture_qbo,
    facture_send,
    leave_requests,
    measurements,
    mobile,
    notifications,
    payments,
    sales_tasks,
    service_templates,
    users,
    project_finances,
    project_phases,
    project_photos,
    project_tasks,
    project_to_facture,
    projects,
    public_bon,
    public_soumission,
    punch_ops,
    qbo_token,
    search,
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
api_router.include_router(users.router)
api_router.include_router(clients.router)
# Nested project routes MUST be registered before projects.router so
# /projects/{id}/photos etc. are matched before /projects/{item_id}.
api_router.include_router(project_photos.router)
api_router.include_router(project_tasks.router)
api_router.include_router(project_phases.router)
api_router.include_router(project_finances.router)
api_router.include_router(projects.router)
api_router.include_router(contact.router)
api_router.include_router(blog.router)
api_router.include_router(webhooks.router)
api_router.include_router(public_soumission.router)
api_router.include_router(public_bon.router)
api_router.include_router(qbo_token.router)
api_router.include_router(dashboard.router)
api_router.include_router(calendar.router)
api_router.include_router(appointments.router)
api_router.include_router(measurements.router)
api_router.include_router(sales_tasks.router)
api_router.include_router(mobile.router)
api_router.include_router(leave_requests.router)
api_router.include_router(service_templates.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)

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
api_router.include_router(bon_items.router)
api_router.include_router(bon_send.router)
api_router.include_router(bons_router)
# punch_ops FIRST so its literal paths (/me, /debug, /weekly, ...)
# are matched before the generic /{item_id} from punch_router, which
# would otherwise try to coerce "me"/"debug"/"weekly" to an int and
# return 422.
api_router.include_router(punch_ops.router)
api_router.include_router(punch_router)
api_router.include_router(factures_router)
# Payments sub-routes must come BEFORE facture_items so /factures/{id}/payments
# is matched before /factures/{id}/items (same prefix, different path).
api_router.include_router(payments.router)
api_router.include_router(facture_items.router)
api_router.include_router(facture_import.router)
api_router.include_router(facture_send.router)
api_router.include_router(facture_qbo.router)
api_router.include_router(project_to_facture.router)
# achat_receipt must come BEFORE achats_router so /achats/{id}/receipt
# is matched before the generic /achats/{item_id} tries to parse
# "receipt" as an integer.
api_router.include_router(achat_receipt.router)
api_router.include_router(achats_router)
