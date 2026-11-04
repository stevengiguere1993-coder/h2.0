"""Achat supprimé dans Kratos → sa transaction QuickBooks disparaît aussi.

Steven (2026-11-04, à propos de la dépense Amazon #539 restée orpheline
dans QB après sa suppression dans Kratos) : « si on supprime dans Kratos,
il faudrait que cela supprime dans QuickBooks ».

Règles :
- la dépense (Purchase) ou la facture fournisseur (Bill) liée est
  SUPPRIMÉE dans QB, ainsi que le paiement (BillPayment) que Kratos y a
  enregistré et la pièce jointe (reçu) ;
- reçu DIVISÉ : seulement quand la dernière part s'en va — tant qu'il
  reste des parts, la transaction est réécrite sans la ligne
  (achat_divise.retirer_part_annulee) ;
- transaction PARTAGÉE avec d'autres achats Kratos (facture fractionnée
  importée de QB : plusieurs achats, un par projet, sans groupe) : on ne
  touche pas à QB, l'achat perd seulement son lien ;
- un refus de QuickBooks (transaction rapprochée, payée dans QB…) lève
  ``AchatSyncError`` : l'appelant refuse la suppression (409) et rien ne
  change — Kratos ne diverge jamais de QuickBooks en silence.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.quickbooks import get_qbo
from app.models.achat import Achat, AchatStatus

log = logging.getLogger(__name__)


async def _partagee(db: AsyncSession, achat: Achat) -> bool:
    """La transaction QB de ``achat`` porte-t-elle aussi d'autres achats
    Kratos actifs (hors son propre groupe) ?"""
    ids = {
        str(v)
        for v in (achat.qbo_bill_id, achat.qbo_purchase_id)
        if v
    }
    if not ids:
        return False
    q = select(Achat.id).where(
        Achat.id != achat.id,
        Achat.status != AchatStatus.CANCELLED.value,
        or_(Achat.qbo_bill_id.in_(ids), Achat.qbo_purchase_id.in_(ids)),
    )
    if achat.groupe_id:
        q = q.where(
            or_(Achat.groupe_id.is_(None), Achat.groupe_id != achat.groupe_id)
        )
    return (await db.execute(q.limit(1))).first() is not None


async def supprimer_miroir_qb(db: AsyncSession, achat: Achat) -> Dict[str, Any]:
    """Supprime dans QuickBooks la transaction de l'achat (voir module).
    Retourne ce qui a été fait ; lève ``AchatSyncError`` si QB refuse."""
    from app.services.achat_divise import parts_du_groupe
    from app.services.achat_piece_qbo import retirer_piece_qb, transaction_qb
    from app.services.achat_qbo import AchatSyncError

    if not (achat.qbo_bill_id or achat.qbo_purchase_id):
        return {"skipped": "non lié à QuickBooks"}
    if achat.groupe_id:
        restantes = [
            s for s in await parts_du_groupe(db, achat) if s.id != achat.id
        ]
        if restantes:
            return {"skipped": "d'autres parts du reçu restent"}
    if await _partagee(db, achat):
        log.info(
            "Achat %s : transaction QB partagée avec d'autres achats → "
            "conservée dans QuickBooks",
            achat.id,
        )
        return {"skipped": "transaction partagée"}

    qbo = get_qbo()
    await qbo._load_refresh_from_db()
    if not getattr(qbo, "ready", False):
        raise AchatSyncError(
            "QuickBooks n'est pas configuré : impossible d'y supprimer la "
            "transaction de cet achat."
        )

    txn = await transaction_qb(qbo, achat)
    if txn is None:
        return {"skipped": "déjà absente de QuickBooks"}
    type_qb, id_qb = txn

    out: Dict[str, Any] = {"type": type_qb, "id": id_qb}
    if achat.qbo_bill_payment_id and type_qb == "Bill":
        out["paiement_supprime"] = bool(
            await qbo.delete_bill_payment(str(achat.qbo_bill_payment_id))
        )
    ok = (
        await qbo.delete_bill(id_qb)
        if type_qb == "Bill"
        else await qbo.delete_purchase(id_qb)
    )
    if not ok:
        libelle = "la facture fournisseur" if type_qb == "Bill" else "la dépense"
        raise AchatSyncError(
            f"QuickBooks a refusé de supprimer {libelle} {id_qb} (payée "
            "ou rapprochée dans QuickBooks ?). Supprime-la d'abord dans "
            "QuickBooks, puis reprends ici."
        )
    if achat.qbo_attachable_id:
        out["piece_retiree"] = await retirer_piece_qb(
            qbo, str(achat.qbo_attachable_id)
        )
    log.info(
        "Achat %s supprimé dans Kratos → %s QB %s supprimée",
        achat.id, type_qb, id_qb,
    )
    return out


# ── Sens inverse : supprimée DANS QuickBooks → disparaît de Kratos ─────


def _disparue_de_qb(exc: Exception) -> bool:
    """L'erreur QB dit que l'objet n'existe plus (supprimé) — et non que
    QuickBooks est injoignable."""
    msg = str(exc).lower()
    return (
        "object not found" in msg
        or "errorcode=610" in msg
        or "code': '610'" in msg
        or "'code': '610'" in msg
        or "introuvable" in msg
    )


async def _encore_dans_qb(qbo: Any, type_qb: str, id_qb: str) -> Optional[bool]:
    """True si la transaction existe toujours dans QB, False si elle en a
    disparu, None si QB ne répond pas (on ne décide rien)."""
    try:
        if type_qb == "Bill":
            await qbo.get_bill(id_qb)
        else:
            await qbo.get_purchase(id_qb)
        return True
    except Exception as exc:  # noqa: BLE001
        return False if _disparue_de_qb(exc) else None


async def supprimer_depuis_qb(
    db: AsyncSession, qbo: Any, *, type_qb: str, id_qb: str
) -> Dict[str, Any]:
    """Transaction supprimée DANS QuickBooks (webhook « Delete ») → les
    achats Kratos qui la portaient disparaissent aussi (Steven
    2026-11-04 : « si on supprime une dépense dans QB, elle se supprime
    dans Kratos »).

    Garde-fous :
    - on vérifie auprès de QB que la transaction a bien disparu (un
      événement rejoué ou QB injoignable ne supprime rien) ;
    - chaque achat est relu sous le verrou de sa synchro : un achat dont
      Kratos vient de REMPLACER la transaction QB (doublon nettoyé,
      recréation) n'est plus lié à l'ancien Id → ignoré ;
    - un achat déjà REFACTURÉ au client (ligne de facture) n'est pas
      détruit : il est annulé et délié, pour ne pas casser la facture.
    Chaque geste est journalisé (audit « achats.deleted » /
    « achats.cancelled », source quickbooks)."""
    from app.services.achat_qbo import verrou_achat
    from app.services.audit import log_action

    id_qb = str(id_qb)
    out: Dict[str, Any] = {"type": type_qb, "id": id_qb, "supprimes": [], "annules": []}
    lies = (
        await db.execute(
            select(Achat.id, Achat.groupe_id).where(
                or_(Achat.qbo_bill_id == id_qb, Achat.qbo_purchase_id == id_qb)
            )
        )
    ).all()
    if not lies:
        return out
    encore = await _encore_dans_qb(qbo, type_qb, id_qb)
    if encore is None:
        log.warning(
            "QB %s %s : suppression annoncée mais QuickBooks ne répond pas → "
            "rien n'est touché dans Kratos",
            type_qb, id_qb,
        )
        out["skipped"] = "quickbooks injoignable"
        return out
    if encore:
        out["skipped"] = "toujours dans QuickBooks"
        return out

    for aid, gid in lies:
        async with verrou_achat(int(aid), gid):
            achat = await db.get(Achat, int(aid))
            if achat is None:
                continue
            if id_qb not in (str(achat.qbo_bill_id or ""), str(achat.qbo_purchase_id or "")):
                continue  # relié ailleurs entre-temps
            details = {
                "source": "quickbooks",
                "type_qb": type_qb,
                "qbo_id": id_qb,
                "description": achat.description,
                "amount": float(achat.amount or 0),
                "project_id": achat.project_id,
            }
            achat.qbo_bill_id = None
            achat.qbo_purchase_id = None
            achat.qbo_sync_token = None
            achat.qbo_bill_payment_id = None
            achat.qbo_attachable_id = None
            if achat.invoiced_at or achat.facture_item_id:
                achat.status = AchatStatus.CANCELLED.value
                out["annules"].append(int(aid))
                await log_action(
                    db, user=None, action="achats.cancelled", entity_type="achats",
                    entity_id=int(aid), details={**details, "raison": "refacturé : annulé, non supprimé"},
                )
                log.warning(
                    "QB %s %s supprimée : achat %s déjà refacturé → annulé et délié",
                    type_qb, id_qb, aid,
                )
            else:
                await db.delete(achat)
                out["supprimes"].append(int(aid))
                await log_action(
                    db, user=None, action="achats.deleted", entity_type="achats",
                    entity_id=int(aid), details=details,
                )
                log.info("QB %s %s supprimée → achat %s supprimé", type_qb, id_qb, aid)
            await db.flush()
    return out
