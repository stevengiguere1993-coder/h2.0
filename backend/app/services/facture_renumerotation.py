"""Renumérotation d'une série de factures sortie de la suite (2026-11-05).

Steven : « Pourquoi mes numéros de factures ont fait un bond, ramener ça à
la suite d'où j'étais après 171. Je ne devrais pas être dans les 10..
Mettre à jour les factures envoyées dans les 10.. en ordre d'envoi. »

Cause : le recalage du compteur (« plus haut numéro Kratos ou QuickBooks
+ 1 », 2026-10-17) a suivi un numéro de QuickBooks hors série (1042) ;
la facture suivante est partie en 1043. Le recalage écarte maintenant les
numéros hors série (numbering.ECART_MAX_QB). Ce service remet les
factures déjà numérotées dans les 10xx à la suite de la série :

- factures de Kratos dont le numéro est >= ``seuil`` (1000), brouillons
  exclus, dans l'ordre d'ENVOI (``issued_at``, puis création) ;
- nouveau numéro = suite de la série (plus haut numéro sous le seuil + 1,
  soit 172), en sautant tout numéro déjà pris dans Kratos ou par une
  autre facture de QuickBooks ;
- la facture liée à QuickBooks y est remise à jour (mise à jour complète,
  DocNumber compris) AVANT de passer à la suivante ; si QuickBooks
  refuse, la facture garde son ancien numéro et on s'arrête (la suite
  reste dans l'ordre) ;
- note interne datée + journal ``facture.renumerotee`` ;
- compteur remis à (dernier numéro donné + 1) — ABAISSÉ exprès ici.

``simuler`` (défaut) : le plan seulement, rien n'est écrit. Le plan liste
aussi les factures QuickBooks hors série qui ne sont pas de Kratos (la
cause du saut).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.facture import Facture
from app.models.numbering_counter import NumberingCounter

log = logging.getLogger(__name__)

#: Numéros à partir desquels une facture est « hors série ».
SEUIL_DEFAUT = 1000


def _num(ref: Optional[str]) -> Optional[int]:
    r = (ref or "").strip()
    return int(r) if r.isdigit() else None


def _cle_envoi(fa: Facture):
    return (fa.issued_at or fa.created_at, fa.created_at, fa.id)


async def _qbo_pret():
    from app.integrations.quickbooks import get_qbo

    qbo = get_qbo()
    try:
        await qbo._load_refresh_from_db()
    except Exception as exc:  # noqa: BLE001
        log.warning("QuickBooks : chargement des jetons impossible : %s", exc)
    return qbo if getattr(qbo, "ready", False) else None


async def _invoice_qb(qbo, ref: str) -> Optional[Dict[str, Any]]:
    if qbo is None:
        return None
    return await qbo.find_invoice_by_docnumber(ref)


async def _factures_qb_hors_serie(
    db: AsyncSession, qbo, seuil: int
) -> list[Dict[str, Any]]:
    """Factures QuickBooks numérotées >= seuil qui ne sont liées à aucune
    facture de Kratos (la cause probable du saut)."""
    if qbo is None:
        return []
    try:
        rows = await qbo.query(
            "SELECT * FROM Invoice ORDERBY MetaData.CreateTime DESC MAXRESULTS 1000"
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Lecture des factures QuickBooks impossible : %s", exc)
        return []
    lies = {
        str(i)
        for i in (
            await db.execute(
                select(Facture.qbo_invoice_id).where(Facture.qbo_invoice_id.is_not(None))
            )
        ).scalars().all()
    }
    out = []
    for r in rows:
        n = _num(str(r.get("DocNumber") or ""))
        if n is None or n < seuil or str(r.get("Id") or "") in lies:
            continue
        out.append(
            {
                "qbo_invoice_id": str(r.get("Id") or ""),
                "numero": str(n),
                "client": (r.get("CustomerRef") or {}).get("name"),
                "date": r.get("TxnDate"),
                "total": r.get("TotalAmt"),
                "solde": r.get("Balance"),
                "cree_le": (r.get("MetaData") or {}).get("CreateTime"),
                "memo": r.get("PrivateNote"),
                "lignes": lignes_invoice_qb(r),
            }
        )
    return sorted(out, key=lambda x: int(x["numero"]))


def lignes_invoice_qb(inv: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Les lignes d'une Invoice QB, lisibles : produit, description,
    quantité, prix unitaire, montant (lignes de total exclues)."""
    out = []
    for li in inv.get("Line") or []:
        if li.get("DetailType") not in ("SalesItemLineDetail", "DescriptionOnly"):
            continue
        det = li.get("SalesItemLineDetail") or {}
        out.append(
            {
                "produit": (det.get("ItemRef") or {}).get("name"),
                "description": li.get("Description"),
                "quantite": det.get("Qty"),
                "prix_unitaire": det.get("UnitPrice"),
                "montant": li.get("Amount"),
            }
        )
    return out


async def renumeroter_facture_qb_seule(
    db: AsyncSession, *, qbo_invoice_id: str, numero: Optional[str] = None
) -> Dict[str, Any]:
    """Donne un numéro de la série de Kratos à une facture QuickBooks qui
    N'EST PAS dans Kratos (faite à la main dans QuickBooks, ex. 1044 du
    2026-10-27). ``numero`` vide = prochain numéro du compteur (consommé) ;
    sinon le numéro demandé, s'il est libre dans Kratos et QuickBooks, et
    le compteur passe au-dessus. Mise à jour « sparse » du DocNumber sur
    le SyncToken relu. Committe."""
    from app.services.audit import log_action
    from app.services.numbering import (
        attribuer_numero_libre,
        numero_pris_dans_kratos,
    )

    qbo = await _qbo_pret()
    if qbo is None:
        raise RuntimeError("QuickBooks n'est pas connecté.")
    lie = (
        await db.execute(
            select(Facture.id, Facture.reference).where(
                Facture.qbo_invoice_id == str(qbo_invoice_id)
            )
        )
    ).first()
    if lie is not None:
        raise ValueError(
            f"Cette Invoice QuickBooks est la facture Kratos {lie[1]} (#{lie[0]}) : "
            "renuméroter la facture Kratos, pas l'Invoice."
        )
    cur = await qbo.get_invoice(str(qbo_invoice_id))
    cur = cur.get("Invoice") or cur
    if not cur.get("Id"):
        raise ValueError(f"Invoice QuickBooks {qbo_invoice_id} introuvable.")
    ancien = str(cur.get("DocNumber") or "")
    if numero:
        numero = str(numero).strip()
        if not numero.isdigit():
            raise ValueError("Le numéro doit être un nombre.")
        if await numero_pris_dans_kratos(db, numero) is not None:
            raise ValueError(f"Le numéro {numero} est déjà porté par une facture Kratos.")
        autre = await qbo.find_invoice_by_docnumber(numero)
        if autre and str(autre.get("Id")) != str(cur["Id"]):
            raise ValueError(
                f"Le numéro {numero} est déjà pris dans QuickBooks "
                f"({(autre.get('CustomerRef') or {}).get('name')})."
            )
    else:
        # Prochain numéro libre de la série, via un porteur jetable (pas de
        # facture Kratos à créer).
        class _Porteur:
            id = None
            reference = None

        porteur = _Porteur()
        await attribuer_numero_libre(db, porteur)
        numero = str(porteur.reference)
    rep = await qbo.create_invoice(
        {
            "Id": str(cur["Id"]),
            "SyncToken": str(cur.get("SyncToken") or "0"),
            "sparse": True,
            "DocNumber": numero[:21],
        }
    )
    inv = rep.get("Invoice") or rep
    nouveau = str(inv.get("DocNumber") or "")
    if nouveau != numero:
        await db.rollback()
        raise RuntimeError(f"QuickBooks a gardé le numéro {nouveau or ancien}.")
    # Compteur au-dessus du numéro donné.
    row = (
        await db.execute(
            select(NumberingCounter.next_facture_number).where(NumberingCounter.id == 1)
        )
    ).scalar_one_or_none()
    if row is None or int(row) <= int(numero):
        await db.execute(
            update(NumberingCounter)
            .where(NumberingCounter.id == 1)
            .values(next_facture_number=int(numero) + 1)
        )
    await log_action(
        db,
        user=None,
        action="facture.qb_renumerotee",
        entity_type="facture",
        entity_id=None,
        details={
            "qbo_invoice_id": str(cur["Id"]),
            "ancien": ancien,
            "nouveau": numero,
            "client": (cur.get("CustomerRef") or {}).get("name"),
            "total": cur.get("TotalAmt"),
        },
    )
    await db.commit()
    compteur = (
        await db.execute(
            select(NumberingCounter.next_facture_number).where(NumberingCounter.id == 1)
        )
    ).scalar_one_or_none()
    return {
        "qbo_invoice_id": str(cur["Id"]),
        "ancien": ancien,
        "nouveau": numero,
        "client": (cur.get("CustomerRef") or {}).get("name"),
        "total": cur.get("TotalAmt"),
        "compteur": compteur,
    }


async def renumeroter_factures_hors_serie(
    db: AsyncSession,
    *,
    seuil: int = SEUIL_DEFAUT,
    premier: Optional[int] = None,
    simuler: bool = True,
) -> Dict[str, Any]:
    """Voir le module. Committe chaque facture renumérotée (sauf en
    simulation, où rien n'est écrit)."""
    factures = list((await db.execute(select(Facture))).scalars().all())
    serie = [n for n in (_num(f.reference) for f in factures) if n is not None and n < seuil]
    suite = premier if premier is not None else (max(serie) + 1 if serie else 1)
    a_traiter = sorted(
        [
            f for f in factures
            if (_num(f.reference) or 0) >= seuil and (f.status or "") != "draft"
        ],
        key=_cle_envoi,
    )
    refs_kratos = {(f.reference or "").strip() for f in factures}
    qbo = await _qbo_pret()
    if not simuler and qbo is None and any(f.qbo_invoice_id for f in a_traiter):
        raise RuntimeError(
            "QuickBooks n'est pas connecté : impossible de renuméroter des "
            "factures qui y sont synchronisées."
        )

    # Plan : numéros libres dans Kratos ET QuickBooks, dans l'ordre d'envoi.
    plan: list[Dict[str, Any]] = []
    pris_qb: list[Dict[str, Any]] = []
    cand = suite
    for fa in a_traiter:
        while True:
            ref = str(cand)
            cand += 1
            if ref in refs_kratos:
                continue
            try:
                inv = await _invoice_qb(qbo, ref)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Vérification du numéro {ref} dans QuickBooks impossible : {exc}"
                ) from exc
            if inv and str(inv.get("Id") or "") != str(fa.qbo_invoice_id or ""):
                pris_qb.append(
                    {
                        "numero": ref,
                        "qbo_invoice_id": str(inv.get("Id") or ""),
                        "client": (inv.get("CustomerRef") or {}).get("name"),
                        "total": inv.get("TotalAmt"),
                    }
                )
                continue
            break
        plan.append(
            {
                "facture_id": fa.id,
                "ancien": fa.reference,
                "nouveau": ref,
                "envoyee_le": fa.issued_at.isoformat() if fa.issued_at else None,
                "statut": fa.status,
                "total": float(fa.total) if fa.total is not None else None,
                "qbo_invoice_id": fa.qbo_invoice_id,
            }
        )
    compteur_vise = (int(plan[-1]["nouveau"]) + 1) if plan else suite
    res: Dict[str, Any] = {
        "simulation": simuler,
        "seuil": seuil,
        "suite_de_la_serie": suite,
        "plan": plan,
        "numeros_sautes_pris_dans_qb": pris_qb,
        "factures_qb_hors_serie": await _factures_qb_hors_serie(db, qbo, seuil),
        "compteur_vise": compteur_vise,
    }
    if simuler:
        await db.rollback()
        return res

    from app.services.audit import log_action
    from app.services.facture_qbo import sync_facture_to_qbo

    faites: list[Dict[str, Any]] = []
    erreur: Optional[Dict[str, Any]] = None
    for etape in plan:
        fa = (
            await db.execute(select(Facture).where(Facture.id == etape["facture_id"]))
        ).scalar_one()
        ancien, nouveau = fa.reference, etape["nouveau"]
        fa.reference = nouveau
        note = (
            f"Numéro changé de {ancien} à {nouveau} : remise dans la suite des "
            "numéros de facture (le compteur avait sauté dans les 10xx)."
        )
        fa.internal_notes = (
            f"{fa.internal_notes.rstrip()}\n" if (fa.internal_notes or "").strip() else ""
        ) + f"{date.today().isoformat()} — {note}"
        await db.flush()
        if fa.qbo_invoice_id:
            try:
                sync = await sync_facture_to_qbo(db, fa.id)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                erreur = {"facture_id": etape["facture_id"], "ancien": ancien, "message": str(exc)}
                log.error("Renumérotation %s → %s refusée par QuickBooks : %s", ancien, nouveau, exc)
                break
            doc_qb = str((await db.execute(
                select(Facture.qbo_doc_number).where(Facture.id == etape["facture_id"])
            )).scalar_one() or "")
            if doc_qb and doc_qb != nouveau:
                await db.rollback()
                erreur = {
                    "facture_id": etape["facture_id"],
                    "ancien": ancien,
                    "message": f"QuickBooks a gardé le numéro {doc_qb}",
                    "synchro": sync,
                }
                break
        await log_action(
            db,
            user=None,
            action="facture.renumerotee",
            entity_type="facture",
            entity_id=etape["facture_id"],
            details={"ancien": ancien, "nouveau": nouveau, "motif": "remise dans la suite"},
        )
        await db.commit()
        faites.append({"facture_id": etape["facture_id"], "ancien": ancien, "nouveau": nouveau})

    # Compteur : juste après le dernier numéro donné (abaissé exprès). Si
    # tout n'a pas été fait, le recalage ordinaire s'en charge.
    if faites and erreur is None:
        await db.execute(
            update(NumberingCounter)
            .where(NumberingCounter.id == 1)
            .values(next_facture_number=compteur_vise)
        )
        await db.commit()
    compteur = (
        await db.execute(
            select(NumberingCounter.next_facture_number).where(NumberingCounter.id == 1)
        )
    ).scalar_one_or_none()
    res.update({"faites": faites, "erreur": erreur, "compteur": compteur})
    return res
