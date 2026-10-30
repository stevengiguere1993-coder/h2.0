"""Reçu DIVISÉ entre plusieurs projets (Steven 2026-10-30).

« Si nous avons des reçus, nous pouvons diviser le reçu entre deux
entreprises : une coche qui permet de dire que deux projets différents
sont touchés par la facture et de séparer le montant qui va dans chacun
des projets ; miroir dans QuickBooks, enregistré sur plusieurs projets. »

Représentation : UN ACHAT PAR PROJET (sa part du HT et des taxes), tous
liés par ``Achat.groupe_id`` = id de la PREMIÈRE part (la « tête »). Les
champs qui décrivent la facture (fournisseur, n° de facture, date, mode de
paiement, nature, PO) sont identiques sur toutes les parts
(:data:`CHAMPS_COMMUNS`) ; projet, montants, description et refacturation
sont propres à chaque part — les coûts par projet, la refacturation et la
page « À refacturer » fonctionnent donc sans rien savoir du groupe.

Côté QuickBooks (services/achat_qbo.py) : UNE transaction (Bill ou
Purchase) à une ligne par part, CustomerRef = projet de la part, taxes du
reçu entier ; son Id est recopié sur toutes les parts. Paiement (mark-paid,
BillPayment) et reçu (image / PDF) valent pour tout le groupe.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achat import KIND_INVENTAIRE, Achat, AchatStatus
from app.models.project import Project
from app.schemas.business import AchatDiviseCreate, AchatPartIn
from app.services.achat_payment import apply_payment_defaults
from app.services.achat_refacturable import refacturable_par_defaut

log = logging.getLogger(__name__)

#: Écart toléré entre la somme des parts saisies et le total du reçu ;
#: l'écart (arrondi) est reporté sur la dernière part.
TOLERANCE = 0.02

#: Champs d'un achat qui décrivent LA FACTURE, communs à toutes les parts
#: d'un reçu divisé (propagés aux sœurs quand on en modifie une). Projet,
#: montants, description et refacturation restent propres à la part.
CHAMPS_COMMUNS = (
    "fournisseur_id",
    "sous_traitant_id",
    "supplier_invoice_number",
    "invoice_date",
    "payment_method",
    "purchase_order_id",
    "kind",
)


class DivisionErreur(ValueError):
    """Division invalide — le message s'adresse à l'utilisateur."""


def _r(v: float) -> float:
    """Arrondi au cent « commercial » (demi-cent vers le haut), sans les
    surprises du round() binaire (2,675 → 2,67)."""
    return float(
        Decimal(str(float(v))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ) + 0.0


def repartir(total: float, poids: Sequence[float]) -> list[float]:
    """Répartit ``total`` au prorata de ``poids`` (arrondi au cent) ; la
    DERNIÈRE part absorbe l'écart d'arrondi, la somme retombe exactement
    sur ``total``. Poids tous nuls → tout sur la dernière part."""
    n = len(poids)
    if n == 0:
        return []
    total = _r(total)
    somme = float(sum(float(w) for w in poids))
    parts: list[float] = []
    cumul = 0.0
    for i, w in enumerate(poids):
        if i == n - 1:
            parts.append(_r(total - cumul))
        else:
            part = _r(total * float(w) / somme) if somme else 0.0
            parts.append(part)
            cumul = _r(cumul + part)
    return parts


def valider_parts(parts: Sequence[AchatPartIn]) -> None:
    """Au moins deux projets, tous distincts, chaque part > 0."""
    if len(parts) < 2:
        raise DivisionErreur(
            "Pour diviser un reçu, choisis au moins deux projets."
        )
    ids = [p.project_id for p in parts]
    if len(set(ids)) != len(ids):
        raise DivisionErreur(
            "Chaque projet ne peut apparaître qu'une fois dans la division."
        )
    if any(float(p.total) <= 0 for p in parts):
        raise DivisionErreur("Chaque part doit avoir un montant supérieur à 0 $.")


def ventiler_parts(
    *,
    amount: float,
    amount_taxes: Optional[float],
    amount_tps: Optional[float],
    amount_tvq: Optional[float],
    totals: Sequence[float],
) -> list[dict]:
    """Montants de chaque part à partir des TTC saisis par projet.

    - les TTC des parts sont ramenés à la somme EXACTE du reçu (un écart
      ≤ :data:`TOLERANCE` est reporté sur la dernière part ; au-delà, la
      saisie est refusée) ;
    - HT de la part au prorata de son TTC (dernière part : le reste) ;
    - taxes de la part = TTC de la part − HT de la part → la somme des
      taxes des parts retombe sur ``amount_taxes`` ;
    - TPS et TVQ de la part au prorata des taxes de la part (sommes
      exactes elles aussi) ; absentes si le reçu ne les ventile pas.

    Chaque part garde donc le TTC que l'utilisateur lui a attribué (à
    l'arrondi près sur la dernière), et le groupe retombe au cent près sur
    les montants du reçu."""
    n = len(totals)
    if n == 0:
        return []
    amount = _r(amount)
    taxes_total = _r(amount_taxes or 0)
    ttc = _r(amount + taxes_total)
    totals = [_r(t) for t in totals]
    ecart = _r(ttc - sum(totals))
    if abs(ecart) > TOLERANCE:
        raise DivisionErreur(
            "La somme des parts "
            f"({_r(sum(totals)):.2f} $) ne retombe pas sur le total du reçu "
            f"({ttc:.2f} $) : il reste {ecart:.2f} $ à répartir."
        )
    totals[-1] = _r(totals[-1] + ecart)
    if totals[-1] <= 0:
        raise DivisionErreur("Chaque part doit avoir un montant supérieur à 0 $.")
    hts = repartir(amount, totals)
    if amount_taxes is None:
        taxes: list[Optional[float]] = [None] * n
    else:
        taxes = [max(0.0, _r(t - h)) for t, h in zip(totals, hts)]
    poids_taxes = [float(t or 0) for t in taxes]
    tps = (
        repartir(amount_tps, poids_taxes)
        if amount_tps is not None and amount_taxes is not None
        else [None] * n
    )
    tvq = (
        repartir(amount_tvq, poids_taxes)
        if amount_tvq is not None and amount_taxes is not None
        else [None] * n
    )
    return [
        {
            "total": totals[i],
            "amount": hts[i],
            "amount_taxes": taxes[i],
            "amount_tps": tps[i],
            "amount_tvq": tvq[i],
        }
        for i in range(n)
    ]


async def creer_achat_divise(
    db: AsyncSession,
    data: AchatDiviseCreate,
    *,
    user_id: Optional[int],
) -> list[Achat]:
    """Crée les parts d'un reçu divisé (un achat par projet) et les lie par
    ``groupe_id``. Ne committe pas ; ne pousse pas vers QuickBooks (le
    push du groupe est déclenché par l'appelant sur la tête)."""
    if float(data.amount or 0) <= 0:
        raise DivisionErreur(
            "Entre le total de la facture : le montant hors taxes doit être "
            "supérieur à 0 $."
        )
    valider_parts(data.parts)
    ids = [p.project_id for p in data.parts]
    projets = {
        p.id: p
        for p in (
            await db.execute(select(Project).where(Project.id.in_(ids)))
        ).scalars()
    }
    manquants = [pid for pid in ids if pid not in projets]
    if manquants:
        raise DivisionErreur(
            "Projet introuvable : "
            + ", ".join(f"#{pid}" for pid in manquants)
        )
    montants = ventiler_parts(
        amount=data.amount,
        amount_taxes=data.amount_taxes,
        amount_tps=data.amount_tps,
        amount_tvq=data.amount_tvq,
        totals=[p.total for p in data.parts],
    )
    communs = data.model_dump(exclude_unset=True, exclude={"parts"})
    for k in (
        "amount", "amount_taxes", "amount_tps", "amount_tvq",
        "is_billable", "status", "hours",
    ):
        communs.pop(k, None)
    statut = (data.status or "").strip() or AchatStatus.RECEIVED.value
    # Heures (facture de sous-traitant au taux horaire) : réparties comme
    # les montants — recopiées entières, chaque projet refacturerait toutes
    # les heures.
    heures: Optional[list[float]] = (
        repartir(data.hours, [m["total"] for m in montants])
        if data.hours is not None
        else None
    )

    achats: list[Achat] = []
    for i, (part, m) in enumerate(zip(data.parts, montants)):
        # « À refacturer » : choix de LA part s'il est donné, sinon choix
        # global, sinon défaut du projet (contrat / bon de travail → oui).
        # Le verrou manuel n'est posé que sur un choix explicite.
        if part.is_billable is not None:
            billable, choix_manuel = bool(part.is_billable), True
        elif data.is_billable is not None:
            billable, choix_manuel = bool(data.is_billable), True
        else:
            billable = await refacturable_par_defaut(db, part.project_id)
            choix_manuel = False
        a = Achat(
            **communs,
            project_id=part.project_id,
            amount=m["amount"],
            amount_taxes=m["amount_taxes"],
            amount_tps=m["amount_tps"],
            amount_tvq=m["amount_tvq"],
            hours=heures[i] if heures is not None else None,
            status=statut,
            is_billable=billable,
            billable_manual=choix_manuel,
            created_by_user_id=user_id,
        )
        db.add(a)
        achats.append(a)
    await db.flush()
    tete = achats[0]
    for a in achats:
        a.groupe_id = tete.id
        await apply_payment_defaults(db, a)
    await db.flush()
    log.info(
        "Reçu divisé : groupe %s, %d parts (projets %s)",
        tete.id, len(achats), ids,
    )
    return achats


async def parts_du_groupe(
    db: AsyncSession, achat: Achat, *, actives_seulement: bool = True
) -> list[Achat]:
    """Les parts du groupe de ``achat`` (lui compris s'il est actif),
    triées par id ; ``[achat]`` pour un achat simple. ``actives_seulement``
    écarte les parts annulées (et les sorties d'inventaire)."""
    if not achat.groupe_id:
        return [achat]
    q = select(Achat).where(Achat.groupe_id == achat.groupe_id)
    if actives_seulement:
        q = q.where(
            Achat.status != AchatStatus.CANCELLED.value,
            Achat.kind != KIND_INVENTAIRE,
        )
    return list((await db.execute(q.order_by(Achat.id))).scalars().all())


def ttc(a: Achat) -> float:
    return _r(float(a.amount or 0) + float(a.amount_taxes or 0))


def montants_groupe(parts: Sequence[Achat]) -> SimpleNamespace:
    """Sommes des montants des parts, sous la forme (amount, amount_taxes,
    amount_tps, amount_tvq) attendue par le calcul de taxe du push QB.
    Une composante vaut None si TOUTES les parts l'ignorent (taxes), ou si
    UNE part l'ignore (TPS/TVQ : la ventilation se recalcule alors)."""

    def _somme(champ: str, *, tolerant: bool) -> Optional[float]:
        vals = [getattr(p, champ) for p in parts]
        if tolerant:
            if all(v is None for v in vals):
                return None
        elif any(v is None for v in vals):
            return None
        return _r(sum(float(v or 0) for v in vals))

    return SimpleNamespace(
        amount=_r(sum(float(p.amount or 0) for p in parts)),
        amount_taxes=_somme("amount_taxes", tolerant=True),
        amount_tps=_somme("amount_tps", tolerant=False),
        amount_tvq=_somme("amount_tvq", tolerant=False),
    )


async def propager_champs_communs(db: AsyncSession, achat: Achat) -> int:
    """Recopie les champs de la facture (:data:`CHAMPS_COMMUNS`) de
    ``achat`` sur les autres parts de son groupe. Renvoie le nombre de
    parts modifiées. Sans effet pour un achat simple."""
    if not achat.groupe_id:
        return 0
    soeurs = [
        s
        for s in await parts_du_groupe(db, achat, actives_seulement=False)
        if s.id != achat.id
    ]
    modifiees = 0
    for s in soeurs:
        changee = False
        for champ in CHAMPS_COMMUNS:
            val = getattr(achat, champ)
            if getattr(s, champ) != val:
                setattr(s, champ, val)
                changee = True
        if changee:
            modifiees += 1
    if modifiees:
        await db.flush()
    return modifiees


async def verifier_projet_unique(db: AsyncSession, achat: Achat) -> None:
    """Une part par projet : déplacer une part sur le projet d'une sœur
    active est refusé (DivisionErreur) — sinon la dédup y verrait un
    doublon. Sans effet pour un achat simple."""
    if not achat.groupe_id or not achat.project_id:
        return
    for s in await parts_du_groupe(db, achat):
        if s.id != achat.id and s.project_id == achat.project_id:
            raise DivisionErreur(
                f"Le projet est déjà une part de ce reçu divisé (achat "
                f"#{s.id}). Pour regrouper deux parts, ajuste les montants "
                "puis supprime l'autre part."
            )


async def propager_statut_paiement(db: AsyncSession, achat: Achat) -> int:
    """Une facture fournisseur se paie en entier : le statut reçu ↔ payé,
    la date de paiement et l'échéance d'une part valent pour ses sœurs
    actives (l'annulation, elle, reste propre à la part). Renvoie le
    nombre de sœurs alignées."""
    if not achat.groupe_id or achat.status not in (
        AchatStatus.RECEIVED.value,
        AchatStatus.PAID.value,
    ):
        return 0
    n = 0
    for s in await parts_du_groupe(db, achat):
        if s.id == achat.id or s.status == achat.status:
            continue
        s.status = achat.status
        s.paid_at = achat.paid_at
        s.due_at = achat.due_at
        n += 1
    if n:
        await db.flush()
    return n


async def retirer_part_annulee(
    db: AsyncSession, part: Achat
) -> Optional[dict[str, Any]]:
    """Part passée à « annulé » (ou en cours de suppression) : s'il reste
    des parts actives, la transaction QB du groupe est réécrite SANS sa
    ligne — dans la requête, même session ; une erreur QB remonte à
    l'appelant (AchatSyncError) et rien n'est annulé — et la part perd son
    lien QB (plus de ligne dans QB : les pulls ne la ressusciteront pas
    « payée »). Dernière part active : la transaction QB reste entière,
    avec son lien, comme un achat simple annulé. Renvoie le résultat du
    push, ou None s'il n'y en a pas eu."""
    if not part.groupe_id:
        return None
    soeurs = [s for s in await parts_du_groupe(db, part) if s.id != part.id]
    if not soeurs:
        return None
    avait_lien = bool(part.qbo_bill_id or part.qbo_purchase_id)
    part.qbo_bill_id = None
    part.qbo_sync_token = None
    part.qbo_doc_number = None
    part.qbo_bill_payment_id = None
    await db.flush()
    if not avait_lien:
        return None
    from app.services.achat_qbo import sync_achat_to_qbo

    return await sync_achat_to_qbo(db, soeurs[0].id)


def premieres_parts(rows: Iterable[tuple[int, Optional[int]]]) -> list[int]:
    """Ids à pousser vers QB parmi des couples (id, groupe_id) : une seule
    part par reçu divisé (pousser une part pousse tout le groupe), tous les
    achats simples. Ordre conservé."""
    vus: set[int] = set()
    out: list[int] = []
    for aid, gid in rows:
        if gid:
            if gid in vus:
                continue
            vus.add(int(gid))
        out.append(int(aid))
    return out
