"""Endpoints — pôle Développement logiciel.

Ressources :
  * /api/v1/devlog/clients — clients du pôle (boîtes pour qui on
    développe des plateformes / logiciels) ;
  * /api/v1/devlog/leads — pipeline kanban du closer ;
  * /api/v1/devlog/soumissions — devis envoyés aux leads / clients.

Accessible à tout utilisateur authentifié : nouveau pôle interne,
petite équipe (closer / PM / devs partagent l'outil).
"""

from typing import List, Optional, Type

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.base import Base
from app.models.devlog_client import DevlogClient
from app.models.devlog_contract import DevlogContract
from app.models.devlog_invoice import DevlogInvoice
from app.models.devlog_invoice_item import DevlogInvoiceItem
from app.models.devlog_lead import LEAD_STATUSES, DevlogLead
from app.models.devlog_lead_need import DevlogLeadNeed
from app.models.devlog_project import DevlogProject
from app.models.devlog_soumission import DevlogSoumission
from app.models.devlog_soumission_item import DevlogSoumissionItem
from app.models.devlog_soumission_section import DevlogSoumissionSection
from app.models.devlog_sous_traitant import DevlogSousTraitant
from app.models.devlog_time_entry import DevlogTimeEntry
from app.repositories.generic import GenericCrud
from app.schemas.devlog import (
    DevisPreview,
    DevlogClientCreate,
    DevlogClientRead,
    DevlogClientUpdate,
    DevlogContractCreate,
    DevlogContractMarkDepositPaid,
    DevlogContractPublicRead,
    DevlogContractRead,
    DevlogContractSignRequest,
    DevlogContractUpdate,
    DevlogInvoiceCreate,
    DevlogInvoiceImportRequest,
    DevlogInvoiceImportResult,
    DevlogInvoiceItemCreate,
    DevlogInvoiceItemRead,
    DevlogInvoiceItemUpdate,
    DevlogInvoiceRead,
    DevlogInvoiceUpdate,
    DevlogLeadCreate,
    DevlogLeadNeedCreate,
    DevlogLeadNeedRead,
    DevlogLeadNeedUpdate,
    DevlogLeadPlan,
    DevlogLeadPlanToSoumissionRequest,
    DevlogLeadRead,
    DevlogLeadStatusUpdate,
    DevlogLeadUpdate,
    DevlogProjectCreate,
    DevlogProjectRead,
    DevlogProjectUpdate,
    DevlogSoumissionCreate,
    DevlogSoumissionItemCreate,
    DevlogSoumissionItemRead,
    DevlogSoumissionItemUpdate,
    DevlogSoumissionRead,
    DevlogSoumissionSectionCreate,
    DevlogSoumissionSectionRead,
    DevlogSoumissionSectionUpdate,
    DevlogSoumissionUpdate,
    DevlogSousTraitantCreate,
    DevlogSousTraitantRead,
    DevlogSousTraitantUpdate,
    DevlogTimeEntryCreate,
    DevlogTimeEntryRead,
    DevlogTimeEntryUpdate,
)
from app.services.audit import log_action
from app.services.devlog_client_provision import (
    convert_lead_to_client as _convert_lead_to_client_service,
)
from app.services.devlog_contract_signed_hook import on_contract_signed
from app.services.devlog_devis_calc import compute_devis
from app.services.devlog_project_provision import maybe_start_project
from app.services.devlog_invoice_pdf import (
    compute_invoice_totals,
    generate_invoice_pdf,
)
from app.services.devlog_invoice_send import (
    DevlogInvoiceSendError,
    send_invoice_email,
)
from app.services.devlog_soumission_pdf import generate_devis_pdf
from app.services.devlog_soumission_send import (
    DevlogSoumissionSendError,
    send_devis_email,
)


def _make_crud_router(
    *,
    prefix: str,
    model: Type[Base],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    not_found: str,
    audit_entity: Optional[str] = None,
    drive_entity_type: Optional[str] = None,
) -> APIRouter:
    """CRUD générique du pôle — ouvert à tout utilisateur authentifié.

    Diffère de ``business.make_crud_router`` : ici les écritures ne
    sont pas réservées aux managers (petit pôle interne partagé).

    ``audit_entity`` : si fourni, log les mutations dans audit_logs avec
    des actions ``{audit_entity}.created/updated/deleted``.

    ``drive_entity_type`` : si fourni (ex. ``"DevlogProject"``,
    ``"DevlogClient"``), invoque le hook Drive Conventions Phase 5
    après la création. Best-effort — un échec ne bloque jamais
    l'endpoint."""
    router = APIRouter(prefix=prefix, tags=["devlog"])

    @router.post(
        "", response_model=read_schema, status_code=status.HTTP_201_CREATED
    )
    async def create(data: create_schema, db: DBSession, user: CurrentUser):  # type: ignore[valid-type]
        obj = await GenericCrud(db, model).create(data)
        if audit_entity:
            await log_action(
                db,
                user=user,
                action=f"{audit_entity}.created",
                entity_type=audit_entity,
                entity_id=getattr(obj, "id", None),
                details=data.model_dump(exclude_unset=True),
            )
        # Phase 5 — hook Drive Conventions (best-effort, ne bloque pas).
        if drive_entity_type and getattr(obj, "id", None) is not None:
            try:
                from app.services.drive_conventions_hooks import (
                    on_entity_created,
                )

                await on_entity_created(
                    entity_type=drive_entity_type,
                    entity_id=obj.id,
                    user_id=user.id,
                    db=db,
                )
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).exception(
                    "drive hook 'created' a echoue pour %s #%s "
                    "(non bloquant)",
                    drive_entity_type,
                    obj.id,
                )
        return read_schema.model_validate(obj)

    @router.get("", response_model=List[read_schema])  # type: ignore[valid-type]
    async def list_items(
        db: DBSession,
        _: CurrentUser,
        skip: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=500),
    ):
        return list(await GenericCrud(db, model).list(skip=skip, limit=limit))

    @router.get("/{item_id}", response_model=read_schema)
    async def get_item(item_id: int, db: DBSession, _: CurrentUser):
        obj = await GenericCrud(db, model).get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        return read_schema.model_validate(obj)

    @router.patch("/{item_id}", response_model=read_schema)
    async def update_item(
        item_id: int, data: update_schema, db: DBSession, user: CurrentUser  # type: ignore[valid-type]
    ):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        obj = await crud.update(obj, data)
        if audit_entity:
            await log_action(
                db,
                user=user,
                action=f"{audit_entity}.updated",
                entity_type=audit_entity,
                entity_id=item_id,
                details=data.model_dump(exclude_unset=True),
            )
        return read_schema.model_validate(obj)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, db: DBSession, user: CurrentUser):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status_code=404, detail=not_found)
        await crud.delete(obj)
        if audit_entity:
            await log_action(
                db,
                user=user,
                action=f"{audit_entity}.deleted",
                entity_type=audit_entity,
                entity_id=item_id,
                details=None,
            )

    return router

# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

clients_router = APIRouter(prefix="/devlog/clients", tags=["devlog"])


@clients_router.post(
    "", response_model=DevlogClientRead, status_code=status.HTTP_201_CREATED
)
async def create_client(
    data: DevlogClientCreate, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.create(data)
    await log_action(
        db,
        user=user,
        action="devlog_client.created",
        entity_type="devlog_client",
        entity_id=obj.id,
        details={
            "name": getattr(obj, "name", None),
            "email": getattr(obj, "email", None),
            "company": getattr(obj, "company", None),
        },
    )

    # Phase 5 — hook Drive Conventions (best-effort).
    try:
        from app.services.drive_conventions_hooks import on_entity_created

        await on_entity_created(
            entity_type="DevlogClient",
            entity_id=obj.id,
            user_id=user.id,
            db=db,
        )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "drive hook 'created' a echoue pour DevlogClient #%s "
            "(non bloquant)",
            obj.id,
        )

    return DevlogClientRead.model_validate(obj)


@clients_router.get("", response_model=List[DevlogClientRead])
async def list_clients(
    db: DBSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
):
    crud = GenericCrud(db, DevlogClient)
    return list(await crud.list(skip=skip, limit=limit))


class _PickerOption(BaseModel):
    """Entrée unifiée prospect|client pour les selectors UI (création
    de soumission, etc.)."""

    value: str  # "prospect:{id}" | "client:{id}"
    type: str  # "lead" | "client"
    label: str
    sub: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    status: Optional[str] = None  # status du lead pour affichage
    lead_id: Optional[int] = None
    client_id: Optional[int] = None
    project_type: Optional[str] = None


@clients_router.get(
    "/picker-options",
    response_model=List[_PickerOption],
    summary=(
        "Liste unifiée des prospects + clients pour le selector du "
        "wizard de création de soumission"
    ),
)
async def list_picker_options(db: DBSession, _: CurrentUser):
    """Retourne la liste fusionnée des leads (prospects) ET clients du
    pôle, avec un type explicite pour distinguer les deux côté UI.

    Source de vérité pour les selectors qui doivent permettre de viser
    un prospect ou un client indifféremment (création de soumission,
    etc.). Évite le double fetch /leads + /clients qui pose problème
    quand l'une des routes répond en erreur."""
    # Charge tous les leads (peu importe le statut — on peut créer une
    # soumission pour un prospect refusé qu'on relance) et tous les
    # clients actifs.
    leads = (
        await db.execute(select(DevlogLead).order_by(DevlogLead.id.desc()))
    ).scalars().all()
    clients = (
        await db.execute(select(DevlogClient).order_by(DevlogClient.id.desc()))
    ).scalars().all()

    options: List[_PickerOption] = []
    # Leads (prospects) en tête : c'est typiquement ce qu'on veut
    # quand on crée une soumission pour la première fois.
    for lead in leads:
        # On laisse de côté les leads déjà convertis pour éviter le
        # double affichage (le client correspondant est aussi listé).
        if lead.client_id is not None:
            continue
        options.append(
            _PickerOption(
                value=f"prospect:{lead.id}",
                type="lead",
                label=lead.name,
                sub=lead.email or lead.company,
                email=lead.email,
                phone=lead.phone,
                address=lead.address,
                status=lead.status,
                lead_id=lead.id,
                project_type=lead.project_type,
            )
        )
    for client in clients:
        options.append(
            _PickerOption(
                value=f"client:{client.id}",
                type="client",
                label=client.name,
                sub=client.email or client.company,
                email=client.email,
                phone=client.phone,
                address=client.address,
                status=client.status,
                client_id=client.id,
            )
        )
    return options


@clients_router.get("/{client_id}", response_model=DevlogClientRead)
async def get_client(client_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return DevlogClientRead.model_validate(obj)


class _ClientKpis(BaseModel):
    """KPIs cumules d'un client — alimente le header de la fiche client
    "compte mature" (mai 2026). Montants en cents pour rester precis ; la
    UI divise par 100 pour l'affichage.

    Conventions :
      * ``total_invoiced_lifetime_cents`` : somme des totaux TTC des
        factures *non annulees* (status != 'annulee'). On reutilise le
        calcul officiel ``compute_invoice_totals`` quand des items
        existent, sinon on retombe sur ``invoice.amount`` (legacy /
        soumissions converties sans items detailles).
      * ``total_paid_lifetime_cents`` : meme calcul, restreint aux
        factures ``status == 'payee'``.
      * ``outstanding_cents`` : invoiced - paid (positif = reste a
        encaisser ; toujours >= 0 dans la pratique).
      * ``mrr_recurring_cents`` : somme du bloc recurring TTC des
        soumissions acceptees qui alimentent un projet *actif*
        (``en_cours`` ou ``livre``). Plusieurs projets actifs avec
        recurrent => cumul. Cle metier pour la sante du portefeuille.
    """

    active_projects_count: int = 0
    total_invoiced_lifetime_cents: int = 0
    total_paid_lifetime_cents: int = 0
    outstanding_cents: int = 0
    mrr_recurring_cents: int = 0


class _ClientFullHistory(BaseModel):
    """Vue fusionnee de la fiche client : ses propres infos + l'historique
    du prospect d'origine s'il y en a un. Source de verite pour
    /dev-logiciel/clients/[id] qui doit montrer tout — peu importe que
    les entites aient ete creees avant ou apres la conversion."""

    client: DevlogClientRead
    source_lead: Optional[DevlogLeadRead] = None
    kpis: _ClientKpis = Field(default_factory=_ClientKpis)
    soumissions: List[DevlogSoumissionRead] = Field(default_factory=list)
    projects: List[DevlogProjectRead] = Field(default_factory=list)
    contracts: List[DevlogContractRead] = Field(default_factory=list)
    invoices: List[DevlogInvoiceRead] = Field(default_factory=list)


@clients_router.get(
    "/{client_id}/full-history",
    response_model=_ClientFullHistory,
    summary=(
        "Vue unifiee prospect/client : infos du client + lead source + "
        "soumissions/projets/contrats/factures + KPIs cumules"
    ),
)
async def get_client_full_history(
    client_id: int, db: DBSession, _: CurrentUser
):
    """Retourne un payload unique avec toute l'histoire de la fiche
    client : ses infos, le prospect d'origine s'il y en a un, la fusion
    des soumissions/projets/contrats/factures lies au lead OU au client,
    et les KPIs cumules (projets actifs, facture/encaisse a vie, MRR).

    Phil : "quand un prospect devient client, c'est la meme fiche qui
    suit le contact bout-en-bout (notes, attachments, soumissions,
    projet conserves)". Ce endpoint evite que la fiche client n'ait
    pas l'historique du prospect d'origine.

    Vague "fiche client mature" (mai 2026) : ajout du bloc ``kpis``
    pour faire de cette page un *compte client* (header de cards,
    MRR, factures recentes) plutot qu'un simple miroir de la fiche
    prospect.
    """
    client = await GenericCrud(db, DevlogClient).get(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client introuvable")

    source_lead = None
    lead_id = getattr(client, "converted_from_lead_id", None)
    if lead_id is not None:
        source_lead = await GenericCrud(db, DevlogLead).get(lead_id)

    # Soumissions liees soit au client (priorite), soit a son prospect
    # source. La meme soumission peut avoir lead_id ET client_id remplis
    # apres signature — on deduplique sur l'id.
    soum_stmt = select(DevlogSoumission).where(
        DevlogSoumission.client_id == client_id
    )
    if lead_id is not None:
        soum_stmt = select(DevlogSoumission).where(
            (DevlogSoumission.client_id == client_id)
            | (DevlogSoumission.lead_id == lead_id)
        )
    soum_rows = (
        await db.execute(soum_stmt.order_by(DevlogSoumission.id.desc()))
    ).scalars().all()
    seen_ids: set[int] = set()
    soumissions: list[DevlogSoumission] = []
    for s in soum_rows:
        if s.id in seen_ids:
            continue
        seen_ids.add(s.id)
        soumissions.append(s)

    projects = (
        await db.execute(
            select(DevlogProject)
            .where(DevlogProject.client_id == client_id)
            .order_by(DevlogProject.id.desc())
        )
    ).scalars().all()

    contracts = (
        await db.execute(
            select(DevlogContract)
            .where(DevlogContract.client_id == client_id)
            .order_by(DevlogContract.id.desc())
        )
    ).scalars().all()

    invoices = (
        await db.execute(
            select(DevlogInvoice)
            .where(DevlogInvoice.client_id == client_id)
            .order_by(DevlogInvoice.id.desc())
        )
    ).scalars().all()

    kpis = await _compute_client_kpis(
        db,
        projects=list(projects),
        soumissions=list(soumissions),
        invoices=list(invoices),
    )

    return _ClientFullHistory(
        client=DevlogClientRead.model_validate(client),
        source_lead=(
            DevlogLeadRead.model_validate(source_lead)
            if source_lead is not None
            else None
        ),
        kpis=kpis,
        soumissions=[DevlogSoumissionRead.model_validate(s) for s in soumissions],
        projects=[DevlogProjectRead.model_validate(p) for p in projects],
        contracts=[DevlogContractRead.model_validate(c) for c in contracts],
        invoices=[DevlogInvoiceRead.model_validate(i) for i in invoices],
    )


# ---------- helpers KPIs (fiche client mature, mai 2026) ----------

_ACTIVE_PROJECT_STATUSES = ("en_cours", "livre")


async def _compute_client_kpis(
    db,
    *,
    projects: list[DevlogProject],
    soumissions: list[DevlogSoumission],
    invoices: list[DevlogInvoice],
) -> "_ClientKpis":
    """Calcule les KPIs cumules d'un client a partir de ses entites.

    * **MRR recurrent** : pour chaque projet actif (``en_cours`` ou
      ``livre``), on retrouve la soumission liee via
      ``project.soumission_id``. Si la soumission est en mode
      ``is_devis_dev`` (nouveau format), on charge ses items et on passe
      par ``compute_devis`` pour obtenir le ``total_client_amount_taxe``
      du bloc recurring. C'est la verite arithmetique cote client
      (taxes Qc incluses). Si la soumission n'a aucun item recurring,
      le bloc renvoie 0 et le projet ne contribue pas au MRR.
    * **Facture/Encaisse** : on totalise TTC. Quand des items existent
      on reutilise ``compute_invoice_totals`` (somme HT + TPS + TVQ).
      Sinon on retombe sur ``invoice.amount`` (compatibilite avec les
      factures importees / legacy sans items detailles).
    """
    active_projects = [
        p for p in projects if p.status in _ACTIVE_PROJECT_STATUSES
    ]

    # ---- MRR : on charge en bloc les items des soumissions actives ----
    mrr_total_cents = 0
    sub_by_id = {s.id: s for s in soumissions}
    soum_ids_for_mrr: set[int] = set()
    for p in active_projects:
        sid = getattr(p, "soumission_id", None)
        if sid is None:
            continue
        soum = sub_by_id.get(sid)
        # La soumission peut ne pas etre dans le bundle (rare : projet
        # raccroche a un devis d'un autre client) — on la skippe alors.
        if soum is None:
            continue
        # On ne calcule le MRR que pour les soumissions devis_dev avec un
        # statut "acceptee" (la signature implique l'engagement). Pour
        # le legacy (is_devis_dev=False), pas de notion de recurrent
        # structuree => skip plutot que d'inventer un montant.
        if not getattr(soum, "is_devis_dev", False):
            continue
        if soum.status != "acceptee":
            continue
        soum_ids_for_mrr.add(soum.id)

    if soum_ids_for_mrr:
        items_rows = (
            await db.execute(
                select(DevlogSoumissionItem).where(
                    DevlogSoumissionItem.soumission_id.in_(soum_ids_for_mrr)
                )
            )
        ).scalars().all()
        items_by_soum: dict[int, list[DevlogSoumissionItem]] = {}
        for it in items_rows:
            items_by_soum.setdefault(it.soumission_id, []).append(it)
        for sid in soum_ids_for_mrr:
            soum = sub_by_id[sid]
            preview = compute_devis(soum, items_by_soum.get(sid, []))
            recurring = preview.get("recurring", {}) or {}
            total_taxe = float(
                recurring.get("total_client_amount_taxe", 0) or 0
            )
            mrr_total_cents += int(round(total_taxe * 100))

    # ---- Facture / encaisse : on charge en bloc les items des factures
    # non-annulees, et on retombe sur invoice.amount sinon. -------------
    invoice_ids = [i.id for i in invoices if i.status != "annulee"]
    items_by_invoice: dict[int, list[DevlogInvoiceItem]] = {}
    if invoice_ids:
        inv_items = (
            await db.execute(
                select(DevlogInvoiceItem).where(
                    DevlogInvoiceItem.invoice_id.in_(invoice_ids)
                )
            )
        ).scalars().all()
        for it in inv_items:
            items_by_invoice.setdefault(it.invoice_id, []).append(it)

    invoiced_cents = 0
    paid_cents = 0
    for inv in invoices:
        if inv.status == "annulee":
            continue
        items_for_inv = items_by_invoice.get(inv.id, [])
        if items_for_inv:
            totals = compute_invoice_totals(items_for_inv)
            total_ttc = float(totals.get("total", 0) or 0)
        else:
            total_ttc = float(inv.amount or 0)
        cents = int(round(total_ttc * 100))
        invoiced_cents += cents
        if inv.status == "payee":
            paid_cents += cents

    outstanding_cents = max(0, invoiced_cents - paid_cents)

    return _ClientKpis(
        active_projects_count=len(active_projects),
        total_invoiced_lifetime_cents=invoiced_cents,
        total_paid_lifetime_cents=paid_cents,
        outstanding_cents=outstanding_cents,
        mrr_recurring_cents=mrr_total_cents,
    )


@clients_router.patch("/{client_id}", response_model=DevlogClientRead)
async def update_client(
    client_id: int,
    data: DevlogClientUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    obj = await crud.update(obj, data)
    await log_action(
        db,
        user=user,
        action="devlog_client.updated",
        entity_type="devlog_client",
        entity_id=client_id,
        details=data.model_dump(exclude_unset=True),
    )
    return DevlogClientRead.model_validate(obj)


@clients_router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(client_id: int, db: DBSession, user: CurrentUser):
    crud = GenericCrud(db, DevlogClient)
    obj = await crud.get(client_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Client introuvable")
    name = getattr(obj, "name", None)
    await crud.delete(obj)
    await log_action(
        db,
        user=user,
        action="devlog_client.deleted",
        entity_type="devlog_client",
        entity_id=client_id,
        details={"name": name},
    )


# --------------------------------------------------------------------------
# Leads (pipeline du closer)
# --------------------------------------------------------------------------

leads_router = APIRouter(prefix="/devlog/leads", tags=["devlog"])


@leads_router.post(
    "", response_model=DevlogLeadRead, status_code=status.HTTP_201_CREATED
)
async def create_lead(data: DevlogLeadCreate, db: DBSession, user: CurrentUser):
    if data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.create(data)
    await log_action(
        db,
        user=user,
        action="devlog_lead.created",
        entity_type="devlog_lead",
        entity_id=obj.id,
        details={
            "name": getattr(obj, "name", None),
            "email": getattr(obj, "email", None),
            "project_type": getattr(obj, "project_type", None),
            "source": getattr(obj, "source", None),
        },
    )
    return DevlogLeadRead.model_validate(obj)


@leads_router.get("", response_model=List[DevlogLeadRead])
async def list_leads(
    db: DBSession,
    _: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
):
    """Liste les leads, triés pour alimenter directement le kanban
    (par colonne de statut puis position)."""
    stmt = select(DevlogLead)
    if status_filter:
        stmt = stmt.where(DevlogLead.status == status_filter)
    stmt = stmt.order_by(DevlogLead.position.asc(), DevlogLead.id.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


@leads_router.get("/{lead_id}", response_model=DevlogLeadRead)
async def get_lead(lead_id: int, db: DBSession, _: CurrentUser):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return DevlogLeadRead.model_validate(obj)


@leads_router.patch("/{lead_id}", response_model=DevlogLeadRead)
async def update_lead(
    lead_id: int, data: DevlogLeadUpdate, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    if data.status is not None and data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    obj = await crud.update(obj, data)
    await log_action(
        db,
        user=user,
        action="devlog_lead.updated",
        entity_type="devlog_lead",
        entity_id=lead_id,
        details=data.model_dump(exclude_unset=True),
    )
    return DevlogLeadRead.model_validate(obj)


@leads_router.patch("/{lead_id}/status", response_model=DevlogLeadRead)
async def move_lead(
    lead_id: int,
    data: DevlogLeadStatusUpdate,
    db: DBSession,
    user: CurrentUser,
):
    """Déplace un lead dans le kanban (drag & drop entre colonnes)."""
    if data.status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail="Statut invalide")
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    from_status = obj.status
    obj.status = data.status
    if data.position is not None:
        obj.position = data.position
    await db.flush()
    await db.refresh(obj)
    await log_action(
        db,
        user=user,
        action="devlog_lead.status_changed",
        entity_type="devlog_lead",
        entity_id=lead_id,
        details={"from_status": from_status, "to_status": data.status},
    )
    return DevlogLeadRead.model_validate(obj)


@leads_router.post(
    "/{lead_id}/convert", response_model=DevlogClientRead
)
async def convert_lead_to_client(
    lead_id: int, db: DBSession, user: CurrentUser
):
    """Convertit un lead « gagné » en client du pôle. Idempotent :
    si le lead a déjà un client lié, on renvoie ce client.

    Logique centralisée dans ``app.services.devlog_client_provision``
    pour être réutilisée par les autres flows (auto-conversion à la
    création de soumission, à l'acceptation, etc.)."""
    client = await _convert_lead_to_client_service(
        db,
        lead_id,
        user=user,
        audit_action="devlog_lead.converted_to_client",
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    return DevlogClientRead.model_validate(client)


@leads_router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: int, db: DBSession, user: CurrentUser):
    crud = GenericCrud(db, DevlogLead)
    obj = await crud.get(lead_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    name = getattr(obj, "name", None)
    await crud.delete(obj)
    await log_action(
        db,
        user=user,
        action="devlog_lead.deleted",
        entity_type="devlog_lead",
        entity_id=lead_id,
        details={"name": name},
    )


# --------------------------------------------------------------------------
# Soumissions (devis)
# --------------------------------------------------------------------------

soumissions_router = _make_crud_router(
    prefix="/devlog/soumissions",
    model=DevlogSoumission,
    create_schema=DevlogSoumissionCreate,
    update_schema=DevlogSoumissionUpdate,
    read_schema=DevlogSoumissionRead,
    not_found="Soumission introuvable",
    audit_entity="devlog_soumission",
)


# --------------------------------------------------------------------------
# Automatisations soumission → client / projet
# --------------------------------------------------------------------------

soumission_automations_router = APIRouter(
    prefix="/devlog/soumissions", tags=["devlog"]
)


@soumission_automations_router.post(
    "",
    response_model=DevlogSoumissionRead,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Crée une soumission devlog. Si ``lead_id`` est fourni, la "
        "soumission reste liée au prospect — la conversion en client "
        "n'a lieu qu'à la signature publique de la soumission."
    ),
)
async def create_soumission_with_automations(
    data: DevlogSoumissionCreate, db: DBSession, user: CurrentUser
):
    """Override du POST générique : la création d'une soumission liée à
    un prospect garde le ``lead_id`` mais NE convertit PAS le prospect en
    client (revert PR #495 — la conversion se fait uniquement quand le
    client signe la soumission via la page publique).

    Validation : si ``lead_id`` est fourni on vérifie que le lead existe ;
    si ``client_id`` est fourni on vérifie le client. Pas de side-effect
    sur le statut du lead à ce stade.
    """
    payload = data.model_dump(exclude_unset=True)

    lead_id = payload.get("lead_id")
    client_id = payload.get("client_id")

    # Validation : le lead doit exister s'il est fourni (mais on ne le
    # convertit PAS — le statut reste tel quel jusqu'a la signature).
    if lead_id is not None:
        lead = await GenericCrud(db, DevlogLead).get(lead_id)
        if lead is None:
            raise HTTPException(
                status_code=404, detail="Lead introuvable"
            )

    # Validation : le client doit exister s'il est fourni.
    if client_id is not None:
        client = await GenericCrud(db, DevlogClient).get(client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="Client introuvable")

    obj = DevlogSoumission(**payload)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)

    await log_action(
        db,
        user=user,
        action="devlog_soumission.created",
        entity_type="devlog_soumission",
        entity_id=obj.id,
        details={
            "title": obj.title,
            "lead_id": obj.lead_id,
            "client_id": obj.client_id,
            "is_devis_dev": getattr(obj, "is_devis_dev", False),
        },
    )
    return DevlogSoumissionRead.model_validate(obj)


async def _ensure_client_for_soumission(
    db, soumission: DevlogSoumission, user=None
) -> Optional[DevlogClient]:
    """Si la soumission est rattachée à un lead sans client, convertit
    le lead en client via ``convert_lead_to_client`` (qui pose
    ``client.converted_from_lead_id`` + ``client.converted_at`` pour la
    fiche unifiee) et lie la soumission au client résultant. Idempotent.

    Appelee uniquement par les flows d'ACCEPTATION (signature publique,
    transition manuelle vers "acceptee", convert-to-project). PLUS appelee
    a la creation ni a l'envoi — Phil veut que la conversion arrive
    uniquement quand le client signe vraiment.

    Si ``user`` est fourni on log l'action ; notifie les managers /
    admins via notification interne best-effort.
    """
    if soumission.client_id is not None:
        return await GenericCrud(db, DevlogClient).get(soumission.client_id)
    if soumission.lead_id is None:
        return None

    # Conversion centralisee via le service (pose les liens bidirectionnels
    # prospect ↔ client, l'horodatage, le statut "won", l'audit log).
    client = await _convert_lead_to_client_service(
        db,
        soumission.lead_id,
        user=user,
        audit_action="devlog_client.auto_created_from_lead",
        audit_details_extra={"soumission_id": soumission.id},
    )
    if client is None:
        return None

    soumission.client_id = client.id
    await db.flush()

    # Notification best-effort aux managers / admins (Phil + Steven).
    # On n'échoue jamais la signature / l'acceptation si la notif rate.
    try:
        from app.services.notifications import notify_role

        await notify_role(
            db,
            min_role="manager",
            kind="devlog.client.auto_created",
            title=f"Nouveau client devlog : {client.name}",
            body=(
                f"Le prospect #{soumission.lead_id} a été converti "
                f"automatiquement en client suite à l'acceptation de la "
                f"soumission #{soumission.id}."
            ),
            href=f"/dev-logiciel/clients/{client.id}",
        )
    except Exception:
        pass

    return client


async def _provision_project_for_soumission(
    db, soumission: DevlogSoumission, user=None
) -> DevlogProject:
    """Crée le projet Dev logiciel rattaché à une soumission acceptée.
    Idempotent : si un projet existe déjà pour cette soumission, on le
    retourne tel quel."""
    existing = (
        await db.execute(
            select(DevlogProject).where(
                DevlogProject.soumission_id == soumission.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    client = await _ensure_client_for_soumission(db, soumission, user=user)
    project = DevlogProject(
        name=soumission.title,
        client_id=client.id if client else soumission.client_id,
        soumission_id=soumission.id,
        description=soumission.summary,
        status="planifie",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # Phase 5 — hook Drive Conventions sur la création auto d'un
    # projet depuis le passage en acceptee d'une soumission. Best-effort.
    if user is not None and getattr(user, "id", None) is not None:
        try:
            from app.services.drive_conventions_hooks import on_entity_created

            await on_entity_created(
                entity_type="DevlogProject",
                entity_id=project.id,
                user_id=user.id,
                db=db,
            )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "drive hook 'created' a echoue pour DevlogProject #%s "
                "(provision auto, non bloquant)",
                project.id,
            )

    return project


@soumission_automations_router.patch(
    "/{soumission_id}", response_model=DevlogSoumissionRead
)
async def update_soumission_with_automations(
    soumission_id: int,
    data: DevlogSoumissionUpdate,
    db: DBSession,
    user: CurrentUser,
):
    """Override de la mise à jour générique : si le statut passe à
    « acceptee », on provisionne automatiquement le projet (+ client
    si nécessaire) et on met à jour le lead lié.

    En mode « devis_dev », un changement de ``taux_dev_horaire`` se
    répercute aussi sur le total stocké de chaque item feature (la
    quantité × taux), pour que ``amount`` reste cohérent avec les
    listes / kanban sans repasser par compute_devis à chaque GET."""
    crud = GenericCrud(db, DevlogSoumission)
    obj = await crud.get(soumission_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    previous_status = obj.status
    update_data = data.model_dump(exclude_unset=True)
    devis_dev_fields_changed = any(
        f in update_data
        for f in (
            "taux_dev_horaire",
            "taux_manager_horaire",
            "heures_manager",
            "marge_recurrente_pct",
            "marge_initiale_pct",
            "commission_closer_pct",
            "is_devis_dev",
        )
    )
    obj = await crud.update(obj, data)
    if getattr(obj, "is_devis_dev", False) and devis_dev_fields_changed:
        # Re-calc des totaux items feature (heures × taux_dev).
        items = (
            await db.execute(
                select(DevlogSoumissionItem).where(
                    DevlogSoumissionItem.soumission_id == soumission_id
                )
            )
        ).scalars().all()
        for it in items:
            _apply_devis_dev_totals(it, obj)
        await db.flush()
        await _refresh_soumission_amount(db, soumission_id)
        await db.refresh(obj)
    if (
        obj.status == "acceptee"
        and previous_status != "acceptee"
    ):
        # Auto-flow closing : assure que le prospect lié devient client,
        # puis provisionne le projet (idempotent côté projet).
        await _ensure_client_for_soumission(db, obj, user=user)
        await _provision_project_for_soumission(db, obj, user=user)
    await log_action(
        db,
        user=user,
        action="devlog_soumission.updated",
        entity_type="devlog_soumission",
        entity_id=soumission_id,
        details=update_data,
    )
    return DevlogSoumissionRead.model_validate(obj)


_SOUMISSION_STATUS_TO_LEAD: dict[str, str] = {
    "envoyee": "quoted",
    "acceptee": "won",
    "refusee": "lost",
    "expiree": "lost",
}


class _SoumissionStatusBody(BaseModel):
    status: str = Field(..., max_length=16)


@soumission_automations_router.patch(
    "/{soumission_id}/status", response_model=DevlogSoumissionRead
)
async def update_soumission_status(
    soumission_id: int,
    body: _SoumissionStatusBody,
    db: DBSession,
    user: CurrentUser,
):
    """Change le statut de la soumission ET propage côté lead + crée
    le projet si on passe à « acceptee ». Endpoint utilisé par le
    kanban /dev-logiciel/soumissions."""
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    previous_status = soumission.status
    soumission.status = body.status
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_soumission.status_changed",
        entity_type="devlog_soumission",
        entity_id=soumission_id,
        details={"from_status": previous_status, "to_status": body.status},
    )

    # Propagation vers le lead (sauf si lead déjà en état terminal).
    if soumission.lead_id is not None:
        lead = await GenericCrud(db, DevlogLead).get(soumission.lead_id)
        if lead is not None:
            new_lead_status = _SOUMISSION_STATUS_TO_LEAD.get(body.status)
            if (
                new_lead_status is not None
                and lead.status not in ("won", "lost")
            ):
                lead.status = new_lead_status
                await db.flush()

    if (
        soumission.status == "acceptee"
        and previous_status != "acceptee"
    ):
        # Auto-flow closing : lead → client puis client → projet, sur
        # toute transition manuelle vers acceptee depuis le kanban.
        await _ensure_client_for_soumission(db, soumission, user=user)
        await _provision_project_for_soumission(db, soumission, user=user)

    await db.refresh(soumission)
    return DevlogSoumissionRead.model_validate(soumission)


@soumission_automations_router.get(
    "/{soumission_id}/devis-preview",
    response_model=DevisPreview,
    summary=(
        "Prévisualise les totaux du nouveau format devis_dev "
        "(calcul circulaire frais initiaux + frais mensuels)"
    ),
)
async def preview_soumission_devis(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    """Retourne la décomposition complète d'une soumission (vue
    propriétaire ET vue client). Le frontend appelle cet endpoint en
    debounced à chaque modification pour rafraîchir les totaux."""
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    items = (
        await db.execute(
            select(DevlogSoumissionItem)
            .where(DevlogSoumissionItem.soumission_id == soumission_id)
            .order_by(
                DevlogSoumissionItem.position.asc(),
                DevlogSoumissionItem.id.asc(),
            )
        )
    ).scalars().all()
    return compute_devis(soumission, list(items))


@soumission_automations_router.post(
    "/{soumission_id}/convert-to-project",
    response_model=DevlogProjectRead,
    summary="Crée le projet rattaché à une soumission acceptée",
)
async def convert_soumission_to_project(
    soumission_id: int, db: DBSession, user: CurrentUser
):
    """Conversion explicite (idempotente) : si la soumission n'est pas
    encore acceptée, on la passe à `acceptee` puis on provisionne le
    projet + client. Retourne le projet créé (ou existant)."""
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    previous_status = soumission.status
    if soumission.status != "acceptee":
        soumission.status = "acceptee"
        await db.flush()
    # Idempotent : si déjà acceptee, _ensure_client_for_soumission ne
    # recrée rien (court-circuit sur client_id déjà présent).
    if previous_status != "acceptee":
        await _ensure_client_for_soumission(db, soumission, user=user)
    project = await _provision_project_for_soumission(
        db, soumission, user=user
    )
    await log_action(
        db,
        user=user,
        action="devlog_soumission.converted_to_project",
        entity_type="devlog_soumission",
        entity_id=soumission_id,
        details={"project_id": project.id},
    )
    return DevlogProjectRead.model_validate(project)


# --------------------------------------------------------------------------
# Envoi PDF + signature publique (vague 1, mai 2026)
# --------------------------------------------------------------------------


class _SendResult(BaseModel):
    success: bool
    sent_at: Optional[str] = None
    signature_token: Optional[str] = None


@soumission_automations_router.post(
    "/{soumission_id}/send",
    response_model=_SendResult,
    summary=(
        "Envoie la soumission devis_dev au client (PDF + email + "
        "génération du token de signature publique)"
    ),
)
async def send_soumission(
    soumission_id: int, db: DBSession, user: CurrentUser
):
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    if not getattr(soumission, "is_devis_dev", False):
        raise HTTPException(
            status_code=400,
            detail=(
                "Les soumissions au format legacy ne peuvent pas être "
                "envoyées par ce flow. Utilise une soumission « devis_dev »."
            ),
        )
    # Note (mai 2026) : avant on convertissait le lead en client ici via
    # _ensure_client_for_soumission. Phil veut que la conversion arrive
    # UNIQUEMENT a la signature publique. ``send_devis_email`` charge
    # maintenant directement le destinataire (client ou lead) — la
    # soumission peut etre envoyee a un prospect sans creer de client.
    if soumission.client_id is None and soumission.lead_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "La soumission n'est rattachée à aucun client ni à aucun "
                "prospect — impossible d'envoyer. Lie un destinataire à "
                "la soumission, puis réessaie."
            ),
        )
    try:
        soumission = await send_devis_email(db, soumission_id)
    except DevlogSoumissionSendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db,
        user=user,
        action="devlog_soumission.sent",
        entity_type="devlog_soumission",
        entity_id=soumission_id,
        details={
            "signature_token": soumission.signature_token,
            "total": float(soumission.amount or 0),
            "client_id": soumission.client_id,
        },
    )
    return _SendResult(
        success=True,
        sent_at=(
            soumission.sent_at.isoformat()
            if soumission.sent_at
            else None
        ),
        signature_token=soumission.signature_token,
    )


@soumission_automations_router.get(
    "/{soumission_id}/pdf",
    summary="PDF de la soumission devis_dev (vue client uniquement)",
)
async def get_soumission_pdf(
    soumission_id: int, db: DBSession, user: CurrentUser
):
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    if not getattr(soumission, "is_devis_dev", False):
        raise HTTPException(
            status_code=400,
            detail=(
                "Les soumissions au format legacy n'ont pas de PDF "
                "généré. Utilise une soumission « devis_dev »."
            ),
        )
    pdf_bytes = await generate_devis_pdf(db, soumission_id)
    filename = f"soumission-devlog-{soumission_id}.pdf"

    # Phase 6 — auto-classement Drive (best-effort, NON bloquant). Dépose
    # la soumission PDF dans le sous-dossier « Soumissions » du client lié,
    # si une règle est active. N'altère jamais la réponse.
    try:
        from app.services.drive_auto_upload_dispatcher import (
            dispatch_auto_upload,
        )

        await dispatch_auto_upload(
            "soumission_pdf",
            "DevlogClient",
            soumission.client_id,
            user.id,
            pdf_bytes,
            db,
            {"numero": getattr(soumission, "number", None) or soumission_id},
            mime_type="application/pdf",
        )
        await db.commit()
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).exception(
            "Auto-upload Drive soumission PDF non bloquant"
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


@soumission_automations_router.get(
    "/{soumission_id}/signed-pdf",
    summary=(
        "PDF *signé* de la soumission — gelé à la signature publique, "
        "contient le bandeau « SIGNÉE ÉLECTRONIQUEMENT » + IP + "
        "horodatage. Réservé aux soumissions effectivement signées."
    ),
)
async def get_soumission_signed_pdf(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    if not getattr(soumission, "is_devis_dev", False):
        raise HTTPException(
            status_code=400,
            detail=(
                "Les soumissions au format legacy n'ont pas de PDF "
                "signé. Utilise une soumission « devis_dev »."
            ),
        )
    if soumission.signed_at is None:
        raise HTTPException(
            status_code=404,
            detail="Cette soumission n'a pas encore été signée.",
        )
    # Fallback : si le blob est absent (signature antérieure à la mise
    # en place de cette fonctionnalité), on génère le PDF signé à la
    # volée et on le persiste pour les prochains accès.
    pdf_bytes = soumission.signed_pdf_blob
    if not pdf_bytes:
        try:
            from app.services.devlog_soumission_pdf import (
                generate_signed_pdf as _gen_signed,
            )
            pdf_bytes = await _gen_signed(db, soumission_id)
            soumission.signed_pdf_blob = pdf_bytes
            await db.flush()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Régénération PDF signé impossible : {exc}",
            ) from exc
    filename = f"soumission-{soumission_id}-signee.pdf"
    return Response(
        content=bytes(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


# --------------------------------------------------------------------------
# Projets de développement
# --------------------------------------------------------------------------

projects_router = _make_crud_router(
    prefix="/devlog/projects",
    model=DevlogProject,
    create_schema=DevlogProjectCreate,
    update_schema=DevlogProjectUpdate,
    read_schema=DevlogProjectRead,
    not_found="Projet introuvable",
    audit_entity="devlog_project",
    drive_entity_type="DevlogProject",
)


# --------------------------------------------------------------------------
# Saisie d'heures
# --------------------------------------------------------------------------

time_entries_router = _make_crud_router(
    prefix="/devlog/time-entries",
    model=DevlogTimeEntry,
    create_schema=DevlogTimeEntryCreate,
    update_schema=DevlogTimeEntryUpdate,
    read_schema=DevlogTimeEntryRead,
    not_found="Saisie d'heures introuvable",
    audit_entity="devlog_time_entry",
)


# --------------------------------------------------------------------------
# Facturation
# --------------------------------------------------------------------------

invoices_router = _make_crud_router(
    prefix="/devlog/invoices",
    model=DevlogInvoice,
    create_schema=DevlogInvoiceCreate,
    update_schema=DevlogInvoiceUpdate,
    read_schema=DevlogInvoiceRead,
    not_found="Facture introuvable",
    audit_entity="devlog_invoice",
)


# --------------------------------------------------------------------------
# Envoi PDF + page publique de consultation (pièce #5, vague 1, mai 2026)
# --------------------------------------------------------------------------

# Router dédié aux automations sur factures, registered AVANT
# `invoices_router` côté router.py pour que /devlog/invoices/{id}/send
# matche avant le PATCH générique de la CRUD.
invoice_automations_router = APIRouter(prefix="/devlog/invoices", tags=["devlog"])


def _public_base_url() -> str:
    import os as _os

    return (
        _os.getenv("PUBLIC_SITE_URL") or "https://immohorizon.com"
    ).rstrip("/")


class _InvoiceSendResult(BaseModel):
    success: bool
    sent_at: Optional[str] = None
    signature_token: Optional[str] = None
    public_url: Optional[str] = None


@invoice_automations_router.post(
    "/{invoice_id}/send",
    response_model=_InvoiceSendResult,
    summary=(
        "Envoie la facture au client (PDF + email + génération du token "
        "de consultation publique)"
    ),
)
async def send_invoice(
    invoice_id: int, db: DBSession, user: CurrentUser
):
    invoice = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    if invoice.status == "payee":
        raise HTTPException(
            status_code=400,
            detail="Facture déjà payée — envoi inutile.",
        )
    if invoice.status == "annulee":
        raise HTTPException(
            status_code=400,
            detail="Facture annulée — envoi impossible.",
        )
    try:
        invoice = await send_invoice_email(db, invoice_id)
    except DevlogInvoiceSendError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_action(
        db,
        user=user,
        action="devlog_invoice.sent",
        entity_type="devlog_invoice",
        entity_id=invoice_id,
        details={
            "number": invoice.number,
            "total": float(invoice.amount or 0),
            "client_id": invoice.client_id,
            "signature_token": invoice.signature_token,
        },
    )
    return _InvoiceSendResult(
        success=True,
        sent_at=(
            invoice.sent_at.isoformat()
            if invoice.sent_at
            else None
        ),
        signature_token=invoice.signature_token,
        public_url=(
            f"{_public_base_url()}/devlog/pay-invoice/{invoice.signature_token}"
            if invoice.signature_token
            else None
        ),
    )


@invoice_automations_router.get(
    "/{invoice_id}/pdf",
    summary="PDF de la facture (vue client)",
)
async def get_invoice_pdf(
    invoice_id: int, db: DBSession, user: CurrentUser
):
    invoice = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    pdf_bytes = await generate_invoice_pdf(db, invoice_id)
    label = invoice.number or f"facture-{invoice_id}"

    # Phase 6 — auto-classement Drive (best-effort, NON bloquant). Dépose
    # la facture PDF dans le sous-dossier « Factures » du client lié, si
    # une règle est active. N'altère jamais la réponse.
    try:
        from app.services.drive_auto_upload_dispatcher import (
            dispatch_auto_upload,
        )

        await dispatch_auto_upload(
            "facture_pdf",
            "DevlogClient",
            invoice.client_id,
            user.id,
            pdf_bytes,
            db,
            {"numero": invoice.number or invoice_id},
            mime_type="application/pdf",
        )
        await db.commit()
    except Exception:
        import logging as _logging

        _logging.getLogger(__name__).exception(
            "Auto-upload Drive facture PDF non bloquant"
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{label}.pdf"',
        },
    )


@invoice_automations_router.post(
    "/{invoice_id}/mark-paid",
    response_model=DevlogInvoiceRead,
    summary="Marquer la facture comme payée (workflow manuel)",
)
async def mark_invoice_paid(
    invoice_id: int, db: DBSession, user: CurrentUser
):
    from datetime import datetime as _dt, timezone as _tz

    invoice = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    if invoice.status == "annulee":
        raise HTTPException(
            status_code=400,
            detail="Facture annulée — impossible de la marquer payée.",
        )
    invoice.status = "payee"
    invoice.paid_at = _dt.now(_tz.utc)
    await db.flush()
    await db.refresh(invoice)
    await log_action(
        db,
        user=user,
        action="devlog_invoice.paid",
        entity_type="devlog_invoice",
        entity_id=invoice_id,
        details={
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "total": float(invoice.amount or 0),
            "number": invoice.number,
        },
    )
    return DevlogInvoiceRead.model_validate(invoice)


# --------------------------------------------------------------------------
# Sous-traitants
# --------------------------------------------------------------------------

sous_traitants_router = _make_crud_router(
    prefix="/devlog/sous-traitants",
    model=DevlogSousTraitant,
    create_schema=DevlogSousTraitantCreate,
    update_schema=DevlogSousTraitantUpdate,
    read_schema=DevlogSousTraitantRead,
    not_found="Sous-traitant introuvable",
    audit_entity="devlog_sous_traitant",
)


# --------------------------------------------------------------------------
# Items de facture + import depuis projet
# --------------------------------------------------------------------------

invoice_items_router = APIRouter(prefix="/devlog", tags=["devlog"])


async def _refresh_invoice_amount(db, invoice_id: int) -> None:
    items = (
        await db.execute(
            select(DevlogInvoiceItem).where(
                DevlogInvoiceItem.invoice_id == invoice_id
            )
        )
    ).scalars().all()
    total = round(sum(float(it.total or 0) for it in items), 2)
    inv = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if inv is not None:
        inv.amount = total
        await db.flush()


@invoice_items_router.get(
    "/invoices/{invoice_id}/items",
    response_model=List[DevlogInvoiceItemRead],
)
async def list_invoice_items(
    invoice_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoiceItem)
            .where(DevlogInvoiceItem.invoice_id == invoice_id)
            .order_by(DevlogInvoiceItem.position.asc(), DevlogInvoiceItem.id.asc())
        )
    ).scalars().all()
    return list(rows)


@invoice_items_router.post(
    "/invoice-items",
    response_model=DevlogInvoiceItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice_item(
    data: DevlogInvoiceItemCreate, db: DBSession, user: CurrentUser
):
    if await GenericCrud(db, DevlogInvoice).get(data.invoice_id) is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    payload = data.model_dump(exclude_unset=True)
    payload["total"] = _compute_item_total(data.quantity, data.unit_price)
    obj = DevlogInvoiceItem(**payload)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await _refresh_invoice_amount(db, data.invoice_id)
    await log_action(
        db,
        user=user,
        action="devlog_invoice_item.created",
        entity_type="devlog_invoice_item",
        entity_id=obj.id,
        details={
            "invoice_id": data.invoice_id,
            "description": getattr(obj, "description", None),
            "total": float(obj.total or 0),
        },
    )
    return DevlogInvoiceItemRead.model_validate(obj)


@invoice_items_router.patch(
    "/invoice-items/{item_id}",
    response_model=DevlogInvoiceItemRead,
)
async def update_invoice_item(
    item_id: int,
    data: DevlogInvoiceItemUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogInvoiceItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(obj, field, value)
    obj.total = _compute_item_total(obj.quantity, obj.unit_price)
    await db.flush()
    await db.refresh(obj)
    await _refresh_invoice_amount(db, obj.invoice_id)
    await log_action(
        db,
        user=user,
        action="devlog_invoice_item.updated",
        entity_type="devlog_invoice_item",
        entity_id=item_id,
        details=update_data,
    )
    return DevlogInvoiceItemRead.model_validate(obj)


@invoice_items_router.delete(
    "/invoice-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_invoice_item(
    item_id: int, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogInvoiceItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    invoice_id = obj.invoice_id
    await crud.delete(obj)
    await _refresh_invoice_amount(db, invoice_id)
    await log_action(
        db,
        user=user,
        action="devlog_invoice_item.deleted",
        entity_type="devlog_invoice_item",
        entity_id=item_id,
        details={"invoice_id": invoice_id},
    )


@invoice_items_router.post(
    "/invoices/{invoice_id}/import-sources",
    response_model=DevlogInvoiceImportResult,
)
async def import_into_invoice(
    invoice_id: int,
    data: DevlogInvoiceImportRequest,
    db: DBSession,
    user: CurrentUser,
):
    """Ajoute des lignes à la facture en important depuis un projet :
    heures totales + (optionnel) items de la soumission acceptée. Pas
    de markup automatique pour l'instant — le `hourly_rate` du body
    est le tarif facturable que l'admin choisit pour ce batch."""
    inv = await GenericCrud(db, DevlogInvoice).get(invoice_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    existing = (
        await db.execute(
            select(DevlogInvoiceItem.position).where(
                DevlogInvoiceItem.invoice_id == invoice_id
            )
        )
    ).scalars().all()
    next_pos = (max(existing) + 1) if existing else 0
    added = 0

    if data.include_hours:
        rows = (
            await db.execute(
                select(DevlogTimeEntry).where(
                    DevlogTimeEntry.project_id == data.project_id
                )
            )
        ).scalars().all()
        total_hours = round(sum(float(r.hours or 0) for r in rows), 2)
        if total_hours > 0:
            rate = float(data.hourly_rate or 0)
            db.add(
                DevlogInvoiceItem(
                    invoice_id=invoice_id,
                    position=next_pos,
                    description=f"Heures du projet #{data.project_id}",
                    unit="h",
                    quantity=total_hours,
                    unit_price=rate,
                    total=round(total_hours * rate, 2),
                    source_kind="heures",
                )
            )
            next_pos += 1
            added += 1

    if data.include_soumission and data.soumission_id:
        items = (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == data.soumission_id)
                .order_by(DevlogSoumissionItem.position.asc())
            )
        ).scalars().all()
        for it in items:
            db.add(
                DevlogInvoiceItem(
                    invoice_id=invoice_id,
                    position=next_pos,
                    description=it.description,
                    unit=it.unit,
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    total=it.total,
                    source_kind="soumission",
                )
            )
            next_pos += 1
            added += 1

    await db.flush()
    await _refresh_invoice_amount(db, invoice_id)
    await log_action(
        db,
        user=user,
        action="devlog_invoice.items_imported",
        entity_type="devlog_invoice",
        entity_id=invoice_id,
        details={
            "nb_items_added": added,
            "project_id": data.project_id,
            "soumission_id": data.soumission_id,
        },
    )
    return DevlogInvoiceImportResult(added=added)


# --------------------------------------------------------------------------
# Items de soumission (lignes)
# --------------------------------------------------------------------------

soumission_items_router = APIRouter(prefix="/devlog", tags=["devlog"])


def _compute_item_total(quantity: float, unit_price: float) -> float:
    return round(float(quantity or 0) * float(unit_price or 0), 2)


def _apply_markup(cost: float, markup_percent: Optional[float]) -> float:
    """Calcule le prix unitaire client à partir du coût et du markup
    de la section (en %). Markup NULL ou 0 → prix = coût."""
    m = float(markup_percent or 0)
    return round(float(cost or 0) * (1 + m / 100.0), 2)


async def _section_markup(db, section_id: Optional[int]) -> Optional[float]:
    if section_id is None:
        return None
    section = await GenericCrud(db, DevlogSoumissionSection).get(section_id)
    return float(section.markup_percent or 0) if section else None


async def _refresh_section_items(db, section_id: int) -> None:
    """Recalcule unit_price et total de tous les items d'une section
    quand le markup_percent change."""
    section = await GenericCrud(db, DevlogSoumissionSection).get(section_id)
    if section is None:
        return
    markup = float(section.markup_percent or 0)
    items = (
        await db.execute(
            select(DevlogSoumissionItem).where(
                DevlogSoumissionItem.section_id == section_id
            )
        )
    ).scalars().all()
    for it in items:
        it.unit_price = _apply_markup(it.cost_per_unit, markup)
        it.total = _compute_item_total(it.quantity, it.unit_price)
    await db.flush()


async def _refresh_soumission_amount(db, soumission_id: int) -> None:
    """Recalcule `DevlogSoumission.amount` à partir de ses items
    `initial` (frais one-shot). Le total mensuel est exposé séparément
    côté API quand demandé — `amount` reste le « prix de soumission »
    one-shot pour rester compatible avec les listes / kanbans existants.

    Pour les soumissions « devis_dev » (refonte mai 2026), on
    s'appuie sur ``compute_devis`` qui résout la formule circulaire :
    ``amount`` = total final de la mise en oeuvre (frais one-shot
    affichés au client)."""
    soumission = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soumission is None:
        return

    if getattr(soumission, "is_devis_dev", False):
        items = (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(DevlogSoumissionItem.soumission_id == soumission_id)
            )
        ).scalars().all()
        devis = compute_devis(soumission, list(items))
        soumission.amount = float(devis["initial"]["total_final"])
        await db.flush()
        return

    items = (
        await db.execute(
            select(DevlogSoumissionItem)
            .outerjoin(
                DevlogSoumissionSection,
                DevlogSoumissionItem.section_id == DevlogSoumissionSection.id,
            )
            .where(DevlogSoumissionItem.soumission_id == soumission_id)
            .where(
                (DevlogSoumissionSection.billing_kind == "initial")
                | (DevlogSoumissionItem.section_id.is_(None))
            )
        )
    ).scalars().all()
    total = round(sum(float(it.total or 0) for it in items), 2)
    soumission.amount = total
    await db.flush()


@soumission_items_router.get(
    "/soumissions/{soumission_id}/items",
    response_model=List[DevlogSoumissionItemRead],
)
async def list_soumission_items(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumissionItem)
            .where(DevlogSoumissionItem.soumission_id == soumission_id)
            .order_by(DevlogSoumissionItem.position.asc(), DevlogSoumissionItem.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _apply_devis_dev_totals(
    obj: DevlogSoumissionItem, soumission: DevlogSoumission
) -> None:
    """Pour les items « devis_dev », recalcule ``total`` selon le
    ``item_kind``. Pas de markup côté item — la marge est appliquée
    par ``compute_devis`` au niveau de la soumission."""
    kind = (obj.item_kind or "feature").strip()
    if kind == "feature":
        taux = float(soumission.taux_dev_horaire or 0)
        heures = float(obj.heures or 0)
        obj.quantity = heures
        obj.unit = obj.unit or "h"
        obj.cost_per_unit = taux
        obj.unit_price = taux
        obj.total = round(heures * taux, 2)
    elif kind == "recurring_cost":
        cost = float(obj.cost_per_unit or 0)
        obj.quantity = 1
        obj.unit = obj.unit or "mois"
        obj.unit_price = cost
        obj.total = round(cost, 2)
    elif kind == "fixed_cost":
        cost = float(obj.cost_per_unit or 0)
        obj.quantity = 1
        obj.unit = obj.unit or "forfait"
        obj.unit_price = cost
        obj.total = round(cost, 2)


@soumission_items_router.post(
    "/soumission-items",
    response_model=DevlogSoumissionItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_soumission_item(
    data: DevlogSoumissionItemCreate, db: DBSession, user: CurrentUser
):
    soumission = await GenericCrud(db, DevlogSoumission).get(data.soumission_id)
    if soumission is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    payload = data.model_dump(exclude_unset=True)

    if getattr(soumission, "is_devis_dev", False):
        # Mode devis_dev : pas de markup section, totaux dérivés du
        # type d'item via ``_apply_devis_dev_totals``.
        if "item_kind" not in payload or not payload["item_kind"]:
            payload["item_kind"] = "feature"
        payload.pop("section_id", None)
        obj = DevlogSoumissionItem(**payload)
        _apply_devis_dev_totals(obj, soumission)
    else:
        # Si l'item appartient à une section, le markup s'applique sur
        # cost_per_unit pour calculer unit_price. Sinon (item legacy sans
        # section), unit_price = celui fourni.
        markup = await _section_markup(db, data.section_id)
        if markup is not None and (data.cost_per_unit or 0) > 0:
            payload["unit_price"] = _apply_markup(data.cost_per_unit, markup)
        payload["total"] = _compute_item_total(
            data.quantity, payload.get("unit_price", data.unit_price)
        )
        obj = DevlogSoumissionItem(**payload)

    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await _refresh_soumission_amount(db, data.soumission_id)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_item.created",
        entity_type="devlog_soumission_item",
        entity_id=obj.id,
        details={
            "soumission_id": data.soumission_id,
            "description": getattr(obj, "description", None),
            "total": float(obj.total or 0),
        },
    )
    return DevlogSoumissionItemRead.model_validate(obj)


@soumission_items_router.patch(
    "/soumission-items/{item_id}",
    response_model=DevlogSoumissionItemRead,
)
async def update_soumission_item(
    item_id: int,
    data: DevlogSoumissionItemUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogSoumissionItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(obj, field, value)

    soumission = await GenericCrud(db, DevlogSoumission).get(obj.soumission_id)
    if soumission is not None and getattr(soumission, "is_devis_dev", False):
        _apply_devis_dev_totals(obj, soumission)
    else:
        # Si l'item est dans une section et que le coût a été modifié,
        # re-applique le markup de la section.
        if obj.section_id is not None:
            markup = await _section_markup(db, obj.section_id)
            if markup is not None and obj.cost_per_unit > 0:
                obj.unit_price = _apply_markup(obj.cost_per_unit, markup)
        obj.total = _compute_item_total(obj.quantity, obj.unit_price)
    await db.flush()
    await db.refresh(obj)
    await _refresh_soumission_amount(db, obj.soumission_id)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_item.updated",
        entity_type="devlog_soumission_item",
        entity_id=item_id,
        details=update_data,
    )
    return DevlogSoumissionItemRead.model_validate(obj)


@soumission_items_router.delete(
    "/soumission-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_soumission_item(
    item_id: int, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogSoumissionItem)
    obj = await crud.get(item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Item introuvable")
    soumission_id = obj.soumission_id
    await crud.delete(obj)
    await _refresh_soumission_amount(db, soumission_id)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_item.deleted",
        entity_type="devlog_soumission_item",
        entity_id=item_id,
        details={"soumission_id": soumission_id},
    )


# --------------------------------------------------------------------------
# Sections de soumission (pôles)
# --------------------------------------------------------------------------

soumission_sections_router = APIRouter(prefix="/devlog", tags=["devlog"])


@soumission_sections_router.get(
    "/soumissions/{soumission_id}/sections",
    response_model=List[DevlogSoumissionSectionRead],
)
async def list_sections(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumissionSection)
            .where(DevlogSoumissionSection.soumission_id == soumission_id)
            .order_by(
                DevlogSoumissionSection.position.asc(),
                DevlogSoumissionSection.id.asc(),
            )
        )
    ).scalars().all()
    return list(rows)


@soumission_sections_router.post(
    "/soumission-sections",
    response_model=DevlogSoumissionSectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    data: DevlogSoumissionSectionCreate, db: DBSession, user: CurrentUser
):
    if await GenericCrud(db, DevlogSoumission).get(data.soumission_id) is None:
        raise HTTPException(status_code=404, detail="Soumission introuvable")
    obj = await GenericCrud(db, DevlogSoumissionSection).create(data)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_section.created",
        entity_type="devlog_soumission_section",
        entity_id=obj.id,
        details={
            "soumission_id": data.soumission_id,
            "name": getattr(obj, "name", None),
        },
    )
    return DevlogSoumissionSectionRead.model_validate(obj)


@soumission_sections_router.patch(
    "/soumission-sections/{section_id}",
    response_model=DevlogSoumissionSectionRead,
)
async def update_section(
    section_id: int,
    data: DevlogSoumissionSectionUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogSoumissionSection)
    obj = await crud.get(section_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Section introuvable")
    markup_changed = (
        data.markup_percent is not None
        and float(data.markup_percent or 0)
        != float(obj.markup_percent or 0)
    )
    obj = await crud.update(obj, data)
    # Si le markup a changé, recalcule tous les items de la section
    # (unit_price et total) et le total de la soumission.
    if markup_changed:
        await _refresh_section_items(db, section_id)
        await _refresh_soumission_amount(db, obj.soumission_id)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_section.updated",
        entity_type="devlog_soumission_section",
        entity_id=section_id,
        details=data.model_dump(exclude_unset=True),
    )
    return DevlogSoumissionSectionRead.model_validate(obj)


@soumission_sections_router.delete(
    "/soumission-sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_section(
    section_id: int, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogSoumissionSection)
    obj = await crud.get(section_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Section introuvable")
    soumission_id = obj.soumission_id
    # Les items de la section sont détachés (section_id → NULL) via le
    # ON DELETE SET NULL du modèle.
    await crud.delete(obj)
    await _refresh_soumission_amount(db, soumission_id)
    await log_action(
        db,
        user=user,
        action="devlog_soumission_section.deleted",
        entity_type="devlog_soumission_section",
        entity_id=section_id,
        details={"soumission_id": soumission_id},
    )


@soumission_sections_router.get(
    "/soumissions/{soumission_id}/totals",
    summary="Totaux séparés frais initiaux vs mensuels",
)
async def get_soumission_totals(
    soumission_id: int, db: DBSession, _: CurrentUser
):
    """Retourne `{ initial: total_one_shot, monthly: total_mensuel }`
    pour afficher les deux totaux côté UI."""
    rows = (
        await db.execute(
            select(
                DevlogSoumissionItem.total,
                DevlogSoumissionSection.billing_kind,
            )
            .outerjoin(
                DevlogSoumissionSection,
                DevlogSoumissionItem.section_id
                == DevlogSoumissionSection.id,
            )
            .where(DevlogSoumissionItem.soumission_id == soumission_id)
        )
    ).all()
    initial = 0.0
    monthly = 0.0
    for total, kind in rows:
        t = float(total or 0)
        if kind == "recurring":
            monthly += t
        else:
            initial += t
    return {"initial": round(initial, 2), "monthly": round(monthly, 2)}


# --------------------------------------------------------------------------
# Vues « liées » — éléments rattachés à un lead / client / projet
# --------------------------------------------------------------------------

related_router = APIRouter(prefix="/devlog", tags=["devlog"])


@related_router.get(
    "/leads/{lead_id}/soumissions",
    response_model=List[DevlogSoumissionRead],
)
async def list_lead_soumissions(
    lead_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumission)
            .where(DevlogSoumission.lead_id == lead_id)
            .order_by(DevlogSoumission.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/soumissions",
    response_model=List[DevlogSoumissionRead],
)
async def list_client_soumissions(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogSoumission)
            .where(DevlogSoumission.client_id == client_id)
            .order_by(DevlogSoumission.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/projects",
    response_model=List[DevlogProjectRead],
)
async def list_client_projects(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogProject)
            .where(DevlogProject.client_id == client_id)
            .order_by(DevlogProject.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/clients/{client_id}/invoices",
    response_model=List[DevlogInvoiceRead],
)
async def list_client_invoices(
    client_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoice)
            .where(DevlogInvoice.client_id == client_id)
            .order_by(DevlogInvoice.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/projects/{project_id}/invoices",
    response_model=List[DevlogInvoiceRead],
)
async def list_project_invoices(
    project_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogInvoice)
            .where(DevlogInvoice.project_id == project_id)
            .order_by(DevlogInvoice.id.desc())
        )
    ).scalars().all()
    return list(rows)


@related_router.get(
    "/projects/{project_id}/time-entries",
    response_model=List[DevlogTimeEntryRead],
)
async def list_project_time_entries(
    project_id: int, db: DBSession, _: CurrentUser
):
    rows = (
        await db.execute(
            select(DevlogTimeEntry)
            .where(DevlogTimeEntry.project_id == project_id)
            .order_by(DevlogTimeEntry.work_date.desc(), DevlogTimeEntry.id.desc())
        )
    ).scalars().all()
    return list(rows)


# --------------------------------------------------------------------------
# Besoins client (par pôle) + génération de plan IA + → soumission
# --------------------------------------------------------------------------

lead_needs_router = APIRouter(prefix="/devlog", tags=["devlog"])


@lead_needs_router.get(
    "/leads/{lead_id}/needs",
    response_model=List[DevlogLeadNeedRead],
)
async def list_lead_needs(lead_id: int, db: DBSession, _: CurrentUser):
    rows = (
        await db.execute(
            select(DevlogLeadNeed)
            .where(DevlogLeadNeed.lead_id == lead_id)
            .order_by(DevlogLeadNeed.position.asc(), DevlogLeadNeed.id.asc())
        )
    ).scalars().all()
    return list(rows)


@lead_needs_router.post(
    "/lead-needs",
    response_model=DevlogLeadNeedRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_lead_need(
    data: DevlogLeadNeedCreate, db: DBSession, user: CurrentUser
):
    if await GenericCrud(db, DevlogLead).get(data.lead_id) is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    obj = await GenericCrud(db, DevlogLeadNeed).create(data)
    await log_action(
        db,
        user=user,
        action="devlog_lead_need.created",
        entity_type="devlog_lead_need",
        entity_id=obj.id,
        details={
            "lead_id": data.lead_id,
            "label": getattr(obj, "label", None),
            "pole": getattr(obj, "pole", None),
        },
    )
    return DevlogLeadNeedRead.model_validate(obj)


@lead_needs_router.patch(
    "/lead-needs/{need_id}",
    response_model=DevlogLeadNeedRead,
)
async def update_lead_need(
    need_id: int,
    data: DevlogLeadNeedUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogLeadNeed)
    obj = await crud.get(need_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Besoin introuvable")
    obj = await crud.update(obj, data)
    await log_action(
        db,
        user=user,
        action="devlog_lead_need.updated",
        entity_type="devlog_lead_need",
        entity_id=need_id,
        details=data.model_dump(exclude_unset=True),
    )
    return DevlogLeadNeedRead.model_validate(obj)


@lead_needs_router.delete(
    "/lead-needs/{need_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lead_need(
    need_id: int, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogLeadNeed)
    obj = await crud.get(need_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Besoin introuvable")
    lead_id = getattr(obj, "lead_id", None)
    await crud.delete(obj)
    await log_action(
        db,
        user=user,
        action="devlog_lead_need.deleted",
        entity_type="devlog_lead_need",
        entity_id=need_id,
        details={"lead_id": lead_id},
    )


# --- AI : génération d'un plan structuré depuis les besoins du client ----

_PLAN_SYSTEM_PROMPT = """\
Tu es un PM senior d'une boîte de dev logiciel. À partir d'un brief
client par pôle (Frontend, Backend, Design, etc.), produis un plan
structuré exploitable pour préparer une soumission. Sois pragmatique
sur les estimations (heures + coût horaire interne ~75$/h dev,
~100$/h design senior, ~65$/h support).

RETOURNE UNIQUEMENT un JSON valide, sans markdown, sans texte autour,
au format :

{
  "summary": "résumé exécutif en 2-3 phrases",
  "sections": [
    {
      "pole": "frontend",
      "name": "Frontend",
      "billing_kind": "initial",
      "markup_percent": 100,
      "notes": "courte note interne",
      "items": [
        {"description": "...", "quantity": 40, "unit": "h", "cost_per_unit": 75}
      ]
    },
    {
      "pole": "hosting",
      "name": "Hébergement + abonnements",
      "billing_kind": "recurring",
      "markup_percent": 50,
      "items": [
        {"description": "VPS production", "quantity": 1, "unit": "mois", "cost_per_unit": 40}
      ]
    }
  ]
}

Règles strictes :
- Inclure systématiquement une section recurring « Hébergement +
  abonnements » (mandatory : Horizon héberge le produit du client).
- billing_kind ∈ {"initial","recurring"}.
- markup_percent : 100 pour initial (dev), 50 pour recurring (hosting).
- Quantités et coûts réalistes. Pas de placeholder.
- Pas de champs autres que ceux du schéma.
"""


def _coerce_plan_payload(raw: str) -> dict:
    """Extrait un JSON depuis la réponse IA en étant tolérant aux
    fences ```json``` que certains modèles ajoutent malgré tout."""
    import json
    import re

    txt = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.DOTALL)
    if fence:
        txt = fence.group(1)
    # Fallback : prendre le 1er { au dernier }.
    if not txt.startswith("{"):
        start = txt.find("{")
        end = txt.rfind("}")
        if start >= 0 and end > start:
            txt = txt[start : end + 1]
    return json.loads(txt)


@lead_needs_router.post(
    "/leads/{lead_id}/generate-plan",
    response_model=DevlogLeadPlan,
    summary="Génère un plan structuré depuis les besoins du lead (IA)",
)
async def generate_lead_plan(
    lead_id: int, db: DBSession, user: CurrentUser
):
    from app.integrations.ai import (
        AIProviderUnavailable,
        complete,
        is_configured,
    )

    lead = await GenericCrud(db, DevlogLead).get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    needs = (
        await db.execute(
            select(DevlogLeadNeed)
            .where(DevlogLeadNeed.lead_id == lead_id)
            .order_by(DevlogLeadNeed.position.asc(), DevlogLeadNeed.id.asc())
        )
    ).scalars().all()
    if not needs:
        raise HTTPException(
            status_code=400,
            detail="Ajoute au moins un besoin avant de générer le plan.",
        )
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Aucun provider IA configuré (AI_PROVIDER).",
        )

    # Compose le brief envoyé au modèle.
    parts: List[str] = [
        f"Client : {lead.name}",
    ]
    if lead.company:
        parts.append(f"Entreprise : {lead.company}")
    if lead.project_type:
        parts.append(f"Type de projet : {lead.project_type}")
    if lead.budget_range:
        parts.append(f"Budget indicatif : {lead.budget_range}")
    if lead.project_summary:
        parts.append(f"Résumé : {lead.project_summary}")
    parts.append("\nBesoins par pôle :")
    for n in needs:
        block = f"\n- {n.label} (pole={n.pole}"
        if n.complexity:
            block += f", complexité={n.complexity}"
        if n.priority:
            block += f", priorité={n.priority}"
        block += ")"
        if n.notes:
            block += f"\n  {n.notes}"
        parts.append(block)
    brief = "\n".join(parts)

    try:
        res = await complete(
            prompt=brief,
            system=_PLAN_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.2,
        )
    except AIProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        payload = _coerce_plan_payload(res.text)
        plan = DevlogLeadPlan.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Plan IA illisible : {exc}",
        ) from exc
    await log_action(
        db,
        user=user,
        action="devlog_lead.plan_generated",
        entity_type="devlog_lead",
        entity_id=lead_id,
        details={
            "sections_count": len(plan.sections),
            "items_count": sum(len(s.items) for s in plan.sections),
            "model_used": getattr(res, "model", None),
        },
    )
    return plan


@lead_needs_router.post(
    "/leads/{lead_id}/plan-to-soumission",
    response_model=DevlogSoumissionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crée une soumission (sections + items) depuis un plan",
)
async def plan_to_soumission(
    lead_id: int,
    data: DevlogLeadPlanToSoumissionRequest,
    db: DBSession,
    user: CurrentUser,
):
    lead = await GenericCrud(db, DevlogLead).get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead introuvable")
    title = (data.title or f"Soumission — {lead.name}").strip()

    soumission = DevlogSoumission(
        title=title,
        lead_id=lead_id,
        client_id=lead.client_id,
        status="brouillon",
        amount=0,
        summary=data.plan.summary,
    )
    db.add(soumission)
    await db.flush()
    await db.refresh(soumission)

    for sec_idx, sec in enumerate(data.plan.sections):
        section = DevlogSoumissionSection(
            soumission_id=soumission.id,
            position=sec_idx,
            name=sec.name,
            billing_kind=(
                "recurring" if sec.billing_kind == "recurring" else "initial"
            ),
            markup_percent=(
                float(sec.markup_percent)
                if sec.markup_percent is not None
                else None
            ),
            notes=sec.notes,
        )
        db.add(section)
        await db.flush()
        await db.refresh(section)

        markup = float(section.markup_percent or 0)
        for it_idx, it in enumerate(sec.items):
            unit_price = _apply_markup(it.cost_per_unit, markup)
            total = _compute_item_total(it.quantity, unit_price)
            db.add(
                DevlogSoumissionItem(
                    soumission_id=soumission.id,
                    section_id=section.id,
                    position=it_idx,
                    description=it.description,
                    unit=it.unit,
                    quantity=float(it.quantity),
                    cost_per_unit=float(it.cost_per_unit),
                    unit_price=unit_price,
                    total=total,
                )
            )

    await db.flush()
    await _refresh_soumission_amount(db, soumission.id)
    await db.refresh(soumission)
    await log_action(
        db,
        user=user,
        action="devlog_lead.plan_to_soumission",
        entity_type="devlog_lead",
        entity_id=lead_id,
        details={"soumission_id": soumission.id},
    )
    return DevlogSoumissionRead.model_validate(soumission)


# --------------------------------------------------------------------------
# Contrats electroniques (signature publique avec token)
# --------------------------------------------------------------------------

import secrets
from datetime import datetime, timezone
from fastapi import Request

contracts_router = APIRouter(prefix="/devlog", tags=["devlog"])


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


@contracts_router.get(
    "/contracts",
    response_model=List[DevlogContractRead],
)
async def list_contracts(db: DBSession, _: CurrentUser):
    rows = (
        await db.execute(
            select(DevlogContract).order_by(DevlogContract.id.desc())
        )
    ).scalars().all()
    return list(rows)


@contracts_router.post(
    "/contracts",
    response_model=DevlogContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract(
    data: DevlogContractCreate, db: DBSession, user: CurrentUser
):
    obj = await GenericCrud(db, DevlogContract).create(data)
    await log_action(
        db,
        user=user,
        action="devlog_contract.created",
        entity_type="devlog_contract",
        entity_id=obj.id,
        details={
            "client_id": getattr(obj, "client_id", None),
            "title": getattr(obj, "title", None),
        },
    )
    return DevlogContractRead.model_validate(obj)


@contracts_router.get(
    "/contracts/{contract_id}",
    response_model=DevlogContractRead,
)
async def get_contract(contract_id: int, db: DBSession, _: CurrentUser):
    obj = await GenericCrud(db, DevlogContract).get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return DevlogContractRead.model_validate(obj)


@contracts_router.patch(
    "/contracts/{contract_id}",
    response_model=DevlogContractRead,
)
async def update_contract(
    contract_id: int,
    data: DevlogContractUpdate,
    db: DBSession,
    user: CurrentUser,
):
    crud = GenericCrud(db, DevlogContract)
    obj = await crud.get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    update_data = data.model_dump(exclude_unset=True)
    # Verrouillage d'edition une fois signe — sauf si le PATCH ne porte
    # QUE sur le champ status (drag-and-drop kanban vers "annule" par ex.)
    # ou sur les champs depot (Phil peut marquer le depot apres coup).
    if obj.status == "signe":
        allowed_post_sign = {
            "status",
            "deposit_required_cents",
            "project_id",
        }
        forbidden = set(update_data.keys()) - allowed_post_sign
        if forbidden:
            raise HTTPException(
                status_code=400,
                detail="Contrat signe - edition verrouillee.",
            )
    previous_status = obj.status
    obj = await crud.update(obj, data)
    await log_action(
        db,
        user=user,
        action="devlog_contract.updated",
        entity_type="devlog_contract",
        entity_id=contract_id,
        details=update_data,
    )
    # Si le statut passe a "signe" via PATCH (drag-and-drop kanban) et
    # que le depot est deja paye, on declenche le demarrage projet.
    if previous_status != "signe" and obj.status == "signe":
        try:
            await maybe_start_project(db, obj, user=user)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "auto-start project apres PATCH contrat %s a echoue",
                contract_id,
            )
    return DevlogContractRead.model_validate(obj)


@contracts_router.delete(
    "/contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contract(
    contract_id: int, db: DBSession, user: CurrentUser
):
    crud = GenericCrud(db, DevlogContract)
    obj = await crud.get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    await crud.delete(obj)
    await log_action(
        db,
        user=user,
        action="devlog_contract.deleted",
        entity_type="devlog_contract",
        entity_id=contract_id,
        details=None,
    )


@contracts_router.post(
    "/contracts/{contract_id}/send",
    response_model=DevlogContractRead,
    summary=(
        "Genere un signature_token (si absent) et passe le contrat en "
        "envoye. L'admin peut copier le lien public et l'envoyer."
    ),
)
async def send_contract(
    contract_id: int, db: DBSession, user: CurrentUser
):
    obj = await GenericCrud(db, DevlogContract).get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    # Idempotence + robustesse (fix bug "erreur generation de lien
    # impossible") : on regenere un token si l'existant est vide OU
    # incoherent (chaine vide vs NULL en base), et on retente une fois
    # sur IntegrityError (collision token theoriquement impossible
    # mais coute zero de proteger). Sans ce filet, un contrat re-envoye
    # avec un token corrompu plantait silencieusement la requete cote
    # backend - le frontend ne voyait qu'un 500 generique.
    import logging as _logging
    _log = _logging.getLogger(__name__)
    if not (obj.signature_token or "").strip():
        obj.signature_token = _gen_token()
    obj.status = "envoye"
    obj.sent_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except Exception as exc:
        # Collision sur unique(signature_token) - rarissime mais on
        # regenere et on retente une fois.
        _log.warning(
            "send_contract %s: flush a echoue (%s) - regeneration token",
            contract_id, exc,
        )
        await db.rollback()
        obj = await GenericCrud(db, DevlogContract).get(contract_id)
        if obj is None:
            raise HTTPException(
                status_code=404, detail="Contrat introuvable"
            )
        obj.signature_token = _gen_token()
        obj.status = "envoye"
        obj.sent_at = datetime.now(timezone.utc)
        try:
            await db.flush()
        except Exception as exc2:
            _log.exception(
                "send_contract %s: 2eme flush a aussi echoue",
                contract_id,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Generation du lien impossible : {exc2}",
            ) from exc2
    await log_action(
        db,
        user=user,
        action="devlog_contract.sent",
        entity_type="devlog_contract",
        entity_id=contract_id,
        details={"signature_token": obj.signature_token},
    )
    return DevlogContractRead.model_validate(obj)


@contracts_router.post(
    "/contracts/{contract_id}/mark-deposit-paid",
    response_model=DevlogContractRead,
    summary=(
        "Marque le depot initial comme paye (manuel, apres virement / "
        "cheque). Si le contrat est deja signe, declenche automatiquement "
        "le demarrage du projet (generation phases/taches depuis la "
        "soumission, notification email Phil)."
    ),
)
async def mark_deposit_paid(
    contract_id: int,
    body: DevlogContractMarkDepositPaid,
    db: DBSession,
    user: CurrentUser,
):
    obj = await GenericCrud(db, DevlogContract).get(contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    # Idempotent : un re-marquage met simplement a jour le montant.
    obj.deposit_paid_amount_cents = body.amount_cents
    if obj.deposit_paid_at is None:
        obj.deposit_paid_at = datetime.now(timezone.utc)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_contract.deposit_paid",
        entity_type="devlog_contract",
        entity_id=contract_id,
        details={
            "amount_cents": body.amount_cents,
            "deposit_paid_at": obj.deposit_paid_at.isoformat()
            if obj.deposit_paid_at
            else None,
        },
    )
    # Si le contrat est deja signe, on demarre le projet maintenant.
    if obj.status == "signe":
        try:
            await maybe_start_project(db, obj, user=user)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).exception(
                "auto-start project apres mark-deposit-paid contrat %s a echoue",
                contract_id,
            )
    return DevlogContractRead.model_validate(obj)


# --- Auto-remplissage depuis une soumission acceptee -----------------------

# Template Markdown du contrat - placeholders entre accolades, formates
# via str.format(). Toute valeur fournie par l'utilisateur est nettoyee
# en amont (pas d'echappement specifique : Markdown sans rendu HTML).
_CONTRACT_TEMPLATE = (
    "# Contrat de developpement logiciel\n"
    "\n"
    "## Parties\n"
    "\n"
    "**Prestataire** : Horizon Services Immobiliers inc.\n"
    "\n"
    "**Client** : {client_nom}\n"
    "{client_adresse_line}"
    "{client_email_line}"
    "\n"
    "## Objet du contrat\n"
    "\n"
    "Le Prestataire s'engage a fournir au Client les services de "
    "developpement logiciel suivants, tels que detailles dans la "
    "soumission n^o {soumission_numero} acceptee le {date_acceptation} :\n"
    "\n"
    "**{soumission_titre}**\n"
    "\n"
    "{sections_resumees}\n"
    "\n"
    "## Conditions financieres\n"
    "\n"
    "**Frais de mise en oeuvre** (paiement unique) : "
    "{prix_initial_ttc} $ taxes incluses\n"
    "  - Depot a la signature : 50 % ({depot_ttc} $)\n"
    "  - Solde a la livraison : 50 % ({solde_ttc} $)\n"
    "\n"
    "**Frais mensuels recurrents** : {prix_mensuel_ttc} $ / mois "
    "taxes incluses\n"
    "\n"
    "Toutes les sommes sont payables dans les 15 jours suivant "
    "l'emission de la facture.\n"
    "\n"
    "## Duree\n"
    "\n"
    "Le projet demarre des la signature du present contrat et le "
    "versement du depot. La livraison est estimee au "
    "{date_livraison_estimee}.\n"
    "\n"
    "## Propriete intellectuelle\n"
    "\n"
    "Le code source, les designs et les livrables deviennent la "
    "propriete du Client a la reception du paiement final. Le "
    "Prestataire conserve le droit de reutiliser les composants "
    "generiques et non confidentiels pour ses autres projets.\n"
    "\n"
    "## Garanties\n"
    "\n"
    "Le Prestataire garantit ses livrables contre les defauts de "
    "fonctionnement pendant 90 jours suivant la livraison. Cette "
    "garantie ne couvre pas les modifications apportees par le Client "
    "ou par un tiers.\n"
    "\n"
    "## Confidentialite\n"
    "\n"
    "Les deux parties s'engagent a respecter la confidentialite des "
    "informations echangees dans le cadre du present contrat.\n"
    "\n"
    "## Resiliation\n"
    "\n"
    "Toute resiliation anticipee par le Client donne lieu au paiement "
    "des heures effectuees + 20 % de penalite sur le solde du "
    "contrat.\n"
    "\n"
    "## Signatures\n"
    "\n"
    "**Pour le Prestataire** : Philippe Meuser, Horizon Services "
    "Immobiliers inc.\n"
    "Date : {date_emission}\n"
    "\n"
    "**Pour le Client** : ________________________\n"
    "Date : ________________________\n"
)


def _fmt_money(n: float) -> str:
    """Formate un montant en CAD style 'X XXX.XX' (separateur espace
    insecable, deux decimales). Reste compatible Markdown brut."""
    try:
        s = f"{float(n):,.2f}"
    except (TypeError, ValueError):
        s = "0.00"
    # Espace fine insecable comme separateur de milliers (style fr-CA).
    return s.replace(",", " ")


def _fmt_date_fr(d) -> str:
    """Formate une date / datetime en 'JJ mois YYYY' (francais)."""
    if d is None:
        return "________________"
    mois = [
        "janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
    ]
    return f"{d.day} {mois[d.month - 1]} {d.year}"


@contracts_router.post(
    "/contracts/from-soumission/{soumission_id}",
    response_model=DevlogContractRead,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Cree un contrat brouillon auto-rempli a partir d'une soumission "
        "acceptee : parties, objet, conditions financieres, clauses "
        "standards."
    ),
)
async def create_contract_from_soumission(
    soumission_id: int, db: DBSession, user: CurrentUser
):
    from datetime import timedelta

    soum = await GenericCrud(db, DevlogSoumission).get(soumission_id)
    if soum is None:
        raise HTTPException(
            status_code=404, detail="Soumission introuvable"
        )
    if soum.status != "acceptee":
        raise HTTPException(
            status_code=400,
            detail=(
                "La soumission doit etre acceptee pour generer un "
                "contrat (statut actuel : " + soum.status + ")."
            ),
        )

    # --- Client (peut etre absent si soumission liee a un lead seul) ---
    client = None
    if soum.client_id is not None:
        client = await GenericCrud(db, DevlogClient).get(soum.client_id)

    # --- Sections + items pour le resume objet du contrat -------------
    sections = (
        (
            await db.execute(
                select(DevlogSoumissionSection)
                .where(
                    DevlogSoumissionSection.soumission_id == soumission_id
                )
                .order_by(
                    DevlogSoumissionSection.position.asc(),
                    DevlogSoumissionSection.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    items = (
        (
            await db.execute(
                select(DevlogSoumissionItem)
                .where(
                    DevlogSoumissionItem.soumission_id == soumission_id
                )
                .order_by(
                    DevlogSoumissionItem.position.asc(),
                    DevlogSoumissionItem.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )

    # --- Prix : prefere compute_devis pour les devis_dev, sinon
    # fallback sur soumission.amount + somme des items recurring. ----
    prix_initial_ttc = 0.0
    prix_mensuel_ttc = 0.0
    if soum.is_devis_dev:
        try:
            preview = compute_devis(soum, items)
            if not preview.get("is_invalid"):
                prix_initial_ttc = float(
                    preview["initial"].get("total_final_taxe", 0.0)
                )
                prix_mensuel_ttc = float(
                    preview["recurring"].get(
                        "total_client_amount_taxe", 0.0
                    )
                )
        except Exception:
            # Fallback silencieux : le calcul circulaire peut etre
            # invalide (divisor <= 0). On laisse les montants a 0,
            # Phil ajustera dans l'editeur.
            prix_initial_ttc = 0.0
            prix_mensuel_ttc = 0.0
    else:
        # Legacy : utilise amount (initial) ; pas de recurrent identifiable.
        if soum.amount is not None:
            # On suppose amount HT, on applique 1.14975 (TPS+TVQ Qc).
            prix_initial_ttc = float(soum.amount) * 1.14975
        prix_mensuel_ttc = 0.0

    depot_ttc = prix_initial_ttc / 2.0
    solde_ttc = prix_initial_ttc - depot_ttc

    # --- Resume des sections (objet du contrat) -----------------------
    if sections:
        # Une ligne par section, en utilisant client_label si present.
        lignes = []
        for sec in sections:
            label = (sec.client_label or sec.name or "").strip()
            kind = (
                "mensuel" if sec.billing_kind == "recurring" else "livraison"
            )
            lignes.append(f"- **{label}** ({kind})")
        sections_resumees = "\n".join(lignes)
    elif soum.summary:
        sections_resumees = soum.summary.strip()
    else:
        sections_resumees = (
            "- Livraison conforme a la soumission acceptee."
        )

    # --- Dates ---------------------------------------------------------
    now = datetime.now(timezone.utc)
    date_acceptation = _fmt_date_fr(soum.signed_at or soum.updated_at or now)
    date_emission = _fmt_date_fr(now)
    date_livraison_estimee = _fmt_date_fr(now + timedelta(days=60))

    # --- Champs client -------------------------------------------------
    if client is not None:
        client_nom = client.name
        if client.company:
            client_nom = f"{client_nom} ({client.company})"
        client_adresse_line = (
            f"{client.address}\n" if client.address else ""
        )
        client_email_line = (
            f"{client.email}\n" if client.email else ""
        )
    else:
        client_nom = "________________________"
        client_adresse_line = ""
        client_email_line = ""

    body = _CONTRACT_TEMPLATE.format(
        client_nom=client_nom,
        client_adresse_line=client_adresse_line,
        client_email_line=client_email_line,
        soumission_numero=str(soum.id),
        soumission_titre=soum.title,
        date_acceptation=date_acceptation,
        sections_resumees=sections_resumees,
        prix_initial_ttc=_fmt_money(prix_initial_ttc),
        depot_ttc=_fmt_money(depot_ttc),
        solde_ttc=_fmt_money(solde_ttc),
        prix_mensuel_ttc=_fmt_money(prix_mensuel_ttc),
        date_livraison_estimee=date_livraison_estimee,
        date_emission=date_emission,
    )

    title = f"Contrat - {soum.title}"
    contract = DevlogContract(
        title=title[:255],
        body=body,
        status="brouillon",
        soumission_id=soum.id,
        client_id=soum.client_id,
        project_id=None,
    )
    db.add(contract)
    await db.flush()
    await log_action(
        db,
        user=user,
        action="devlog_contract.created_from_soumission",
        entity_type="devlog_contract",
        entity_id=contract.id,
        details={
            "soumission_id": soum.id,
            "client_id": soum.client_id,
            "prix_initial_ttc": round(prix_initial_ttc, 2),
            "prix_mensuel_ttc": round(prix_mensuel_ttc, 2),
        },
    )
    return DevlogContractRead.model_validate(contract)


# --- Endpoints publics (sans auth - acces par lien token) ---

public_contracts_router = APIRouter(
    prefix="/public/devlog", tags=["devlog-public"]
)


@public_contracts_router.get(
    "/contracts/{token}",
    response_model=DevlogContractPublicRead,
)
async def public_get_contract(token: str, db: DBSession):
    obj = (
        await db.execute(
            select(DevlogContract).where(
                DevlogContract.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lien invalide")
    return DevlogContractPublicRead.model_validate(obj)


@public_contracts_router.post(
    "/contracts/{token}/sign",
    response_model=DevlogContractPublicRead,
)
async def public_sign_contract(
    token: str,
    data: DevlogContractSignRequest,
    request: Request,
    db: DBSession,
):
    obj = (
        await db.execute(
            select(DevlogContract).where(
                DevlogContract.signature_token == token
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Lien invalide")
    if obj.status == "signe":
        # Idempotent : on retourne la version signee sans reecrire.
        return DevlogContractPublicRead.model_validate(obj)
    if obj.status == "annule":
        raise HTTPException(
            status_code=400, detail="Contrat annule - signature refusee."
        )
    obj.status = "signe"
    obj.signed_at = datetime.now(timezone.utc)
    obj.signed_name = data.name.strip()[:255]
    # Best-effort IP capture.
    fwd = request.headers.get("x-forwarded-for") or ""
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    obj.signed_ip = (ip or "")[:64]
    await db.flush()
    await log_action(
        db,
        user=None,
        action="devlog_contract.signed",
        entity_type="devlog_contract",
        entity_id=obj.id,
        details={
            "signed_name": obj.signed_name,
            "signed_ip": obj.signed_ip,
        },
    )

    # Cas : Phil a deja marque le depot paye AVANT la signature publique.
    # On declenche le demarrage projet automatique. Best-effort : si
    # quoi que ce soit rate, on ne casse pas la signature (qui est
    # juridiquement engageante cote client).
    try:
        await maybe_start_project(db, obj, user=None)
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).exception(
            "auto-start project apres signature contrat %s a echoue",
            obj.id,
        )

    # Hook post-signature : 4 side-effects best-effort (email welcome,
    # notif Teams, repo GitHub, push QBO). Chaque action est encapsulée
    # individuellement — l'orchestrateur ``on_contract_signed`` ne lève
    # jamais, donc pas besoin d'un try/except ici. Le tout est conçu
    # pour rester < 3-5 s ; au pire on dégrade en no-op si une intégra-
    # tion n'est pas configurée (cf. les ENV vars optionnelles
    # TEAMS_WEBHOOK_URL_DEVLOG / GITHUB_AUTOMATION_TOKEN / etc.).
    await on_contract_signed(obj, db)

    return DevlogContractPublicRead.model_validate(obj)



