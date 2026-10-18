"""Fin OPPOSABLE d'un bail et solde dû — une seule règle, partagée.

Retour Steven (2026-10-18) : « lorsque nous mettons fin à un locataire,
présentement il continue de s'accumuler une dette comme non-paiement
dans les mois qui suivent ». Trois vues calculaient « jusqu'à quand un
bail doit des loyers » chacune à leur façon, et toutes trois laissaient
courir un bail AU MOIS (chambres) après son départ parce que « les
loyers courent sans égard à la date de fin ». Ici, la règle unique :

- bail TERMINÉ / RÉSILIÉ : sa date de fin, point ;
- bail actif dont le DÉPART EST DÉCLARÉ (``depart_declare_le``) : sa
  date de fin, même au mois ;
- bail actif annuel : sa date de fin (une reconduction l'étire) ;
- bail actif AU MOIS sans départ déclaré : aucune fin — il court.

Le solde d'un bail = loyers des 1ers de mois couverts (du début de
collecte à aujourd'hui, bornés à la fin opposable) + frais − paiements,
jamais négatif. Même formule que la colonne « Solde » de
/loyers/overview — c'est elle qu'on reproduit ici pour les fiches
(logement, locataire) et pour l'assistant.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.immobilier import (
    Bail,
    BailStatus,
    FraisLocatif,
    Immeuble,
    Logement,
    PaiementLoyer,
)


def fin_reelle(bail: Bail) -> Optional[date]:
    """Date de fin OPPOSABLE du bail pour le calcul des loyers dus
    (None = le bail court sans fin connue : bail au mois en place)."""
    if bail.date_fin is None:
        return None
    if bail.status != BailStatus.ACTIF.value:
        return bail.date_fin
    if getattr(bail, "depart_declare_le", None) is not None:
        return bail.date_fin
    if bail.au_mois:
        return None
    return bail.date_fin


def apres_la_fin(bail: Bail, mois: date) -> bool:
    """Vrai si ``mois`` (1er du mois) est APRÈS la fin opposable du bail :
    rien n'y est attendu, seule une dette antérieure peut s'y afficher."""
    fin = fin_reelle(bail)
    return fin is not None and fin < mois


def nb_mois_echus(
    bail: Bail, *, depuis: date, jusqua: date, today: Optional[date] = None
) -> int:
    """Nombre de 1ers de mois couverts par le bail entre ``depuis`` (début
    de collecte) et ``jusqua`` (mois affiché), bornés à aujourd'hui et à
    la fin opposable du bail."""
    today = today or date.today()
    if bail.date_debut is None:
        return 0
    debut = max(bail.date_debut.replace(day=1), depuis.replace(day=1))
    fin = min(jusqua.replace(day=1), today.replace(day=1))
    fr = fin_reelle(bail)
    if fr is not None:
        fin = min(fin, fr.replace(day=1))
    if fin < debut:
        return 0
    return (fin.year - debut.year) * 12 + (fin.month - debut.month) + 1


def debut_collecte(immeuble, solde_depuis: date) -> date:
    """Début de la collecte pour un immeuble : la date posée sur sa fiche
    (ramenée au 1er du mois), jamais avant le démarrage du pôle."""
    d = getattr(immeuble, "collecte_depuis", None) if immeuble is not None else None
    return max(solde_depuis, d.replace(day=1)) if d else solde_depuis


async def soldes_par_bail(
    db: AsyncSession,
    baux: Iterable[Bail],
    *,
    today: Optional[date] = None,
) -> Dict[int, float]:
    """``{bail_id: solde dû}`` pour une poignée de baux (fiche logement,
    fiche locataire) — trois requêtes groupées, jamais une par bail."""
    from app.services.locatif_demarrage import get_demarrage

    baux = [b for b in baux if b is not None]
    if not baux:
        return {}
    today = today or date.today()
    solde_depuis = await get_demarrage()
    mois_courant = today.replace(day=1)

    log_ids = {b.logement_id for b in baux if b.logement_id}
    log_by_id: Dict[int, Logement] = {}
    if log_ids:
        for lg in (
            await db.execute(select(Logement).where(Logement.id.in_(list(log_ids))))
        ).scalars().all():
            log_by_id[lg.id] = lg
    imm_ids = {lg.immeuble_id for lg in log_by_id.values() if lg.immeuble_id}
    imm_by_id: Dict[int, Immeuble] = {}
    if imm_ids:
        for im in (
            await db.execute(select(Immeuble).where(Immeuble.id.in_(list(imm_ids))))
        ).scalars().all():
            imm_by_id[im.id] = im

    depuis_bail: Dict[int, date] = {}
    for b in baux:
        lg = log_by_id.get(b.logement_id)
        im = imm_by_id.get(lg.immeuble_id) if lg else None
        depuis_bail[b.id] = debut_collecte(im, solde_depuis)

    ids = [b.id for b in baux]
    paye: Dict[int, float] = {}
    for bid, mc, montant in (
        await db.execute(
            select(PaiementLoyer.bail_id, PaiementLoyer.mois_couvert, PaiementLoyer.montant)
            .where(PaiementLoyer.bail_id.in_(ids), PaiementLoyer.mois_couvert >= solde_depuis)
        )
    ).all():
        if mc is not None and mc >= depuis_bail.get(bid, solde_depuis):
            paye[bid] = paye.get(bid, 0.0) + float(montant or 0)
    frais: Dict[int, float] = {}
    for bid, mc, montant in (
        await db.execute(
            select(FraisLocatif.bail_id, FraisLocatif.mois_couvert, FraisLocatif.montant)
            .where(
                FraisLocatif.bail_id.in_(ids),
                FraisLocatif.mois_couvert >= solde_depuis,
                FraisLocatif.mois_couvert <= mois_courant,
            )
        )
    ).all():
        if mc is not None and mc >= depuis_bail.get(bid, solde_depuis):
            frais[bid] = frais.get(bid, 0.0) + float(montant or 0)

    out: Dict[int, float] = {}
    for b in baux:
        n = nb_mois_echus(
            b, depuis=depuis_bail.get(b.id, solde_depuis), jusqua=mois_courant, today=today
        )
        solde = n * float(b.loyer_mensuel or 0) + frais.get(b.id, 0.0) - paye.get(b.id, 0.0)
        out[b.id] = max(0.0, round(solde, 2))
    return out


async def solde_bail(db: AsyncSession, bail: Bail) -> float:
    """Solde dû d'UN bail (≥ 0)."""
    return (await soldes_par_bail(db, [bail])).get(bail.id, 0.0)


async def nb_frais_et_paiements(db: AsyncSession, bail_id: int) -> int:
    """Nombre de lignes d'argent (paiements + frais) sur un bail."""
    n_p = (
        await db.execute(
            select(func.count(PaiementLoyer.id)).where(PaiementLoyer.bail_id == bail_id)
        )
    ).scalar_one()
    n_f = (
        await db.execute(
            select(func.count(FraisLocatif.id)).where(FraisLocatif.bail_id == bail_id)
        )
    ).scalar_one()
    return int(n_p or 0) + int(n_f or 0)


__all__ = [
    "apres_la_fin",
    "debut_collecte",
    "fin_reelle",
    "nb_frais_et_paiements",
    "nb_mois_echus",
    "solde_bail",
    "soldes_par_bail",
]
