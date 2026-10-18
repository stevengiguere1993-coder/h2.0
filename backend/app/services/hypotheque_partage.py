"""Hypothèque conjointe — une hypothèque, plusieurs immeubles, une part
chacun (Steven 2026-10-06 : « le 710 Legendre et le 9085 Millen ont une
hypothèque conjointe, mais ici le calcul est en 2 shots »).

Modèle : ``Hypotheque.immeuble_id`` reste l'immeuble PRINCIPAL (celui où
l'hypothèque a été saisie) ; ``HypothequeImmeuble`` porte, pour une
hypothèque conjointe, la part en % de chaque immeuble couvert (principal
inclus, total 100). Sans ligne de répartition = hypothèque simple, 100 %
sur son immeuble.

Règle d'agrégation, partout (fiche, P&L, prévisionnel, équité, portail
investisseur) : un immeuble ne porte que SA part de la balance et du
paiement. La somme des parts des immeubles couverts redonne exactement
l'hypothèque — plus de double compte quand les deux immeubles sont dans
le même portefeuille, et pas de dette « oubliée » quand on ne regarde
qu'un seul des deux.

Les helpers posent ``ATTR_PART`` (fraction 0..1) sur l'objet Hypotheque
pour l'immeuble consulté ; ``part_de(h)`` la relit (1.0 par défaut).
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from sqlalchemy import or_, select

from app.models.immobilier import (
    Hypotheque,
    HypothequeImmeuble,
    HypothequeStatus,
    Immeuble,
)
from app.services.hypotheque_calc import charger_debourses

#: Attribut posé sur l'objet Hypotheque : part (fraction 0..1) de
#: l'immeuble dans le contexte duquel l'hypothèque a été chargée.
ATTR_PART = "part_immeuble_cache"

#: Tolérance sur le total des parts (saisie en %, deux décimales).
TOLERANCE_PCT = 0.01


def part_de(hyp) -> float:
    """Part (0..1) de l'immeuble consulté — 1.0 pour une hypothèque
    simple ou hors contexte d'immeuble."""
    p = getattr(hyp, ATTR_PART, None)
    return 1.0 if p is None else float(p)


def _filtre_statut(q, *, actives_seulement: bool, statuts_exclus: Optional[Sequence[str]]):
    if statuts_exclus:
        return q.where(Hypotheque.status.notin_(list(statuts_exclus)))
    if actives_seulement:
        return q.where(Hypotheque.status == HypothequeStatus.ACTIVE.value)
    return q


async def repartitions_de(
    db, hyp_ids: Iterable[int]
) -> dict[int, list[HypothequeImmeuble]]:
    """Lignes de répartition par hypothèque (vide = hypothèque simple)."""
    ids = [int(i) for i in hyp_ids]
    out: dict[int, list[HypothequeImmeuble]] = {i: [] for i in ids}
    if not ids:
        return out
    rows = (
        await db.execute(
            select(HypothequeImmeuble)
            .where(HypothequeImmeuble.hypotheque_id.in_(ids))
            .order_by(HypothequeImmeuble.id.asc())
        )
    ).scalars().all()
    for r in rows:
        out.setdefault(int(r.hypotheque_id), []).append(r)
    return out


async def hypotheques_par_immeuble(
    db,
    imm_ids: Iterable[int],
    *,
    actives_seulement: bool = True,
    statuts_exclus: Optional[Sequence[str]] = None,
) -> dict[int, list[tuple[Hypotheque, float]]]:
    """Pour chaque immeuble demandé : ses hypothèques avec la PART (0..1)
    qu'il en porte — les simples à 1.0, les conjointes à leur %.

    Une hypothèque conjointe apparaît sous chaque immeuble couvert de la
    liste ; une somme sur tous ses immeubles redonne 100 %. Le déboursé
    par tranches est chargé (``charger_debourses``)."""
    ids = [int(i) for i in imm_ids]
    out: dict[int, list[tuple[Hypotheque, float]]] = {i: [] for i in ids}
    if not ids:
        return out
    sous_req = select(HypothequeImmeuble.hypotheque_id).where(
        HypothequeImmeuble.immeuble_id.in_(ids)
    )
    q = select(Hypotheque).where(
        or_(Hypotheque.immeuble_id.in_(ids), Hypotheque.id.in_(sous_req))
    )
    q = _filtre_statut(
        q, actives_seulement=actives_seulement, statuts_exclus=statuts_exclus
    )
    hyps = list((await db.execute(q)).scalars().all())
    if not hyps:
        return out
    await charger_debourses(db, hyps)
    reparts = await repartitions_de(db, [h.id for h in hyps])
    for h in hyps:
        lignes = reparts.get(h.id) or []
        if not lignes:
            if h.immeuble_id in out:
                out[h.immeuble_id].append((h, 1.0))
            continue
        for ligne in lignes:
            if ligne.immeuble_id in out:
                out[ligne.immeuble_id].append(
                    (h, float(ligne.part_pct or 0) / 100.0)
                )
    return out


async def hypotheques_de_l_immeuble(
    db,
    immeuble_id: int,
    *,
    actives_seulement: bool = True,
    statuts_exclus: Optional[Sequence[str]] = None,
) -> list[Hypotheque]:
    """Hypothèques d'UN immeuble (simples + conjointes qui le couvrent),
    chacune avec ``ATTR_PART`` posé pour cet immeuble, triées par rang."""
    par_imm = await hypotheques_par_immeuble(
        db,
        [immeuble_id],
        actives_seulement=actives_seulement,
        statuts_exclus=statuts_exclus,
    )
    hyps: list[Hypotheque] = []
    for h, part in par_imm.get(int(immeuble_id), []):
        setattr(h, ATTR_PART, part)
        hyps.append(h)
    hyps.sort(key=lambda h: ((h.rang or 99), h.id))
    return hyps


def balance_part(hyp, balance_totale: float) -> float:
    return round(float(balance_totale) * part_de(hyp), 2)


def paiement_part(hyp) -> float:
    return round(float(hyp.paiement_mensuel or 0) * part_de(hyp), 2)


# ── Validation / enregistrement d'une répartition ────────────────────


class RepartitionInvalide(ValueError):
    """Répartition refusée (message en français, prêt pour un 422)."""


async def valider_repartition(db, items: Sequence) -> list[tuple[int, float]]:
    """Normalise une répartition saisie : immeubles existants et
    distincts, parts > 0, total 100 ± tolérance. Retourne
    ``[(immeuble_id, part_pct), …]`` dans l'ordre saisi. Deux lignes ou
    plus sont attendues (une seule = hypothèque simple, à envoyer vide).
    """
    paires: list[tuple[int, float]] = []
    vus: set[int] = set()
    for it in items:
        imm_id = int(getattr(it, "immeuble_id", None) or it["immeuble_id"])
        pct = float(getattr(it, "part_pct", None) or it["part_pct"])
        if imm_id in vus:
            raise RepartitionInvalide(
                "Un immeuble ne peut apparaître qu'une fois dans la répartition."
            )
        if pct <= 0 or pct > 100:
            raise RepartitionInvalide(
                "Chaque part doit être comprise entre 0 (exclu) et 100 %."
            )
        vus.add(imm_id)
        paires.append((imm_id, round(pct, 4)))
    if len(paires) < 2:
        raise RepartitionInvalide(
            "Une hypothèque conjointe couvre au moins deux immeubles ; "
            "pour un seul immeuble, n'envoie pas de répartition."
        )
    total = sum(p for _, p in paires)
    if abs(total - 100.0) > TOLERANCE_PCT:
        raise RepartitionInvalide(
            f"Les parts doivent totaliser 100 % (actuellement {total:g} %)."
        )
    existants = set(
        (
            await db.execute(
                select(Immeuble.id).where(Immeuble.id.in_(list(vus)))
            )
        ).scalars().all()
    )
    manquants = sorted(vus - set(int(x) for x in existants))
    if manquants:
        raise RepartitionInvalide(
            f"Immeuble(s) introuvable(s) : {', '.join(str(m) for m in manquants)}."
        )
    return paires


async def enregistrer_repartition(
    db, hyp: Hypotheque, paires: Optional[Sequence[tuple[int, float]]]
) -> None:
    """Remplace la répartition de ``hyp``. ``None`` ou vide = hypothèque
    simple (lignes supprimées). Si l'immeuble principal ne fait plus
    partie des immeubles couverts, l'hypothèque est ré-attachée au
    premier immeuble de la liste (elle disparaît de l'ancien)."""
    from sqlalchemy import delete

    await db.execute(
        delete(HypothequeImmeuble).where(
            HypothequeImmeuble.hypotheque_id == hyp.id
        )
    )
    if not paires:
        return
    if hyp.immeuble_id not in {imm_id for imm_id, _ in paires}:
        hyp.immeuble_id = paires[0][0]
    for imm_id, pct in paires:
        db.add(
            HypothequeImmeuble(
                hypotheque_id=hyp.id, immeuble_id=imm_id, part_pct=pct
            )
        )
    await db.flush()


async def noms_immeubles(db, ids: Iterable[int]) -> dict[int, str]:
    ids = list({int(i) for i in ids})
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Immeuble.id, Immeuble.name).where(Immeuble.id.in_(ids))
        )
    ).all()
    return {int(i): str(n) for i, n in rows}
