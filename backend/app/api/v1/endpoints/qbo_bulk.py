"""Synchro QBO de masse — endpoint RAPPORT dry-run (lecture seule).

Aucune écriture dans QuickBooks. Réservé admin/propriétaire. Sert à
valider, AVANT tout envoi réel, ce que la migration ferait (clients,
projets, factures) et l'état de liaison QBO actuel.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DBSession, RequireAdminOrOwner
from app.models.project import Project
from app.services.qbo_auto_sync import QBO_AUTO_SYNC_KEY
from app.services.qbo_bulk_sync import (
    dry_run_report,
    reset_links,
    run_migration,
)
from app.services.qbo_invoice_pull import pull_invoices_from_qbo

router = APIRouter(prefix="/qbo", tags=["qbo-bulk"])


class QboAutoSync(BaseModel):
    enabled: bool


@router.get("/auto-sync", response_model=QboAutoSync)
async def get_auto_sync(db: DBSession, _: RequireAdminOrOwner) -> QboAutoSync:
    # SQL minimal + tolérant : si la table n'existe pas / autre souci, on
    # renvoie « désactivé » (fail-closed) sans 500.
    from sqlalchemy import text

    try:
        row = (
            await db.execute(
                text(
                    "SELECT enabled FROM automation_settings WHERE key = :k"
                ),
                {"k": QBO_AUTO_SYNC_KEY},
            )
        ).first()
        return QboAutoSync(enabled=bool(row[0]) if row else False)
    except Exception:  # noqa: BLE001
        return QboAutoSync(enabled=False)


@router.put("/auto-sync", response_model=QboAutoSync)
async def set_auto_sync(
    data: QboAutoSync, db: DBSession, user: RequireAdminOrOwner
) -> QboAutoSync:
    # Robuste : garantit la table (au cas où create_all ne l'aurait pas
    # créée en prod), puis UPSERT minimal sur key/enabled — sans toucher
    # aux colonnes de timestamp. En cas d'échec, on REMONTE l'erreur réelle
    # (au lieu d'un 500 opaque) pour pouvoir diagnostiquer.
    from sqlalchemy import text

    try:
        await db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS automation_settings ("
                "key VARCHAR(64) PRIMARY KEY, "
                "enabled BOOLEAN NOT NULL DEFAULT true, "
                "config_json TEXT, "
                "updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "
                "updated_by_user_id INTEGER)"
            )
        )
        await db.execute(
            text(
                "INSERT INTO automation_settings (key, enabled) "
                "VALUES (:k, :e) "
                "ON CONFLICT (key) DO UPDATE SET enabled = EXCLUDED.enabled"
            ),
            {"k": QBO_AUTO_SYNC_KEY, "e": bool(data.enabled)},
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"auto-sync write failed: {type(exc).__name__}: {exc}",
        )
    return QboAutoSync(enabled=bool(data.enabled))


@router.get("/bulk-report")
async def bulk_report(
    db: DBSession,
    _: RequireAdminOrOwner,
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (test sur 1 dossier). Vide = tous.",
    ),
) -> dict:
    return await dry_run_report(db, client_id=client_id)


@router.post("/bulk-sync")
async def bulk_sync(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description=(
            "true (défaut) = rapport seul, AUCUNE écriture. "
            "false = migration RÉELLE dans QuickBooks (irréversible)."
        ),
    ),
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (test sur 1 dossier). Vide = tous.",
    ),
) -> dict:
    if dry_run:
        return await dry_run_report(db, client_id=client_id)
    # Écritures réelles. On COMMITTE ICI (dans le try) pour capturer la
    # VRAIE cause si le commit échoue — sinon le commit de la dépendance DB
    # lève hors de notre try → « Internal Server Error » opaque.
    try:
        result = await run_migration(db, client_id=client_id)
        await db.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Migration: {type(exc).__name__}: {str(exc)[:600]}",
        )


@router.post("/reclass-projects")
async def reclass_projects(
    db: DBSession,
    _: RequireAdminOrOwner,
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client. Vide = toutes les factures.",
    ),
) -> dict:
    """Ré-attribue dans QuickBooks les factures (et coûts) déjà liés à QB
    au bon PROJET — CustomerRef = sous-client (Job), ClassRef = chantier.

    Utile quand des projets ont été créés APRÈS l'envoi des factures : les
    Invoices QB pointaient sur le client parent (sans classe), donc le
    revenu n'apparaissait pas dans l'onglet Projets et les montants QB ≠
    Kratos. Ré-pousse chaque enregistrement (sparse update idempotent —
    aucune création de doublon). Ne touche QUE les enregistrements ayant à
    la fois un projet ET un id QB.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.achat import Achat
    from app.models.facture import Facture
    from app.services.achat_qbo import sync_achat_to_qbo
    from app.services.facture_qbo import sync_facture_to_qbo

    out: dict = {
        "factures_repushed": 0,
        "factures_failed": 0,
        "achats_repushed": 0,
        "achats_failed": 0,
        "errors": [],
    }

    # On ne lit que des IDs sur la session de la requête (lecture seule) ;
    # chaque push se fait dans une session FRAÎCHE dédiée. Évite de mélanger
    # des commits manuels avec la session de requête (dont le teardown
    # committait à son tour → 500).
    fstmt = select(Facture.id).where(
        Facture.project_id.is_not(None),
        Facture.qbo_invoice_id.is_not(None),
    )
    if client_id is not None:
        fstmt = fstmt.where(Facture.client_id == client_id)
    facture_ids = [int(i) for i in (await db.execute(fstmt)).scalars().all()]

    # Achats liés via un BILL QB (qbo_bill_id) → MAJ Class/Customer par
    # sparse update propre. On EXCLUT les Purchases importés (qbo_purchase_id
    # seul) : un re-push les recréerait en doublon (mode de paiement non
    # mappé). Ceux-là restent à corriger côté QB.
    astmt = select(Achat.id).where(
        Achat.project_id.is_not(None),
        Achat.qbo_bill_id.is_not(None),
    )
    if client_id is not None:
        from app.models.project import Project as _Project

        proj_ids = (
            await db.execute(
                select(_Project.id).where(_Project.client_id == client_id)
            )
        ).scalars().all()
        astmt = astmt.where(Achat.project_id.in_(list(proj_ids) or [-1]))
    achat_ids = [int(i) for i in (await db.execute(astmt)).scalars().all()]

    for fid in facture_ids:
        try:
            async with AsyncSessionLocal() as s:
                await sync_facture_to_qbo(s, fid)
                await s.commit()
            out["factures_repushed"] += 1
        except Exception as exc:  # noqa: BLE001
            out["factures_failed"] += 1
            if len(out["errors"]) < 20:
                out["errors"].append(f"facture {fid}: {str(exc)[:160]}")

    for aid in achat_ids:
        try:
            async with AsyncSessionLocal() as s:
                await sync_achat_to_qbo(s, aid)
                await s.commit()
            out["achats_repushed"] += 1
        except Exception as exc:  # noqa: BLE001
            out["achats_failed"] += 1
            if len(out["errors"]) < 40:
                out["errors"].append(f"achat {aid}: {str(exc)[:160]}")

    return out


@router.post("/reset-links")
async def reset_links_endpoint(
    db: DBSession,
    _: RequireAdminOrOwner,
    client_id: Optional[int] = Query(default=None),
    payments_only: bool = Query(
        default=False,
        description=(
            "true = n'efface QUE les liens de paiement (garde client / "
            "projet / facture) → re-pousser les paiements sans recréer de "
            "doublon."
        ),
    ),
) -> dict:
    # Efface les ID QBO côté Kratos pour re-migrer proprement (ne touche
    # pas QuickBooks — supprime d'abord les fiches dans QB).
    return await reset_links(
        db, client_id=client_id, payments_only=payments_only
    )


@router.get("/projects")
async def list_qbo_projects(
    db: DBSession, _: RequireAdminOrOwner
) -> dict:
    """Liste les vrais projets/sous-clients QBO existants (onglet Projets),
    pour relier un projet Kratos à l'un d'eux. Lecture seule."""
    from app.integrations.quickbooks import QuickBooksError, get_qbo

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not qbo.ready:
        return {"error": "QuickBooks non connecté (OAuth).", "projects": []}
    try:
        projects = await qbo.list_projects()
    except QuickBooksError as exc:
        return {"error": f"Requête QB échouée : {exc}", "projects": []}
    return {"projects": projects}


class LinkProject(BaseModel):
    project_id: int
    qbo_job_id: Optional[str] = None


@router.post("/link-project")
async def link_project(
    data: LinkProject, db: DBSession, _: RequireAdminOrOwner
) -> dict:
    """Relie (ou délie) un projet Kratos à un vrai projet/sous-client QBO.

    `qbo_job_id` = l'Id du projet QB (issu de GET /qbo/projects). Passer
    `null`/absent pour défaire la liaison. Une fois lié, factures et coûts
    se rattachent automatiquement à ce projet dans QB.
    """
    proj = (
        await db.execute(
            select(Project).where(Project.id == data.project_id)
        )
    ).scalar_one_or_none()
    if proj is None:
        return {"error": f"Projet {data.project_id} introuvable."}
    jid = (data.qbo_job_id or "").strip() or None
    proj.qbo_job_id = jid
    await db.flush()
    return {"project_id": proj.id, "qbo_job_id": proj.qbo_job_id}


@router.post("/pull-invoices")
async def pull_invoices(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description=(
            "true (défaut) = aperçu, aucune écriture. false = importe "
            "réellement dans Kratos."
        ),
    ),
    since_days: int = Query(default=180, ge=1, le=3650),
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (aperçu détaillé). Vide = tous.",
    ),
) -> dict:
    # Importe les factures QB rattachées à un projet (Job). Une facture QB
    # SANS projet n'est PAS importée.
    return await pull_invoices_from_qbo(
        db, since_days=since_days, dry_run=dry_run, client_id=client_id
    )


@router.post("/pull-costs")
async def pull_costs(
    db: DBSession,
    _: RequireAdminOrOwner,
    dry_run: bool = Query(
        default=True,
        description="true (défaut) = aperçu ; false = importe dans Kratos.",
    ),
    since_days: int = Query(default=180, ge=1, le=3650),
    client_id: Optional[int] = Query(
        default=None,
        description="Limiter à un client (aperçu détaillé). Vide = tous.",
    ),
) -> dict:
    # Importe les Bills (factures fournisseurs à payer) + Purchases
    # (dépenses) QB rattachés à un PROJET (sous-client). Sans projet → pas
    # d'import.
    from app.services.qbo_cost_pull import pull_project_costs_from_qbo

    return await pull_project_costs_from_qbo(
        db, since_days=since_days, dry_run=dry_run, client_id=client_id
    )
