"""Generic CRUD endpoints for business entities.

All endpoints require an authenticated user.
"""

from datetime import datetime, timezone
from typing import List, Type

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import CurrentUser, DBSession, RequireManager
from app.db.base import Base
from app.models.achat import Achat
from app.models.agenda_event import AgendaEvent
from app.models.bon_travail import BonTravail
from app.models.employe import Employe
from app.models.facture import Facture, FactureStatus
from app.models.fournisseur import Fournisseur
from app.models.note_template import NoteTemplate
from app.models.punch import Punch
from app.models.purchase_order import PurchaseOrder
from app.models.soumission import Soumission
from app.models.sous_traitant import SousTraitant
from app.models.sous_traitant_timesheet import SousTraitantTimesheet
from app.repositories.generic import GenericCrud
from app.schemas.business import (
    AchatCreate,
    AchatRead,
    AchatUpdate,
    AgendaEventCreate,
    AgendaEventRead,
    AgendaEventUpdate,
    BonTravailCreate,
    BonTravailRead,
    BonTravailUpdate,
    EmployeCreate,
    EmployeRead,
    EmployeUpdate,
    FactureCreate,
    FactureRead,
    FactureUpdate,
    FournisseurCreate,
    FournisseurRead,
    FournisseurUpdate,
    PunchCreate,
    PunchRead,
    PunchUpdate,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
    SoumissionCreate,
    SoumissionRead,
    SoumissionUpdate,
)
from app.schemas.sous_traitant import (
    SousTraitantCreate,
    SousTraitantRead,
    SousTraitantUpdate,
)
from app.schemas.sous_traitant_timesheet import (
    SousTraitantTimesheetCreate,
    SousTraitantTimesheetRead,
    SousTraitantTimesheetUpdate,
)
from app.schemas.note_template import (
    NoteTemplateCreate,
    NoteTemplateRead,
    NoteTemplateUpdate,
)


# Anti-doublon opportuniste : on déclenche une déduplication des achats au
# plus une fois toutes les N secondes quand la liste est consultée, en
# arrière-plan (session fraîche). Pas de bouton : les doublons disparaissent
# « tout seuls » dès qu'on ouvre la page Achats.
_ACHAT_DEDUPE_THROTTLE_S = 30.0
_last_achat_dedupe_at = 0.0


def _maybe_dedupe_achats_bg() -> None:
    import asyncio
    import time

    global _last_achat_dedupe_at
    now = time.monotonic()
    if now - _last_achat_dedupe_at < _ACHAT_DEDUPE_THROTTLE_S:
        return
    _last_achat_dedupe_at = now

    async def _run() -> None:
        from app.db.session import AsyncSessionLocal
        from app.services.achat_dedupe import dedupe_achats

        try:
            async with AsyncSessionLocal() as s:
                removed = await dedupe_achats(s)
                if removed:
                    await s.commit()
                else:
                    await s.rollback()
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        # Pas de boucle asyncio active (contexte sync) : on ignore.
        pass


_last_facture_dedupe_at = 0.0


def _maybe_dedupe_factures_bg() -> None:
    import asyncio
    import time

    global _last_facture_dedupe_at
    now = time.monotonic()
    if now - _last_facture_dedupe_at < _ACHAT_DEDUPE_THROTTLE_S:
        return
    _last_facture_dedupe_at = now

    async def _run() -> None:
        from app.db.session import AsyncSessionLocal
        from app.services.facture_dedupe import dedupe_factures

        try:
            async with AsyncSessionLocal() as s:
                removed = await dedupe_factures(s)
                if removed:
                    await s.commit()
                else:
                    await s.rollback()
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        pass


_last_billable_correct_at = 0.0


def _maybe_correct_billable_bg() -> None:
    """Remet « à refacturer » les dépenses des projets contrat/estimé.

    Automatisme DB-only déclenché à l'ouverture de la liste des achats
    (au plus 1×/30 s), en miroir de l'hourly cron, pour que le statut
    REFACT se corrige sans attendre l'heure pleine.
    """
    import asyncio
    import time

    global _last_billable_correct_at
    now = time.monotonic()
    if now - _last_billable_correct_at < _ACHAT_DEDUPE_THROTTLE_S:
        return
    _last_billable_correct_at = now

    async def _run() -> None:
        from app.db.session import AsyncSessionLocal
        from app.services.achat_billable_correct import (
            correct_billable_for_contract_projects,
        )

        try:
            async with AsyncSessionLocal() as s:
                await correct_billable_for_contract_projects(s)
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        pass


def make_crud_router(
    *,
    prefix: str,
    tag: str,
    model: Type[Base],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    read_schema: Type[BaseModel],
    require_manager: bool = True,
) -> APIRouter:
    """Generic CRUD endpoints. By default they require manager+ role so
    that plain employees don't see (or modify) records they shouldn't.
    Set ``require_manager=False`` to keep them open to any logged-in
    user (e.g. agenda events which employees need to read)."""
    router = APIRouter(prefix=prefix, tags=[tag])

    # One auth dep per-operation: manager+ for writes always, reads when
    # require_manager=True. For open routers (agenda), reads are any user
    # but writes still require manager+.
    AuthRead = RequireManager if require_manager else CurrentUser
    AuthWrite = RequireManager

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create(data: create_schema, db: DBSession, user: AuthWrite):  # type: ignore[valid-type]
        # Numérotation séquentielle auto pour Soumission / Facture si
        # la référence n'est pas fournie (alignée sur la séquence
        # QuickBooks via /api/v1/settings/numbering).
        if hasattr(data, "reference") and getattr(data, "reference", None) in (
            None,
            "",
        ):
            from app.services.numbering import (
                next_facture_number,
                next_po_number,
                next_soumission_number,
            )

            if model is Soumission:
                data.reference = await next_soumission_number(db)
            elif model is Facture:
                data.reference = await next_facture_number(db)
            elif model is PurchaseOrder:
                data.reference = await next_po_number(db)
        crud = GenericCrud(db, model)
        obj = await crud.create(data)
        # Achat : applique la logique payment_method + due_at apres
        # creation (avant l'autopush QBO pour que QB recoive le bon
        # statut Bill/Purchase).
        if model is Achat:
            from app.services.achat_payment import (
                apply_payment_defaults,
            )

            await apply_payment_defaults(db, obj)
            await db.flush()
        # Auto-push QBO pour tout Achat créé « actif » (reçu OU déjà payé) →
        # il part dans QB et se classe dans le bon projet. Avant, seuls les
        # achats « received » partaient ; un achat saisi DÉJÀ payé (chèque/CC)
        # était oublié.
        if model is Achat and getattr(obj, "status", None) in (
            "received",
            "paid",
        ):
            import asyncio

            from app.api.v1.endpoints.achat_qbo import autopush_achat

            asyncio.create_task(autopush_achat(int(obj.id)))
        # Synchro QBO automatique (Facture / Soumission). Inerte tant que
        # l'interrupteur `qbo_auto_sync` est OFF (fail-closed) : ne
        # s'active qu'après validation de la migration de masse.
        if model in (Facture, Soumission):
            import asyncio

            from app.services.qbo_auto_sync import (
                autopush_facture,
                autopush_soumission,
            )

            if model is Facture:
                asyncio.create_task(autopush_facture(int(obj.id)))
            else:
                asyncio.create_task(autopush_soumission(int(obj.id)))
        # Auto-bump : tout Punch créé sur un projet bascule celui-ci
        # en « En cours » s'il ne l'est pas déjà.
        if model is Punch:
            from app.services.project_auto_status import (
                bump_to_in_progress_if_needed,
            )

            await bump_to_in_progress_if_needed(
                db, getattr(obj, "project_id", None)
            )
            await db.flush()
        # Journal d'audit : on trace la création pour pouvoir
        # retrouver qui a créé quoi (volet construction & Co.).
        from app.services.audit import log_action as _log_action

        await _log_action(
            db,
            user=user,
            action=f"{tag}.created",
            entity_type=tag,
            entity_id=getattr(obj, "id", None),
            details={
                "reference": getattr(obj, "reference", None),
                "name": getattr(obj, "name", None)
                or getattr(obj, "title", None)
                or getattr(obj, "full_name", None),
            },
        )
        return read_schema.model_validate(obj)

    @router.get("", response_model=List[read_schema])  # type: ignore[valid-type]
    async def list_items(
        db: DBSession,
        _: AuthRead,
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        crud = GenericCrud(db, model)
        items = await crud.list(skip=skip, limit=limit)
        # Ouvrir la liste des achats nettoie les doublons en tâche de fond
        # (au plus 1×/30 s) — sans bouton, comme demandé.
        if model is Achat:
            _maybe_dedupe_achats_bg()
            _maybe_correct_billable_bg()
        elif model is Facture:
            _maybe_dedupe_factures_bg()
        return [read_schema.model_validate(i) for i in items]

    @router.get("/{item_id}")
    async def get_item(item_id: int, db: DBSession, _: AuthRead):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return read_schema.model_validate(obj)

    @router.patch("/{item_id}")
    async def update_item(item_id: int, data: update_schema, db: DBSession, user: AuthWrite):  # type: ignore[valid-type]
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        # Renumérotation : la référence Soumission/Facture/PO est UNIQUE.
        # On vérifie AVANT l'update qu'aucun autre enregistrement ne porte
        # déjà ce numéro → message clair (409) au lieu d'un 500 opaque
        # (violation de contrainte) qui bloquait l'utilisateur.
        if model in (Soumission, Facture, PurchaseOrder):
            try:
                _new_ref = data.model_dump(exclude_unset=True).get("reference")
            except Exception:  # noqa: BLE001
                _new_ref = None
            if (
                isinstance(_new_ref, str)
                and _new_ref.strip()
                and _new_ref.strip() != (getattr(obj, "reference", None) or "")
            ):
                from sqlalchemy import select as _sel_ref

                clash = (
                    await db.execute(
                        _sel_ref(model.id).where(
                            model.reference == _new_ref.strip(),
                            model.id != item_id,
                        )
                    )
                ).first()
                if clash is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Le numéro « {_new_ref.strip()} » est déjà utilisé "
                        "par un autre document. Choisis-en un autre ou "
                        "supprime le doublon.",
                    )
        # Capture pre-update status pour détecter la transition
        # vers received sur les achats → autopush QBO en background.
        prev_status = (
            getattr(obj, "status", None)
            if model in (Achat, Facture)
            else None
        )
        # Capture pre-update project_id du Punch — si on rattache un
        # punch existant à un projet (ou on le change de projet), on
        # bumpera aussi ce projet.
        prev_project_id = (
            getattr(obj, "project_id", None) if model is Punch else None
        )
        # Capture pre-update project_id de l'Achat / Facture — si on
        # (re)classe le document dans un projet, on doit pousser la mise à
        # jour vers QB (CustomerRef = sous-client du projet, ClassRef =
        # chantier) pour que le coût / revenu soit attribué au bon projet.
        prev_doc_project_id = (
            getattr(obj, "project_id", None)
            if model in (Achat, Facture)
            else None
        )
        # Capture pre-update total Soumission — si le total change,
        # on propage au budget du projet lié pour que la kanban, le
        # header projet (« Budget » pill) et le champ « Budget (CAD) »
        # de la fiche reflètent la dernière version soumissionnée.
        prev_soum_total = (
            getattr(obj, "total", None) if model is Soumission else None
        )
        # Snapshot avant/après pour journaliser une modification
        # MANUELLE de punch (édition admin des heures / dates /
        # projet). Permet de tracer dans le journal d'activité qui a
        # touché à un pointage et ce qui a changé.
        punch_before: dict = {}
        punch_changed_fields: list[str] = []
        if model is Punch:
            try:
                punch_changed_fields = list(
                    data.model_dump(exclude_unset=True).keys()
                )
            except Exception:  # noqa: BLE001
                punch_changed_fields = []
            for f in punch_changed_fields:
                punch_before[f] = getattr(obj, f, None)
        obj = await crud.update(obj, data)
        if model is Punch and punch_changed_fields:
            from app.services.audit import log_action as _log_punch_audit

            changes = {}
            for f in punch_changed_fields:
                after = getattr(obj, f, None)
                before = punch_before.get(f)
                if str(before) != str(after):
                    changes[f] = {
                        "avant": str(before) if before is not None else None,
                        "apres": str(after) if after is not None else None,
                    }
            if changes:
                await _log_punch_audit(
                    db,
                    user=user,
                    action="punch.modifie",
                    entity_type="punch",
                    entity_id=int(obj.id),
                    details={
                        "employe_id": getattr(obj, "employe_id", None),
                        "project_id": getattr(obj, "project_id", None),
                        "modifications": changes,
                    },
                )
        if model is Achat:
            new_status = getattr(obj, "status", None)
            new_proj = getattr(obj, "project_id", None)
            # Push QB si : (a) l'achat devient « actif » (received OU paid)
            # pour la 1ʳᵉ fois, OU (b) on le (re)classe dans un autre projet
            # (met à jour le CustomerRef/ClassRef du Bill/Purchase QB).
            became_active = prev_status not in ("received", "paid") and (
                new_status in ("received", "paid")
            )
            project_changed = new_proj != prev_doc_project_id
            # Garde anti-doublon : un achat IMPORTÉ de QB comme Purchase ne
            # porte que `qbo_purchase_id` (pas `qbo_bill_id`) et un mode de
            # paiement non mappé → un re-push le recréerait en Bill doublon.
            # On ne re-pousse sur changement de projet que les achats sans
            # lien QB (création propre) ou liés via `qbo_bill_id`
            # (mise à jour sparse propre).
            safe_for_repush = bool(getattr(obj, "qbo_bill_id", None)) or not (
                getattr(obj, "qbo_purchase_id", None)
            )
            if became_active or (project_changed and safe_for_repush):
                import asyncio

                from app.api.v1.endpoints.achat_qbo import autopush_achat

                asyncio.create_task(autopush_achat(int(obj.id)))
        if model is Punch:
            new_project_id = getattr(obj, "project_id", None)
            if new_project_id is not None and new_project_id != prev_project_id:
                from app.services.project_auto_status import (
                    bump_to_in_progress_if_needed,
                )

                await bump_to_in_progress_if_needed(db, new_project_id)
                await db.flush()
        if model is Soumission:
            new_total = getattr(obj, "total", None)
            if new_total != prev_soum_total and new_total is not None:
                # Sync : Project.budget = Soumission.total quand le
                # total change. Affecte la card kanban, le pill «
                # Budget » du header projet et le champ « Budget (CAD)
                # » de la fiche projet.
                from sqlalchemy import update as _update

                from app.models.project import Project as _Project

                await db.execute(
                    _update(_Project)
                    .where(_Project.soumission_id == int(obj.id))
                    .values(budget=new_total)
                )
                await db.flush()
        if model is Facture:
            # La facture est « émise » le jour où elle quitte l'état
            # brouillon (envoi au client). issued_at n'est fixé qu'une
            # fois : un changement de statut ultérieur ne le déplace pas.
            new_status = getattr(obj, "status", None)
            if (
                prev_status == FactureStatus.DRAFT.value
                and new_status != FactureStatus.DRAFT.value
                and getattr(obj, "issued_at", None) is None
            ):
                obj.issued_at = datetime.now(timezone.utc)
                await db.flush()
            # (Re)classement dans un projet → on pousse vers QB pour
            # rattacher le REVENU au bon projet (CustomerRef = sous-client,
            # ClassRef = chantier). Push délibéré (non conditionné à
            # l'interrupteur de migration). On ne pousse que si la facture
            # est déjà dans QB (qbo_invoice_id) OU sortie de brouillon, pour
            # ne pas créer une Invoice à partir d'un brouillon.
            new_proj = getattr(obj, "project_id", None)
            already_in_qbo = bool(getattr(obj, "qbo_invoice_id", None))
            if (
                new_proj != prev_doc_project_id
                and (obj.status or "") not in ("draft", "void")
                and (already_in_qbo or new_proj is not None)
            ):
                await db.flush()
                import asyncio

                from app.services.qbo_auto_sync import push_facture_now

                asyncio.create_task(push_facture_now(int(obj.id)))
        return read_schema.model_validate(obj)

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_item(item_id: int, db: DBSession, user: AuthWrite):
        crud = GenericCrud(db, model)
        obj = await crud.get(item_id)
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        # Snapshot avant suppression pour le journal d'audit
        # (référence + label visible si dispo).
        snap = {
            "reference": getattr(obj, "reference", None),
            "name": getattr(obj, "name", None)
            or getattr(obj, "title", None)
            or getattr(obj, "full_name", None),
        }
        # Suppression d'une facture : on « dé-refacture » les achats et
        # les heures (punches) qui y étaient rattachés via leurs
        # facture_items, pour qu'ils redeviennent disponibles à la
        # refacturation et que leurs champs (majoration…) se
        # déverrouillent. Le FK est SET NULL mais `invoiced_at` ne se
        # réinitialise pas seul → on remet les deux à NULL ici, AVANT la
        # suppression (après, les facture_items sont déjà cascade-delete).
        if model is Facture:
            from sqlalchemy import select as _select, update as _update
            from app.models.facture_item import FactureItem as _FI

            item_ids = (
                await db.execute(
                    _select(_FI.id).where(_FI.facture_id == item_id)
                )
            ).scalars().all()
            if item_ids:
                await db.execute(
                    _update(Achat)
                    .where(Achat.facture_item_id.in_(item_ids))
                    .values(invoiced_at=None, facture_item_id=None)
                )
                await db.execute(
                    _update(Punch)
                    .where(Punch.facture_item_id.in_(item_ids))
                    .values(invoiced_at=None, facture_item_id=None)
                )

        await crud.delete(obj)
        from app.services.audit import log_action as _log_action

        await _log_action(
            db,
            user=user,
            action=f"{tag}.deleted",
            entity_type=tag,
            entity_id=item_id,
            details=snap,
        )
        # Après suppression d'un PO, on recycle son numéro : on
        # ré-aligne le compteur `next_po_number` sur (max restant + 1).
        # Comme ça, supprimer le dernier PO-0030 fait que le prochain
        # créé reprendra le numéro 0030.
        if model is PurchaseOrder:
            from app.services.numbering import resync_po_counter

            await resync_po_counter(db)

    return router


employes_router = make_crud_router(
    prefix="/employes", tag="employes",
    model=Employe, create_schema=EmployeCreate, update_schema=EmployeUpdate, read_schema=EmployeRead,
)
fournisseurs_router = make_crud_router(
    prefix="/fournisseurs", tag="fournisseurs",
    model=Fournisseur, create_schema=FournisseurCreate, update_schema=FournisseurUpdate, read_schema=FournisseurRead,
)
sous_traitants_router = make_crud_router(
    prefix="/sous-traitants", tag="sous-traitants",
    model=SousTraitant, create_schema=SousTraitantCreate, update_schema=SousTraitantUpdate, read_schema=SousTraitantRead,
)
# Feuille de temps sous-traitant : saisie des heures par projet (admin
# gestion de temps). Lecture/écriture réservées aux managers.
sous_traitant_timesheets_router = make_crud_router(
    prefix="/sous-traitant-timesheets", tag="sous-traitant-timesheets",
    model=SousTraitantTimesheet,
    create_schema=SousTraitantTimesheetCreate,
    update_schema=SousTraitantTimesheetUpdate,
    read_schema=SousTraitantTimesheetRead,
)
# #16 — Catalogue de notes prédéfinies. Lecture ouverte à tout utilisateur
# connecté (insertion dans une soumission), écriture réservée aux managers.
note_templates_router = make_crud_router(
    prefix="/note-templates", tag="note-templates",
    model=NoteTemplate, create_schema=NoteTemplateCreate,
    update_schema=NoteTemplateUpdate, read_schema=NoteTemplateRead,
    require_manager=False,
)
soumissions_router = make_crud_router(
    prefix="/soumissions", tag="soumissions",
    model=Soumission, create_schema=SoumissionCreate, update_schema=SoumissionUpdate, read_schema=SoumissionRead,
)
agenda_router = make_crud_router(
    # Agenda reads must stay open to employees (they need to consult
    # their own schedule). Writes still require manager+.
    prefix="/agenda", tag="agenda",
    model=AgendaEvent, create_schema=AgendaEventCreate, update_schema=AgendaEventUpdate, read_schema=AgendaEventRead,
    require_manager=False,
)
bons_router = make_crud_router(
    prefix="/bons-travail", tag="bons-travail",
    model=BonTravail, create_schema=BonTravailCreate, update_schema=BonTravailUpdate, read_schema=BonTravailRead,
)
punch_router = make_crud_router(
    # Reads stay open: employees consult their own punches via
    # /punch/me. Writes (admin edits) still require manager+.
    prefix="/punch", tag="punch",
    model=Punch, create_schema=PunchCreate, update_schema=PunchUpdate, read_schema=PunchRead,
    require_manager=False,
)
factures_router = make_crud_router(
    prefix="/factures", tag="factures",
    model=Facture, create_schema=FactureCreate, update_schema=FactureUpdate, read_schema=FactureRead,
)
achats_router = make_crud_router(
    prefix="/achats", tag="achats",
    model=Achat, create_schema=AchatCreate, update_schema=AchatUpdate, read_schema=AchatRead,
)
purchase_orders_router = make_crud_router(
    prefix="/purchase-orders", tag="purchase-orders",
    model=PurchaseOrder,
    create_schema=PurchaseOrderCreate,
    update_schema=PurchaseOrderUpdate,
    read_schema=PurchaseOrderRead,
)
