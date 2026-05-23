"""
API v1 Router

Main router that aggregates all API v1 endpoints.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin_or_owner
from app.api.v1.endpoints import (
    admin_data,
    agenda_availability,
    agenda_unified,
    appointment_types,
    lea_web,
    letmetalk,
    webhooks_meta,
    ai,
    appointments,
    audit,
    auth,
    blog,
    calendar,
    clients,
    devlog,
    employes,
    entreprises,
    extension,
    follow_ups,
    contact,
    contacts,
    entreprise_extras,
    entreprise_partners_links,
    immobilier,
    immobilier_extras,
    investissements,
    dashboard,
    help,
    kratos,
    ndas,
    offers,
    org_nodes,
    org_seed_canonical,
    rencontres,
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
    public_nda,
    public_offer,
    sales_tasks,
    service_templates,
    user_roles,
    users,
    project_billables,
    project_finances,
    project_members,
    project_phases,
    project_photos,
    project_tasks,
    project_to_facture,
    projects,
    public_bon,
    public_devlog_contact,
    public_devlog_invoice,
    push,
    public_contract,
    public_devlog_soumission,
    public_facture,
    public_purchase_agreement,
    public_soumission,
    purchase_agreement_milestones,
    purchase_agreement_template,
    purchase_agreements,
    punch_ops,
    achat_qbo,
    email_templates,
    mtl_properties,
    lead_analyses,
    prospection,
    prospection_analyse_extract,
    prospection_analyses,
    prospection_deals,
    prospection_lists,
    rental_comparables,
    purchase_order_actions,
    purchase_order_items,
    client_qbo,
    cron_runner,
    numbering,
    qbo_account_map,
    qbo_oauth,
    qbo_token,
    search,
    contract_sign,
    soumission_items,
    soumission_qbo,
    soumission_send,
    soumission_status,
    soumission_to_client,
    soumission_to_project,
    soumissions_aggregates,
    subcontractor_contracts,
    voice,
    webhooks,
)
from app.api.v1.endpoints.business import (
    achats_router,
    purchase_orders_router,
    agenda_router,
    bons_router,
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
# Le pôle Dev Logiciel est restreint à admin/owner (Phil + Steven).
# La garde est appliquée à TOUS les routers internes du pôle ; seuls
# les routers publics (signature contrat sans login, formulaire de
# contact, signature soumission, consultation facture) restent ouverts.
_devlog_admin_only = [Depends(get_current_admin_or_owner)]
api_router.include_router(devlog.clients_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.leads_router, dependencies=_devlog_admin_only)
# Automations DOIT être registered AVANT soumissions_router pour que
# le PATCH override (auto-création projet quand status → acceptee) et
# /soumissions/{id}/convert-to-project matchent avant le CRUD générique.
api_router.include_router(devlog.soumission_automations_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.soumissions_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.projects_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.time_entries_router, dependencies=_devlog_admin_only)
# invoice_automations_router DOIT être registered AVANT invoices_router
# pour que /devlog/invoices/{id}/send, /pdf et /mark-paid matchent
# avant le CRUD générique /devlog/invoices/{item_id}.
api_router.include_router(devlog.invoice_automations_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.invoices_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.soumission_items_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.soumission_sections_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.related_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.sous_traitants_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.invoice_items_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.lead_needs_router, dependencies=_devlog_admin_only)
api_router.include_router(devlog.contracts_router, dependencies=_devlog_admin_only)
# public_contracts_router = signature de contrat sans auth (prefix /public/devlog).
# Ne PAS protéger sinon les clients externes ne peuvent plus signer.
api_router.include_router(devlog.public_contracts_router)
# Page publique signature soumission devis_dev — /public/devlog/soumissions/{token}
api_router.include_router(public_devlog_soumission.router)
# Page publique consultation facture devlog — /public/devlog/invoices/{token}
api_router.include_router(public_devlog_invoice.router)
# Nested project routes MUST be registered before projects.router so
# /projects/{id}/photos etc. are matched before /projects/{item_id}.
api_router.include_router(project_photos.router)
api_router.include_router(project_tasks.router)
api_router.include_router(project_phases.router)
api_router.include_router(project_phases.phases_router)
api_router.include_router(project_members.router)
api_router.include_router(project_finances.router)
api_router.include_router(project_billables.router)
api_router.include_router(subcontractor_contracts.router)
api_router.include_router(projects.router)
api_router.include_router(contact.router)
api_router.include_router(contacts.router)
api_router.include_router(blog.router)
api_router.include_router(webhooks.router)
api_router.include_router(voice.router)
api_router.include_router(public_soumission.router)
api_router.include_router(public_contract.router)
api_router.include_router(public_facture.router)
api_router.include_router(contract_sign.router)
api_router.include_router(contract_sign.docs_router)
api_router.include_router(public_bon.router)
api_router.include_router(push.router)
api_router.include_router(appointment_types.router)
api_router.include_router(agenda_availability.router)
api_router.include_router(user_roles.router)
api_router.include_router(lea_web.router)
api_router.include_router(letmetalk.router)
api_router.include_router(webhooks_meta.router)
api_router.include_router(public_purchase_agreement.router)
# Offre d'achat minimaliste — flow indépendant du PurchaseAgreement
# complet (modèle Offer dédié, page publique /sign-offer/{token}).
api_router.include_router(offers.router)
api_router.include_router(public_offer.router)
# NDA investisseurs — entente de confidentialité minimaliste pour
# partager les infos d'un deal Pipeline avec un investisseur
# potentiel (modèle NDA dédié, page publique /sign-nda/{token}).
api_router.include_router(ndas.router)
api_router.include_router(public_nda.router)
api_router.include_router(qbo_token.router)
api_router.include_router(qbo_oauth.router)
api_router.include_router(client_qbo.router)
api_router.include_router(achat_qbo.router)
api_router.include_router(purchase_order_actions.router)
api_router.include_router(cron_runner.router)
api_router.include_router(numbering.router)
api_router.include_router(qbo_account_map.router)
api_router.include_router(extension.router)
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
api_router.include_router(follow_ups.router)

# Business
api_router.include_router(employes.router)
api_router.include_router(fournisseurs_router)
api_router.include_router(sous_traitants_router)
api_router.include_router(soumissions_router)
api_router.include_router(soumission_items.router)
api_router.include_router(soumission_qbo.router)
api_router.include_router(soumission_send.router)
api_router.include_router(soumission_status.router)
api_router.include_router(soumissions_aggregates.router)
api_router.include_router(soumission_to_client.router)
api_router.include_router(soumission_to_project.router)
# /agenda/unified DOIT être avant agenda_router (CRUD générique avec
# /agenda/{item_id}) pour que le path littéral matche en premier.
api_router.include_router(agenda_unified.router)
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
api_router.include_router(purchase_orders_router)
api_router.include_router(purchase_order_items.router)
# prospection_lists DOIT être registered AVANT prospection.router
# pour que /prospection/lists/* soit matché avant /prospection/{lead_id}.
# Idem pour mtl_properties qui a /prospection/mtl-properties/* et
# prospection_analyses qui a /prospection/analyses/* — match littéral
# avant /prospection/{lead_id}.
api_router.include_router(prospection_lists.router)
# rental_comparables : prefix /prospection/rental-comparables, doit
# matcher avant /prospection/{lead_id} comme les autres.
api_router.include_router(rental_comparables.router)
api_router.include_router(mtl_properties.router)
# /prospection/analyses/extract DOIT être avant prospection_analyses
# pour que le path littéral matche avant /prospection/analyses/{id}.
api_router.include_router(prospection_analyse_extract.router)
api_router.include_router(prospection_analyses.router)
api_router.include_router(lead_analyses.router)
# /prospection/deals DOIT être avant prospection.router pour la même
# raison que les autres : éviter la collision avec /prospection/{lead_id}.
api_router.include_router(prospection_deals.router)
# purchase_agreements + pa-milestones DOIVENT être avant prospection.router
# pour que /prospection/{lead_id}/purchase-agreements et /prospection/pa-milestones
# matchent avant /prospection/{lead_id}.
api_router.include_router(purchase_agreements.router)
api_router.include_router(purchase_agreement_milestones.router)
api_router.include_router(purchase_agreement_template.router)
api_router.include_router(prospection.router)
api_router.include_router(email_templates.router)
api_router.include_router(admin_data.router)
api_router.include_router(help.router)
api_router.include_router(kratos.router)
api_router.include_router(org_nodes.router)
api_router.include_router(org_seed_canonical.router)
api_router.include_router(rencontres.router)
api_router.include_router(ai.router)
api_router.include_router(entreprises.router)
# entreprise_extras DOIT être registered avant entreprises.router pour que
# /entreprises/finance/* et /entreprises/value-plans/* matchent avant
# /entreprises/{id}.
api_router.include_router(entreprise_extras.router)
# Partners + links DOIT être avant entreprises.router pour matcher
# /entreprises/{id}/partners et /entreprises/{id}/links avant
# /entreprises/{id} (PATCH).
api_router.include_router(entreprise_partners_links.router)
# immobilier_extras DOIT être registered avant immobilier.router pour que
# /immobilier/tal/* et /immobilier/renouvellements/* matchent avant les
# routes plus génériques de /immobilier.
api_router.include_router(immobilier_extras.router)
api_router.include_router(immobilier.router)
api_router.include_router(investissements.router)
# Formulaire public Dev Logiciel — endpoint POST /public/devlog/contact
# sans auth, cree un DevlogLead avec source=web_form au submit.
api_router.include_router(public_devlog_contact.router)

