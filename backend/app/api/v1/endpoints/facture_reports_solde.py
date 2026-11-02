"""Report des petits soldes impayés sur la prochaine facture du client.

    GET    /api/v1/factures/{facture_id}/reports-solde
    POST   /api/v1/factures/{facture_id}/reports-solde
    DELETE /api/v1/factures/{facture_id}/reports-solde/{report_id}
    GET    /api/v1/reports-solde?client_id=&statut=

Le report se fait aussi tout seul quand une facture est classée « payée »
avec un petit solde restant (voir business.update_item). Logique et
écritures QuickBooks : app.services.facture_report_solde.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.facture import Facture
from app.models.facture_report_solde import FactureReportSolde
from app.services import facture_report_solde as svc

log = logging.getLogger(__name__)
router = APIRouter(tags=["factures"])


async def _facture(db, facture_id: int) -> Facture:
    fa = await db.get(Facture, facture_id)
    if fa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable")
    return fa


async def _refs(db, reps: List[FactureReportSolde]) -> Dict[int, str]:
    ids = {r.origine_facture_id for r in reps} | {
        r.cible_facture_id for r in reps if r.cible_facture_id
    }
    if not ids:
        return {}
    return {
        int(i): str(ref)
        for i, ref in (
            await db.execute(
                select(Facture.id, Facture.reference).where(Facture.id.in_(ids))
            )
        ).all()
    }


@router.get(
    "/factures/{facture_id}/reports-solde",
    summary="Soldes reportés de cette facture et soldes reportés sur elle",
)
async def reports_de_la_facture(
    facture_id: int, db: DBSession, _: CurrentUser
) -> Dict[str, Any]:
    fa = await _facture(db, facture_id)
    reps = (
        await db.execute(
            select(FactureReportSolde)
            .where(
                (FactureReportSolde.origine_facture_id == facture_id)
                | (FactureReportSolde.cible_facture_id == facture_id)
            )
            .order_by(FactureReportSolde.id.asc())
        )
    ).scalars().all()
    refs = await _refs(db, list(reps))
    solde = await svc.solde_restant(db, fa)
    statut = fa.status or ""
    return {
        "reportes": [
            svc.lire(r, refs) for r in reps if r.origine_facture_id == facture_id
        ],
        "recus": [
            svc.lire(r, refs)
            for r in reps
            if r.cible_facture_id == facture_id and r.origine_facture_id != facture_id
        ],
        "solde_restant": solde,
        "plafond": svc.plafond(),
        "reportable": (
            statut not in ("draft", "void")
            and bool(fa.client_id)
            and 0.01 <= solde <= svc.plafond() + 0.005
        ),
    }


@router.post(
    "/factures/{facture_id}/reports-solde",
    status_code=status.HTTP_201_CREATED,
    summary="Reporter le petit solde de la facture sur la prochaine facture du client",
)
async def reporter(
    facture_id: int, db: DBSession, user: CurrentUser
) -> Dict[str, Any]:
    fa = await _facture(db, facture_id)
    try:
        rep = await svc.reporter_solde(db, fa, user_id=getattr(user, "id", None))
    except svc.ReportImpossible as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    # QuickBooks d'abord : si l'Invoice d'origine est dans QB et que QB
    # refuse le Payment qui ferme le solde, rien n'est enregistré.
    from app.services.facture_qbo import quickbooks_branche

    if quickbooks_branche() and fa.qbo_invoice_id:
        from app.services.qbo_auto_sync import verrou_facture

        async with verrou_facture(facture_id):
            try:
                await svc.pousser_report_qbo(db, rep)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                log.error("Report du solde facture %s refusé par QB : %s", facture_id, exc)
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"QuickBooks a refusé de fermer le solde : {exc}",
                )
            await db.commit()
    else:
        await db.commit()
    await db.refresh(rep)
    return svc.lire(rep, await _refs(db, [rep]))


@router.delete(
    "/factures/{facture_id}/reports-solde/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Annuler un report de solde (la facture d'origine redevient ouverte)",
)
async def annuler(
    facture_id: int, report_id: int, db: DBSession, _: CurrentUser
) -> None:
    rep = await db.get(FactureReportSolde, report_id)
    if rep is None or facture_id not in (rep.origine_facture_id, rep.cible_facture_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report introuvable")
    try:
        await svc.annuler_report(db, rep)
    except svc.ReportImpossible as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    await db.commit()


@router.get(
    "/reports-solde",
    summary="Liste des petits soldes reportés (par client / statut)",
)
async def liste(
    db: DBSession,
    _: CurrentUser,
    client_id: Optional[int] = Query(default=None),
    statut: Optional[str] = Query(default=None, pattern="^(en_attente|applique|annule)$"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> List[Dict[str, Any]]:
    stmt = select(FactureReportSolde).order_by(FactureReportSolde.id.desc()).limit(limit)
    if client_id is not None:
        stmt = stmt.where(FactureReportSolde.client_id == client_id)
    if statut:
        stmt = stmt.where(FactureReportSolde.statut == statut)
    reps = list((await db.execute(stmt)).scalars().all())
    refs = await _refs(db, reps)
    return [svc.lire(r, refs) for r in reps]
